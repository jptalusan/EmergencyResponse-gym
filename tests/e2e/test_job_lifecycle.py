"""End-to-end tests for the job lifecycle."""

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
from db import crud
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


@pytest.fixture
def runnable_config(tmp_path):
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
    return config_dir


class SqlAlchemyWorkerCursor:
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


class SqlAlchemyWorkerConnection:
    def __init__(self, session):
        self.session = session

    def cursor(self):
        return SqlAlchemyWorkerCursor(self.session)


def test_authenticated_job_can_be_submitted_processed_and_retrieved(
    session_factory,
    runnable_config,
    tmp_path,
    monkeypatch,
):
    storage_root = tmp_path / "storage"
    output_dir = tmp_path / "sim_output"
    output_dir.mkdir()
    monkeypatch.setattr("db.storage.STORAGE_ROOT", storage_root)
    monkeypatch.setattr(auth_routes, "SessionLocal", session_factory)
    monkeypatch.setattr(jobs_routes, "SessionLocal", session_factory)
    monkeypatch.setattr(processor, "run_sim", sim_service.run_sim)

    def fake_core_run(cfg):
        assert Path(cfg.city.geography.bounds_geojson).exists()
        outputs = {
            "incident_report.csv": "incident_id,status\n1,done\n",
            "apparatus_events.csv": "apparatus_id,event\n1,dispatch\n",
            "step_trace.csv": "step,reward\n1,-1\n",
        }
        paths = []
        for filename, content in outputs.items():
            path = output_dir / filename
            path.write_text(content)
            paths.append(str(path))
        return tuple(paths)

    monkeypatch.setattr(sim_service, "core_run", fake_core_run)

    client = TestClient(app)
    register = client.post("/auth/register", params={"username": "e2e-user", "password": "secret"})
    assert register.status_code == 200

    login = client.post("/auth/login", params={"username": "e2e-user", "password": "secret"})
    assert login.status_code == 200
    token = login.json()["access_token"]

    submitted = client.post(
        "/jobs",
        json={"config_dir": str(runnable_config), "config_name": "config"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert submitted.status_code == 200
    job_id = submitted.json()["id"]
    stored_config_dir = Path(submitted.json()["payload"]["config_dir"])
    assert stored_config_dir == storage_root / "jobs" / str(job_id) / "configs"
    assert (stored_config_dir / "config.yaml").exists()
    assert {path.name for path in (storage_root / "jobs" / str(job_id) / "data").iterdir()} == {
        "bounds.geojson",
        "stations.csv",
        "incidents.csv",
    }

    with session_factory() as db:
        job = crud.get_job(db, job_id)
        assert job.status == "pending"
        processor.process_job(SqlAlchemyWorkerConnection(db), job.id, json.dumps(job.payload))
        db.commit()

    fetched = client.get(f"/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["status"] == "done"
    assert body["result"] == {
        "path_incident_report": str(storage_root / "jobs" / str(job_id) / "output" / "incident_report.csv"),
        "path_apparatus_events": str(storage_root / "jobs" / str(job_id) / "output" / "apparatus_events.csv"),
        "path_step_trace": str(storage_root / "jobs" / str(job_id) / "output" / "step_trace.csv"),
    }
    assert Path(body["result"]["path_incident_report"]).read_text() == "incident_id,status\n1,done\n"


def test_invalid_config_job_submission_does_not_create_job(session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr("db.storage.STORAGE_ROOT", tmp_path / "storage")
    monkeypatch.setattr(auth_routes, "SessionLocal", session_factory)
    monkeypatch.setattr(jobs_routes, "SessionLocal", session_factory)

    client = TestClient(app)
    client.post("/auth/register", params={"username": "bad-config-user", "password": "secret"})
    login = client.post("/auth/login", params={"username": "bad-config-user", "password": "secret"})
    token = login.json()["access_token"]

    submitted = client.post(
        "/jobs",
        json={"config_dir": str(tmp_path / "missing-configs"), "config_name": "config"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert submitted.status_code == 200
    assert submitted.json() is None
    with session_factory() as db:
        assert db.query(Job).count() == 0
