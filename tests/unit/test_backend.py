"""Unit tests for backend modules."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from backend.main import health
from backend.config import _replace_local_host
from backend.routes import auth as auth_routes
from backend.routes import jobs as jobs_routes
from backend.routes import sim as sim_routes
from backend.schemas.sim import SimInput, SimJob, SimOutput
from backend.services import auth as auth_service
from backend.services import sim as sim_service


class DummySession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_sim_schemas_validate_and_dump_expected_fields():
    sim_input = SimInput(config_dir="configs", config_name="config")
    sim_output = SimOutput(
        path_incident_report="output/incidents.csv",
        path_apparatus_events="output/apparatus.csv",
        path_step_trace="output/steps.csv",
    )
    job = SimJob(id=1, user_id=2, status="pending", payload=sim_input, result=sim_output)

    assert sim_input.model_dump() == {"config_dir": "configs", "config_name": "config"}
    assert job.payload.config_name == "config"
    assert job.result.path_step_trace == "output/steps.csv"

    with pytest.raises(ValidationError):
        SimInput(config_dir="configs")


def test_replace_local_host_rewrites_loopback_hosts_and_preserves_auth_port_path():
    assert (
        _replace_local_host("postgresql://user:pass@localhost:5432/appdb?sslmode=disable", "postgres")
        == "postgresql://user:pass@postgres:5432/appdb?sslmode=disable"
    )
    assert _replace_local_host("postgresql://app@127.0.0.1/db", "postgres") == "postgresql://app@postgres/db"
    assert _replace_local_host("postgresql://app@db.internal/db", "postgres") == "postgresql://app@db.internal/db"


def test_health_returns_ok():
    assert asyncio.run(health()) == {"status": "ok"}


def test_normalize_password_accepts_bytes_truncates_and_rejects_non_string():
    assert auth_service._normalize_password(b"abc\xff") == b"abc"
    assert auth_service._normalize_password("x" * 100) == b"x" * 72

    with pytest.raises(TypeError, match="Password must be a string"):
        auth_service._normalize_password(123)


def test_hash_and_verify_password_round_trip():
    password_hash = auth_service.hash_password("secret")

    assert password_hash != "secret"
    assert auth_service.verify_password("secret", password_hash) is True
    assert auth_service.verify_password("wrong", password_hash) is False


def test_extract_token_handles_bearer_raw_and_invalid_schemes():
    assert auth_service._extract_token(None) is None
    assert auth_service._extract_token("   ") is None
    assert auth_service._extract_token("Bearer abc.def") == "abc.def"
    assert auth_service._extract_token("bearer token") == "token"
    assert auth_service._extract_token("Token abc") is None
    assert auth_service._extract_token("raw-token") == "raw-token"


def test_create_token_and_decode_user_id_round_trip():
    token = auth_service.create_token(42)

    assert auth_service._decode_user_id(token) == 42


def test_get_current_user_prefers_security_credentials():
    token = auth_service.create_token(7)
    request = SimpleNamespace(headers={}, cookies={})
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    assert auth_service.get_current_user(request, credentials) == 7


def test_get_current_user_accepts_header_or_cookie_and_rejects_missing():
    header_token = auth_service.create_token(8)
    cookie_token = auth_service.create_token(9)

    assert auth_service.get_current_user(
        SimpleNamespace(headers={"Authorization": f"Bearer {header_token}"}, cookies={}),
        None,
    ) == 8
    assert auth_service.get_current_user(
        SimpleNamespace(headers={}, cookies={"auth_token": cookie_token}),
        None,
    ) == 9

    with pytest.raises(HTTPException) as exc:
        auth_service.get_current_user(SimpleNamespace(headers={}, cookies={}), None)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Missing authorization header or auth cookie"


def test_get_current_user_rejects_invalid_token():
    with pytest.raises(HTTPException) as exc:
        auth_service.get_current_user(
            SimpleNamespace(headers={"Authorization": "Bearer not-a-token"}, cookies={}),
            None,
        )

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid token"


def test_run_sim_loads_config_and_wraps_core_result(monkeypatch):
    cfg = object()
    monkeypatch.setattr(sim_service, "load_cfg", lambda config_dir, config_name: cfg)
    monkeypatch.setattr(
        sim_service,
        "core_run",
        lambda received_cfg: ("incidents.csv", "apparatus.csv", "steps.csv") if received_cfg is cfg else None,
    )

    result = sim_service.run_sim(SimInput(config_dir="configs", config_name="config"))

    assert result == SimOutput(
        path_incident_report="incidents.csv",
        path_apparatus_events="apparatus.csv",
        path_step_trace="steps.csv",
    )


def test_sim_route_returns_service_output(monkeypatch):
    expected = SimOutput(
        path_incident_report="incidents.csv",
        path_apparatus_events="apparatus.csv",
        path_step_trace="steps.csv",
    )
    monkeypatch.setattr(sim_routes, "run_sim", lambda payload: expected)

    assert asyncio.run(sim_routes.sim(SimInput(config_dir="configs", config_name="config"))) == expected


def test_sim_route_converts_service_error_to_http_500(monkeypatch):
    def fail(payload):
        raise RuntimeError("boom")

    monkeypatch.setattr(sim_routes, "run_sim", fail)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(sim_routes.sim(SimInput(config_dir="configs", config_name="config")))

    assert exc.value.status_code == 500
    assert exc.value.detail == "boom"


def test_serialize_job_returns_plain_dict():
    job = SimpleNamespace(id=1, user_id=2, status="done", payload={"x": 1}, result={"ok": True})

    assert jobs_routes._serialize_job(job) == {
        "id": 1,
        "user_id": 2,
        "status": "done",
        "payload": {"x": 1},
        "result": {"ok": True},
    }


def test_submit_job_creates_and_closes_session(monkeypatch):
    session = DummySession()
    job = SimpleNamespace(id=3, user_id=4, status="pending", payload={"a": 1}, result=None)
    monkeypatch.setattr(jobs_routes, "SessionLocal", lambda: session)
    monkeypatch.setattr(jobs_routes.crud, "create_job", lambda db, user_id, payload: job)

    result = jobs_routes._submit_job(SimInput(config_dir="configs", config_name="config"), user_id=4)

    assert result["id"] == 3
    assert result["payload"] == {"a": 1}
    assert session.closed is True


def test_submit_job_returns_none_when_crud_returns_none(monkeypatch):
    session = DummySession()
    monkeypatch.setattr(jobs_routes, "SessionLocal", lambda: session)
    monkeypatch.setattr(jobs_routes.crud, "create_job", lambda db, user_id, payload: None)

    assert jobs_routes._submit_job(SimInput(config_dir="bad", config_name="missing"), user_id=4) is None
    assert session.closed is True


def test_list_user_jobs_serializes_jobs_and_closes_session(monkeypatch):
    session = DummySession()
    jobs = [
        SimpleNamespace(id=1, user_id=5, status="pending", payload={}, result=None),
        SimpleNamespace(id=2, user_id=5, status="done", payload={}, result={"ok": True}),
    ]
    monkeypatch.setattr(jobs_routes, "SessionLocal", lambda: session)
    monkeypatch.setattr(jobs_routes.crud, "list_jobs", lambda db, user_id: jobs)

    result = jobs_routes._list_user_jobs(user_id=5)

    assert [job["id"] for job in result] == [1, 2]
    assert session.closed is True


def test_get_one_returns_job_for_owner_and_closes_session(monkeypatch):
    session = DummySession()
    job = SimpleNamespace(id=9, user_id=6, status="done", payload={}, result={})
    monkeypatch.setattr(jobs_routes, "SessionLocal", lambda: session)
    monkeypatch.setattr(jobs_routes.crud, "get_job", lambda db, job_id: job)

    assert jobs_routes.get_one(job_id=9, user_id=6)["id"] == 9
    assert session.closed is True


def test_get_one_currently_returns_none_for_missing_or_other_users(monkeypatch):
    session = DummySession()
    monkeypatch.setattr(jobs_routes, "SessionLocal", lambda: session)
    monkeypatch.setattr(jobs_routes.crud, "get_job", lambda db, job_id: None)

    assert jobs_routes.get_one(job_id=123, user_id=6) is None
    assert session.closed is True


def test_register_creates_user_or_returns_existing_error(monkeypatch):
    sessions = [DummySession(), DummySession()]
    monkeypatch.setattr(auth_routes, "SessionLocal", lambda: sessions.pop(0))
    monkeypatch.setattr(auth_routes, "hash_password", lambda password: f"hashed:{password}")
    monkeypatch.setattr(auth_routes.crud, "get_user", lambda db, username: None)
    monkeypatch.setattr(auth_routes.crud, "create_user", lambda db, username, password_hash: SimpleNamespace(id=11))

    assert auth_routes.register("new", "pw") == {"id": 11}

    monkeypatch.setattr(auth_routes.crud, "get_user", lambda db, username: SimpleNamespace(id=12))
    assert auth_routes.register("new", "pw") == {"error": "User already exists."}


def test_login_sets_cookie_on_success_and_returns_error_on_failure(monkeypatch):
    success_session = DummySession()
    failure_session = DummySession()
    sessions = [success_session, failure_session]
    user = SimpleNamespace(id=21, password_hash="hash")
    monkeypatch.setattr(auth_routes, "SessionLocal", lambda: sessions.pop(0))
    monkeypatch.setattr(auth_routes.crud, "get_user", lambda db, username: user)
    monkeypatch.setattr(auth_routes, "verify_password", lambda password, password_hash: True)
    monkeypatch.setattr(auth_routes, "create_token", lambda user_id: f"token-{user_id}")

    response = Response()
    assert auth_routes.login(response, "name", "pw") == {
        "token": "token-21",
        "access_token": "token-21",
        "token_type": "bearer",
    }
    assert "auth_token=token-21" in response.headers["set-cookie"]
    assert success_session.closed is True

    monkeypatch.setattr(auth_routes.crud, "get_user", lambda db, username: None)
    assert auth_routes.login(Response(), "name", "pw") == {"error": "Invalid username/password combination."}
    assert failure_session.closed is True


def test_running_in_container_detects_explicit_env_var(monkeypatch):
    from backend import config as backend_config

    monkeypatch.setattr(backend_config.os, "getenv", lambda key, default="": "yes" if key == "RUNNING_IN_DOCKER" else default)

    assert backend_config._running_in_container() is True


def test_running_in_container_detects_cgroup_token(monkeypatch):
    import io

    from backend import config as backend_config

    monkeypatch.setattr(backend_config.os, "getenv", lambda key, default="": "")
    monkeypatch.setattr(backend_config.Path, "exists", lambda self: False)
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO("0::/docker/container-id"))

    assert backend_config._running_in_container() is True


def test_running_in_container_returns_false_without_indicators(monkeypatch):
    from backend import config as backend_config

    def raise_missing_file(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(backend_config.os, "getenv", lambda key, default="": "")
    monkeypatch.setattr(backend_config.Path, "exists", lambda self: False)
    monkeypatch.setattr("builtins.open", raise_missing_file)

    assert backend_config._running_in_container() is False


def test_replace_local_host_preserves_query_and_fragment_without_auth():
    from backend import config as backend_config

    assert (
        backend_config._replace_local_host("postgresql://localhost:5432/appdb?sslmode=require#primary", "postgres")
        == "postgresql://postgres:5432/appdb?sslmode=require#primary"
    )


def test_main_app_registers_expected_routes_and_cors_middleware():
    from fastapi.middleware.cors import CORSMiddleware

    from backend import main as backend_main

    route_paths = {route.path for route in backend_main.app.routes}
    assert {
        "/health",
        "/auth/register",
        "/auth/login",
        "/jobs",
        "/jobs/{job_id}",
        "/sim",
    }.issubset(route_paths)
    assert any(middleware.cls is CORSMiddleware for middleware in backend_main.app.user_middleware)


def test_on_startup_creates_database_tables(monkeypatch):
    from backend import main as backend_main

    calls = []
    monkeypatch.setattr(backend_main.Base.metadata, "create_all", lambda bind: calls.append(bind))

    backend_main.on_startup()

    assert calls == [backend_main.engine]


def test_on_startup_logs_and_reraises_create_all_failure(monkeypatch):
    from backend import main as backend_main

    errors = []

    def fail_create_all(bind):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(backend_main.Base.metadata, "create_all", fail_create_all)
    monkeypatch.setattr(backend_main.logger, "error", lambda message, exc_info=False: errors.append((message, exc_info)))

    with pytest.raises(RuntimeError, match="database unavailable"):
        backend_main.on_startup()

    assert errors == [("Failed to create database tables: database unavailable", True)]


def test_submit_endpoint_delegates_to_submit_job(monkeypatch):
    data = SimInput(config_dir="configs", config_name="config")
    calls = []
    monkeypatch.setattr(jobs_routes, "_submit_job", lambda payload, user_id: calls.append((payload, user_id)) or {"id": 55})

    assert jobs_routes.submit(data, user_id=12) == {"id": 55}
    assert calls == [(data, 12)]


def test_list_all_endpoint_delegates_to_list_user_jobs(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs_routes, "_list_user_jobs", lambda user_id: calls.append(user_id) or [{"id": 1}])

    assert jobs_routes.list_all(user_id=33) == [{"id": 1}]
    assert calls == [33]


def test_submit_job_closes_session_when_crud_raises(monkeypatch):
    session = DummySession()

    def fail_create_job(db, user_id, payload):
        raise RuntimeError("bad config")

    monkeypatch.setattr(jobs_routes, "SessionLocal", lambda: session)
    monkeypatch.setattr(jobs_routes.crud, "create_job", fail_create_job)

    assert jobs_routes._submit_job(SimInput(config_dir="bad", config_name="missing"), user_id=4) is None
    assert session.closed is True


def test_list_user_jobs_closes_session_when_crud_raises(monkeypatch):
    session = DummySession()

    def fail_list_jobs(db, user_id):
        raise RuntimeError("database down")

    monkeypatch.setattr(jobs_routes, "SessionLocal", lambda: session)
    monkeypatch.setattr(jobs_routes.crud, "list_jobs", fail_list_jobs)

    assert jobs_routes._list_user_jobs(user_id=5) is None
    assert session.closed is True


def test_get_one_returns_none_for_job_owned_by_different_user_and_closes_session(monkeypatch):
    session = DummySession()
    job = SimpleNamespace(id=9, user_id=99, status="done", payload={}, result={})
    monkeypatch.setattr(jobs_routes, "SessionLocal", lambda: session)
    monkeypatch.setattr(jobs_routes.crud, "get_job", lambda db, job_id: job)

    assert jobs_routes.get_one(job_id=9, user_id=6) is None
    assert session.closed is True


def test_get_one_closes_session_when_crud_raises(monkeypatch):
    session = DummySession()

    def fail_get_job(db, job_id):
        raise RuntimeError("database down")

    monkeypatch.setattr(jobs_routes, "SessionLocal", lambda: session)
    monkeypatch.setattr(jobs_routes.crud, "get_job", fail_get_job)

    assert jobs_routes.get_one(job_id=9, user_id=6) is None
    assert session.closed is True


def test_decode_user_id_rejects_token_without_subject():
    from jose import jwt

    from backend.config import settings

    token = jwt.encode({"not_sub": "42"}, settings.SECRET_KEY, algorithm="HS256")

    with pytest.raises(ValueError, match="Token missing subject"):
        auth_service._decode_user_id(token)


def test_decode_user_id_rejects_non_integer_subject():
    from jose import jwt

    from backend.config import settings

    token = jwt.encode({"sub": "not-an-int"}, settings.SECRET_KEY, algorithm="HS256")

    with pytest.raises(ValueError):
        auth_service._decode_user_id(token)


def test_get_current_user_accepts_raw_authorization_header():
    token = auth_service.create_token(123)
    request = SimpleNamespace(headers={"Authorization": token}, cookies={})

    assert auth_service.get_current_user(request, None) == 123


def test_get_current_user_prefers_credentials_over_invalid_header_and_cookie():
    valid_token = auth_service.create_token(222)
    cookie_token = auth_service.create_token(333)
    request = SimpleNamespace(
        headers={"Authorization": "Bearer invalid-header-token"},
        cookies={"auth_token": cookie_token},
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=valid_token)

    assert auth_service.get_current_user(request, credentials) == 222


def test_get_current_user_rejects_invalid_cookie_token():
    request = SimpleNamespace(headers={}, cookies={"auth_token": "not-a-token"})

    with pytest.raises(HTTPException) as exc:
        auth_service.get_current_user(request, None)

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid token"


def test_verify_password_accepts_bytes_password():
    password_hash = auth_service.hash_password(b"secret")

    assert auth_service.verify_password(b"secret", password_hash) is True
    assert auth_service.verify_password(b"wrong", password_hash) is False
