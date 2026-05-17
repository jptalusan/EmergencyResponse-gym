"""End-to-end tests for the backend, database, and worker suite."""

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
from worker import processor


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


class SessionBackedCursor:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        if "SET status = 'done'" in sql:
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
            raise AssertionError(f"Unexpected worker SQL: {sql}")


class SessionBackedConnection:
    def __init__(self, session):
        self.session = session

    def cursor(self):
        return SessionBackedCursor(self.session)


def test_api_submission_worker_processing_and_retrieval_roundtrip(session_factory, tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    bounds = data_dir / "bounds.geojson"
    stations = data_dir / "stations.csv"
    incidents = data_dir / "incidents.csv"
    bounds.write_text('{"type":"FeatureCollection","features":[]}\n')
    stations.write_text("StationID,Stations,lat,lon\n")
    incidents.write_text("incident_id,lat,lon,datetime\n")

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
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
    source_output = tmp_path / "source_output"
    source_output.mkdir()
    monkeypatch.setattr("db.storage.STORAGE_ROOT", tmp_path / "storage")
    monkeypatch.setattr(auth_routes, "SessionLocal", session_factory)
    monkeypatch.setattr(jobs_routes, "SessionLocal", session_factory)
    monkeypatch.setattr(processor, "run_sim", sim_service.run_sim)

    def fake_core_run(cfg):
        assert Path(cfg.demand.incidents_csv).exists()
        paths = []
        for filename in ("incident_report.csv", "apparatus_events.csv", "step_trace.csv"):
            path = source_output / filename
            path.write_text(filename)
            paths.append(str(path))
        return tuple(paths)

    monkeypatch.setattr(sim_service, "core_run", fake_core_run)

    client = TestClient(app)
    client.post("/auth/register", params={"username": "roundtrip", "password": "secret"})
    login = client.post("/auth/login", params={"username": "roundtrip", "password": "secret"})
    token = login.json()["access_token"]
    submitted = client.post(
        "/jobs",
        json={"config_dir": str(config_dir), "config_name": "config"},
        headers={"Authorization": f"Bearer {token}"},
    )
    job_id = submitted.json()["id"]

    with session_factory() as db:
        job = db.get(Job, job_id)
        processor.process_job(SessionBackedConnection(db), job.id, json.dumps(job.payload))
        db.commit()

    response = client.get(f"/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done"
    assert Path(body["result"]["path_incident_report"]).read_text() == "incident_report.csv"
    assert Path(body["result"]["path_apparatus_events"]).read_text() == "apparatus_events.csv"
    assert Path(body["result"]["path_step_trace"]).read_text() == "step_trace.csv"
