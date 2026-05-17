"""Integration tests for backend, database, and worker suite."""

from __future__ import annotations

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
def config_dir(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    bounds = data_dir / "bounds.geojson"
    stations = data_dir / "stations.csv"
    incidents = data_dir / "incidents.csv"
    bounds.write_text('{"type":"FeatureCollection","features":[]}\n')
    stations.write_text("StationID,Stations,lat,lon\n")
    incidents.write_text("incident_id,lat,lon,datetime\n")

    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        "\n".join(
            [
                "city:",
                "  geography:",
                f"    bounds_geojson: {bounds}",
                "  stations:",
                f"    csv_path: {stations}",
                "demand:",
                f"  incidents_csv: {incidents}",
            ]
        )
        + "\n"
    )
    return cfg_dir


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


def test_authenticated_job_moves_from_api_to_worker_queue_and_result(
    session_factory,
    config_dir,
    tmp_path,
    monkeypatch,
):
    storage_root = tmp_path / "storage"
    source_output = tmp_path / "source_output"
    source_output.mkdir()
    monkeypatch.setattr("db.storage.STORAGE_ROOT", storage_root)
    monkeypatch.setattr(auth_routes, "SessionLocal", session_factory)
    monkeypatch.setattr(jobs_routes, "SessionLocal", session_factory)
    monkeypatch.setattr(processor, "run_sim", sim_service.run_sim)

    def fake_core_run(cfg):
        assert Path(cfg.city.geography.bounds_geojson).exists()
        paths = []
        for filename in ("incident_report.csv", "apparatus_events.csv", "step_trace.csv"):
            path = source_output / filename
            path.write_text(filename)
            paths.append(str(path))
        return tuple(paths)

    monkeypatch.setattr(sim_service, "core_run", fake_core_run)

    client = TestClient(app)
    client.post("/auth/register", params={"username": "queue-user", "password": "secret"})
    login = client.post("/auth/login", params={"username": "queue-user", "password": "secret"})
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
        fetched_job_id, payload = runner.fetch_next_job(conn)
        assert fetched_job_id == job_id
        assert db.get(Job, job_id).status == "running"

        processor.process_job(conn, fetched_job_id, json.dumps(payload))
        db.commit()

    result = client.get(f"/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    body = result.json()
    assert result.status_code == 200
    assert body["status"] == "done"
    assert Path(body["result"]["path_incident_report"]).read_text() == "incident_report.csv"
    assert Path(body["payload"]["config_dir"]) == storage_root / "jobs" / str(job_id) / "configs"
