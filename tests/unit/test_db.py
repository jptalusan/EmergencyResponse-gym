"""Unit tests for database."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import crud
from db.models import Base, Job, User
from db.storage import LocalStorage


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_user_and_job_models_define_expected_tables_and_defaults():
    user = User(username="alice", password_hash="hash")
    job = Job(user_id=1, payload={"config_dir": "configs"}, result={"ok": True})

    assert User.__tablename__ == "users"
    assert Job.__tablename__ == "jobs"
    assert user.username == "alice"
    assert job.status is None
    assert job.attempts is None


def test_create_and_get_user(db_session):
    user = crud.create_user(db_session, "alice", "hashed")

    assert user.id is not None
    assert crud.get_user(db_session, "alice").password_hash == "hashed"
    assert crud.get_user(db_session, "missing") is None


def test_create_job_stores_payload_data_and_refreshes_job(db_session, monkeypatch):
    cfg = OmegaConf.create(
        {
            "city": {
                "geography": {"bounds_geojson": "bounds.geojson"},
                "stations": {"csv_path": "stations.csv"},
            },
            "demand": {"incidents_csv": "incidents.csv"},
        }
    )
    calls = []

    monkeypatch.setattr(crud, "load_cfg", lambda config_dir, config_name: cfg)
    monkeypatch.setattr(crud.LocalStorage, "mkdirs", lambda job_id: calls.append(("mkdirs", job_id)))
    monkeypatch.setattr(
        crud.LocalStorage,
        "store_config",
        lambda job_id, payload: calls.append(("store_config", job_id, payload.copy())) or ("stored/configs", "config"),
    )
    monkeypatch.setattr(
        crud.LocalStorage,
        "store_data",
        lambda job_id, received_cfg: calls.append(("store_data", job_id, received_cfg)),
    )

    job = crud.create_job(db_session, user_id=4, payload={"config_dir": "configs", "config_name": "config"})

    assert job is not None
    assert job.id is not None
    assert job.status == "pending"
    assert job.payload == {"config_dir": "stored/configs", "config_name": "config"}
    assert calls[0] == ("mkdirs", job.id)
    assert calls[1] == ("store_config", job.id, {"config_dir": "configs", "config_name": "config"})
    assert calls[2] == ("store_data", job.id, cfg)


def test_create_job_returns_none_when_config_cannot_load(db_session, monkeypatch):
    monkeypatch.setattr(crud, "load_cfg", lambda config_dir, config_name: None)

    assert crud.create_job(db_session, user_id=4, payload={"config_dir": "bad", "config_name": "missing"}) is None
    assert db_session.query(Job).count() == 0


def test_list_get_and_update_jobs(db_session):
    first = Job(user_id=8, payload={"a": 1})
    second = Job(user_id=8, payload={"b": 2})
    other = Job(user_id=9, payload={"c": 3})
    db_session.add_all([first, second, other])
    db_session.commit()

    assert [job.id for job in crud.list_jobs(db_session, 8)] == [first.id, second.id]
    assert crud.get_job(db_session, first.id).payload == {"a": 1}
    assert crud.get_job(db_session, 9999) is None

    crud.update_job(db_session, first.id, status="done", result={"ok": True})

    updated = crud.get_job(db_session, first.id)
    assert updated.status == "done"
    assert updated.result == {"ok": True}


def test_local_storage_mkdirs_creates_job_directories(tmp_path, monkeypatch):
    monkeypatch.setattr("db.storage.STORAGE_ROOT", tmp_path)

    LocalStorage.mkdirs(123)

    assert (tmp_path / "jobs" / "123" / "configs").is_dir()
    assert (tmp_path / "jobs" / "123" / "data").is_dir()
    assert (tmp_path / "jobs" / "123" / "output").is_dir()


def test_local_storage_store_config_copies_config_directory(tmp_path, monkeypatch):
    source_config_dir = tmp_path / "source_configs"
    source_config_dir.mkdir()
    (source_config_dir / "config.yaml").write_text("seed: 1\n")
    storage_root = tmp_path / "storage"
    monkeypatch.setattr("db.storage.STORAGE_ROOT", storage_root)
    LocalStorage.mkdirs("job-a")

    stored_dir, stored_name = LocalStorage.store_config(
        "job-a",
        {"config_dir": str(source_config_dir), "config_name": "config"},
    )

    assert Path(stored_dir) == storage_root / "jobs" / "job-a" / "configs"
    assert stored_name == "config"
    assert (Path(stored_dir) / "config.yaml").read_text() == "seed: 1\n"


def test_local_storage_store_data_and_output_copy_expected_files(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    bounds = input_dir / "bounds.geojson"
    stations = input_dir / "stations.csv"
    incidents = input_dir / "incidents.csv"
    for file_path in (bounds, stations, incidents):
        file_path.write_text(file_path.name)

    output_dir = tmp_path / "source_output"
    output_dir.mkdir()
    incident_report = output_dir / "incident_report.csv"
    apparatus_events = output_dir / "apparatus_events.csv"
    step_trace = output_dir / "step_trace.csv"
    for file_path in (incident_report, apparatus_events, step_trace):
        file_path.write_text(file_path.name)

    storage_root = tmp_path / "storage"
    monkeypatch.setattr("db.storage.STORAGE_ROOT", storage_root)
    LocalStorage.mkdirs(5)
    cfg = OmegaConf.create(
        {
            "city": {
                "geography": {"bounds_geojson": str(bounds)},
                "stations": {"csv_path": str(stations)},
            },
            "demand": {"incidents_csv": str(incidents)},
        }
    )
    result = SimpleNamespace(
        path_incident_report=str(incident_report),
        path_apparatus_events=str(apparatus_events),
        path_step_trace=str(step_trace),
    )

    data_path = LocalStorage.store_data(5, cfg)
    stored_output = LocalStorage.store_output(5, result)

    assert {path.name for path in Path(data_path).iterdir()} == {
        "bounds.geojson",
        "stations.csv",
        "incidents.csv",
    }
    assert {path.name for path in Path(stored_output).iterdir()} == {
        "incident_report.csv",
        "apparatus_events.csv",
        "step_trace.csv",
    }
