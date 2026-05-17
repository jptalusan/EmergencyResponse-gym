"""End-to-end tests spanning all packages under src."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.routes import auth as auth_routes
from backend.routes import jobs as jobs_routes
from backend.services import sim as sim_service
from db.models import Base, Job
from emergency_response import app as er_app
from emergency_response.models.scenario import Scenario
from worker import processor, runner


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def full_stack_config(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    bounds = data_dir / "bounds.geojson"
    stations = data_dir / "stations.csv"
    incidents = data_dir / "incidents.csv"
    bounds.write_text('{"type":"FeatureCollection","features":[]}\n')
    stations.write_text("StationID,Stations,lat,lon\n")
    with open(incidents, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["incident_id", "lat", "lon", "incident_type", "incident_level", "datetime", "category"])
        writer.writerow([1, 36.16, -86.74, "EMS & Rescue", "Moderate", "2022-01-01 00:00:00", "Nine"])
        writer.writerow([2, 36.14, -86.76, "Building Fire", "High", "2022-01-01 00:05:00", "One"])

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "\n".join(
            [
                "seed: 42",
                "city:",
                "  geography:",
                f"    bounds_geojson: {bounds}",
                "  stations:",
                f"    csv_path: {stations}",
                "demand:",
                "  type: empirical",
                f"  incidents_csv: {incidents}",
                "solver:",
                "  type: nearest",
                "policy:",
                "  type: nearest",
                "simulation:",
                "  max_incidents: 2",
                "  drain: true",
                "  max_drain_time: 20000.0",
            ]
        )
        + "\n"
    )
    return config_dir, incidents


class QueueCursor:
    def __init__(self, session):
        self.session = session
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        if "SELECT id, payload" in sql:
            job = self.session.query(Job).filter_by(status="pending").order_by(Job.created_at).first()
            self.row = None if job is None else (job.id, job.payload)
        elif "SET status = 'running'" in sql:
            job = self.session.get(Job, params[0])
            job.status = "running"
        elif "SET status = 'done'" in sql:
            result_json, job_id = params
            job = self.session.get(Job, job_id)
            job.status = "done"
            job.result = json.loads(result_json)
        elif "SET status = 'failed'" in sql:
            error, job_id = params
            job = self.session.get(Job, job_id)
            job.status = "failed"
            job.error = error
        else:
            raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchone(self):
        return self.row


class QueueConnection:
    def __init__(self, session):
        self.session = session

    def cursor(self):
        return QueueCursor(self.session)


def test_api_to_worker_to_emergency_response_simulation_stack(
    session_factory,
    full_stack_config,
    tmp_path,
    mock_geography,
    sample_stations,
    sample_apparatus,
    monkeypatch,
):
    config_dir, incidents_csv = full_stack_config
    storage_root = tmp_path / "storage"
    monkeypatch.setattr("db.storage.STORAGE_ROOT", storage_root)
    monkeypatch.setattr(auth_routes, "SessionLocal", session_factory)
    monkeypatch.setattr(jobs_routes, "SessionLocal", session_factory)
    monkeypatch.setattr(processor, "run_sim", sim_service.run_sim)

    def core_run_through_emergency_response(cfg):
        scenario = Scenario(
            geography=mock_geography,
            stations=sample_stations,
            apparatus=sample_apparatus,
            incidents_csv=str(incidents_csv),
            bounds_geojson=None,
            random_seed=cfg.seed,
        )
        original_build_scenario = er_app.build_scenario
        original_get_project_root = er_app.get_project_root
        try:
            er_app.build_scenario = lambda cfg, orig_cwd: (scenario, None)
            er_app.get_project_root = lambda: str(tmp_path)
            return er_app.emergency_response_sim(cfg)
        finally:
            er_app.build_scenario = original_build_scenario
            er_app.get_project_root = original_get_project_root

    monkeypatch.setattr(sim_service, "core_run", core_run_through_emergency_response)

    client = TestClient(app)
    assert client.post("/auth/register", params={"username": "full-stack", "password": "secret"}).status_code == 200
    login = client.post("/auth/login", params={"username": "full-stack", "password": "secret"})
    token = login.json()["access_token"]
    submitted = client.post(
        "/jobs",
        json={"config_dir": str(config_dir), "config_name": "config"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert submitted.status_code == 200
    job_id = submitted.json()["id"]

    with session_factory() as db:
        conn = QueueConnection(db)
        queued_job = runner.fetch_next_job(conn)
        assert queued_job is not None
        queued_job_id, payload = queued_job
        assert queued_job_id == job_id
        assert db.get(Job, job_id).status == "running"

        processor.process_job(conn, queued_job_id, json.dumps(payload))
        db.commit()

    fetched = client.get(f"/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["status"] == "done"
    assert Path(body["payload"]["config_dir"]) == storage_root / "jobs" / str(job_id) / "configs"

    incident_report = Path(body["result"]["path_incident_report"])
    apparatus_events = Path(body["result"]["path_apparatus_events"])
    step_trace = Path(body["result"]["path_step_trace"])
    assert incident_report == storage_root / "jobs" / str(job_id) / "output" / "incident_report.csv"
    assert apparatus_events.exists()
    assert step_trace.exists()

    with open(incident_report, newline="") as f:
        incident_rows = list(csv.DictReader(f))
    with open(apparatus_events, newline="") as f:
        event_rows = list(csv.DictReader(f))
    with open(step_trace, newline="") as f:
        step_rows = list(csv.DictReader(f))

    assert {row["incident_id"] for row in incident_rows} == {"1", "2"}
    assert any(row["event"] == "dispatch" for row in event_rows)
    assert [row["step"] for row in step_rows] == ["1", "2"]
