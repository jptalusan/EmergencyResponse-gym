"""Integration tests for backend auth and jobs routes with database CRUD."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from omegaconf import OmegaConf
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.routes import auth as auth_routes
from backend.routes import jobs as jobs_routes
from db import crud
from db.models import Base, Job, User


@pytest.fixture
def sqlite_session_factory():
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
def storage_cfg(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    bounds = data_dir / "bounds.geojson"
    stations = data_dir / "stations.csv"
    incidents = data_dir / "incidents.csv"
    bounds.write_text('{"type":"FeatureCollection","features":[]}\n')
    stations.write_text("StationID,Stations,lat,lon\n")
    incidents.write_text("incident_id,lat,lon,datetime\n")

    return OmegaConf.create(
        {
            "city": {
                "geography": {"bounds_geojson": str(bounds)},
                "stations": {"csv_path": str(stations)},
            },
            "demand": {"incidents_csv": str(incidents)},
        }
    )


def test_auth_and_jobs_routes_persist_jobs_through_crud(sqlite_session_factory, storage_cfg, monkeypatch):
    monkeypatch.setattr(auth_routes, "SessionLocal", sqlite_session_factory)
    monkeypatch.setattr(jobs_routes, "SessionLocal", sqlite_session_factory)
    monkeypatch.setattr(crud, "load_cfg", lambda config_dir, config_name: storage_cfg)
    monkeypatch.setattr(crud.LocalStorage, "mkdirs", lambda job_id: None)
    monkeypatch.setattr(
        crud.LocalStorage,
        "store_config",
        lambda job_id, payload: (f"/stored/jobs/{job_id}/configs", payload["config_name"]),
    )
    monkeypatch.setattr(crud.LocalStorage, "store_data", lambda job_id, cfg: f"/stored/jobs/{job_id}/data")

    client = TestClient(app)

    register = client.post("/auth/register", params={"username": "alice", "password": "secret"})
    assert register.status_code == 200
    assert register.json()["id"] == 1

    duplicate = client.post("/auth/register", params={"username": "alice", "password": "secret"})
    assert duplicate.status_code == 200
    assert duplicate.json() == {"error": "User already exists."}

    login = client.post("/auth/login", params={"username": "alice", "password": "secret"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert login.cookies.get("auth_token") == token

    unauthenticated = TestClient(app).post("/jobs", json={"config_dir": "configs", "config_name": "config"})
    assert unauthenticated.status_code == 401

    submitted = client.post(
        "/jobs",
        json={"config_dir": "configs", "config_name": "config"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert submitted.status_code == 200
    assert submitted.json() == {
        "id": 1,
        "user_id": 1,
        "status": "pending",
        "payload": {"config_dir": "/stored/jobs/1/configs", "config_name": "config"},
        "result": None,
    }

    listed = client.get("/jobs", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    assert [job["id"] for job in listed.json()] == [1]

    fetched = client.get("/jobs/1", headers={"Authorization": f"Bearer {token}"})
    assert fetched.status_code == 200
    assert fetched.json()["payload"]["config_dir"] == "/stored/jobs/1/configs"

    with sqlite_session_factory() as db:
        assert db.query(User).filter_by(username="alice").one().id == 1
        stored_job = db.query(Job).filter_by(id=1).one()
        assert stored_job.user_id == 1
        assert stored_job.payload == {"config_dir": "/stored/jobs/1/configs", "config_name": "config"}
