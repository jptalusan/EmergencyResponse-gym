"""Unit tests for worker."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.schemas.sim import SimInput, SimOutput
from worker import main as worker_main
from worker import processor, runner


class FakeCursor:
    def __init__(self, row=None):
        self.row = row
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, cursor_obj=None):
        self.cursor_obj = cursor_obj or FakeCursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.autocommit = None

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_parse_payload_accepts_dict_and_json_string():
    payload = {"config_dir": "configs", "config_name": "config"}

    assert processor._parse_payload(payload) == SimInput(config_dir="configs", config_name="config")
    assert processor._parse_payload(json.dumps(payload)) == SimInput(config_dir="configs", config_name="config")


def test_parse_payload_rejects_invalid_payloads():
    with pytest.raises(json.JSONDecodeError):
        processor._parse_payload("{")

    with pytest.raises(ValidationError):
        processor._parse_payload({"config_dir": "configs"})


def test_serialize_result_uses_model_dump_when_available():
    output = SimOutput(
        path_incident_report="incident.csv",
        path_apparatus_events="apparatus.csv",
        path_step_trace="steps.csv",
    )

    assert processor._serialize_result(output) == {
        "path_incident_report": "incident.csv",
        "path_apparatus_events": "apparatus.csv",
        "path_step_trace": "steps.csv",
    }
    assert processor._serialize_result({"raw": True}) == {"raw": True}


def test_process_job_runs_sim_stores_output_and_marks_done(monkeypatch, tmp_path):
    result = SimOutput(
        path_incident_report="/tmp/source/incident.csv",
        path_apparatus_events="/tmp/source/apparatus.csv",
        path_step_trace="/tmp/source/steps.csv",
    )
    cursor = FakeCursor()
    conn = FakeConnection(cursor)
    monkeypatch.setattr(processor, "run_sim", lambda sim_input: result)
    monkeypatch.setattr(processor.LocalStorage, "store_output", lambda job_id, output: str(tmp_path / "output"))

    processor.process_job(conn, 10, {"config_dir": "configs", "config_name": "config"})

    sql, params = cursor.statements[0]
    stored_result = json.loads(params[0])
    assert "SET status = 'done'" in sql
    assert params[1] == 10
    assert stored_result == {
        "path_incident_report": str(tmp_path / "output" / "incident.csv"),
        "path_apparatus_events": str(tmp_path / "output" / "apparatus.csv"),
        "path_step_trace": str(tmp_path / "output" / "steps.csv"),
    }


def test_process_job_marks_failed_when_processing_raises(monkeypatch):
    cursor = FakeCursor()
    conn = FakeConnection(cursor)

    def fail(sim_input):
        raise RuntimeError("simulation failed")

    monkeypatch.setattr(processor, "run_sim", fail)

    processor.process_job(conn, 11, {"config_dir": "configs", "config_name": "config"})

    sql, params = cursor.statements[0]
    assert "SET status = 'failed'" in sql
    assert params == ("simulation failed", 11)


def test_fetch_next_job_returns_none_when_no_pending_job():
    cursor = FakeCursor(row=None)
    conn = FakeConnection(cursor)

    assert runner.fetch_next_job(conn) is None
    assert len(cursor.statements) == 1
    assert "FOR UPDATE SKIP LOCKED" in cursor.statements[0][0]


def test_fetch_next_job_marks_row_running_and_returns_job():
    cursor = FakeCursor(row=(22, {"config_dir": "configs", "config_name": "config"}))
    conn = FakeConnection(cursor)

    assert runner.fetch_next_job(conn) == (22, {"config_dir": "configs", "config_name": "config"})
    assert len(cursor.statements) == 2
    assert "SELECT id, payload" in cursor.statements[0][0]
    assert "SET status = 'running'" in cursor.statements[1][0]
    assert cursor.statements[1][1] == (22,)


def test_get_connection_normalizes_postgresql_url_for_psycopg(monkeypatch):
    calls = []
    monkeypatch.setattr(worker_main.settings, "DATABASE_URL", "postgresql://user:pass@localhost:5432/appdb")
    monkeypatch.setattr(worker_main.psycopg2, "connect", lambda dsn: calls.append(dsn) or "connection")

    assert worker_main.get_connection() == "connection"
    assert calls == ["postgresql://user:pass@localhost:5432/appdb"]


def test_wait_for_database_returns_after_success(monkeypatch):
    executions = []

    class Engine:
        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement):
            executions.append(str(statement))

    monkeypatch.setattr(worker_main, "engine", Engine())

    worker_main.wait_for_database(retries=1, delay=0)

    assert executions == ["SELECT 1"]


def test_wait_for_database_raises_after_retries(monkeypatch):
    class Engine:
        def connect(self):
            raise RuntimeError("not ready")

    monkeypatch.setattr(worker_main, "engine", Engine())
    monkeypatch.setattr(worker_main.time, "sleep", lambda delay: None)

    with pytest.raises(RuntimeError, match="Database did not become ready in time"):
        worker_main.wait_for_database(retries=2, delay=0)


def test_run_worker_processes_one_job_then_stops_on_keyboard_interrupt(monkeypatch):
    first_conn = FakeConnection()
    second_conn = FakeConnection()
    connections = [first_conn, second_conn]
    processed = []

    monkeypatch.setattr(worker_main, "wait_for_database", lambda: None)
    monkeypatch.setattr(worker_main.Base.metadata, "create_all", lambda bind: None)
    monkeypatch.setattr(worker_main, "get_connection", lambda: connections.pop(0))
    monkeypatch.setattr(worker_main, "fetch_next_job", lambda conn: (33, {"config_dir": "configs", "config_name": "config"}))

    def process_then_stop(conn, job_id, payload):
        processed.append((conn, job_id, payload))
        raise KeyboardInterrupt

    monkeypatch.setattr(worker_main, "process_job", process_then_stop)

    with pytest.raises(KeyboardInterrupt):
        worker_main.run_worker()

    assert first_conn.commits == 1
    assert first_conn.closed is True
    assert processed == [(second_conn, 33, {"config_dir": "configs", "config_name": "config"})]
    assert second_conn.closed is True


def test_run_worker_rolls_back_and_closes_on_fetch_error(monkeypatch):
    conn = FakeConnection()
    sleeps = []

    monkeypatch.setattr(worker_main, "wait_for_database", lambda: None)
    monkeypatch.setattr(worker_main.Base.metadata, "create_all", lambda bind: None)
    monkeypatch.setattr(worker_main, "get_connection", lambda: conn)

    def fail_fetch(active_conn):
        raise RuntimeError("fetch failed")

    def stop_after_error(delay):
        sleeps.append(delay)
        raise KeyboardInterrupt

    monkeypatch.setattr(worker_main, "fetch_next_job", fail_fetch)
    monkeypatch.setattr(worker_main.time, "sleep", stop_after_error)

    with pytest.raises(KeyboardInterrupt):
        worker_main.run_worker()

    assert conn.rollbacks == 1
    assert conn.closed is True
    assert sleeps == [1]


def test_get_connection_preserves_database_url_without_postgresql_prefix(monkeypatch):
    calls = []
    monkeypatch.setattr(worker_main.settings, "DATABASE_URL", "user:pass@localhost:5432/appdb")
    monkeypatch.setattr(worker_main.psycopg2, "connect", lambda dsn: calls.append(dsn) or "connection")

    assert worker_main.get_connection() == "connection"
    assert calls == ["postgresql://user:pass@localhost:5432/appdb"]


def test_wait_for_database_retries_then_succeeds(monkeypatch):
    attempts = []
    sleeps = []

    class Engine:
        def connect(self):
            attempts.append("connect")
            if len(attempts) < 3:
                raise RuntimeError("not ready yet")
            return self

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement):
            attempts.append(str(statement))

    monkeypatch.setattr(worker_main, "engine", Engine())
    monkeypatch.setattr(worker_main.time, "sleep", lambda delay: sleeps.append(delay))

    worker_main.wait_for_database(retries=3, delay=0.25)

    assert attempts == ["connect", "connect", "connect", "SELECT 1"]
    assert sleeps == [0.25, 0.25]


def test_run_worker_initializes_tables_and_sleeps_when_no_job(monkeypatch):
    conn = FakeConnection()
    create_all_calls = []
    sleeps = []

    monkeypatch.setattr(worker_main, "wait_for_database", lambda: None)
    monkeypatch.setattr(worker_main.Base.metadata, "create_all", lambda bind: create_all_calls.append(bind))
    monkeypatch.setattr(worker_main, "get_connection", lambda: conn)
    monkeypatch.setattr(worker_main, "fetch_next_job", lambda active_conn: None)

    def stop_after_idle_sleep(delay):
        sleeps.append(delay)
        raise KeyboardInterrupt

    monkeypatch.setattr(worker_main.time, "sleep", stop_after_idle_sleep)

    with pytest.raises(KeyboardInterrupt):
        worker_main.run_worker()

    assert create_all_calls == [worker_main.engine]
    assert conn.autocommit is False
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert conn.closed is True
    assert sleeps == [1]


def test_run_worker_commits_processed_job_successfully_then_stops_on_next_fetch(monkeypatch):
    fetch_conn = FakeConnection()
    process_conn = FakeConnection()
    final_conn = FakeConnection()
    connections = [fetch_conn, process_conn, final_conn]
    fetch_calls = []
    processed = []

    monkeypatch.setattr(worker_main, "wait_for_database", lambda: None)
    monkeypatch.setattr(worker_main.Base.metadata, "create_all", lambda bind: None)
    monkeypatch.setattr(worker_main, "get_connection", lambda: connections.pop(0))

    def fetch_once_then_stop(conn):
        fetch_calls.append(conn)
        if len(fetch_calls) == 1:
            return (44, {"config_dir": "configs", "config_name": "config"})
        raise KeyboardInterrupt

    monkeypatch.setattr(worker_main, "fetch_next_job", fetch_once_then_stop)
    monkeypatch.setattr(worker_main, "process_job", lambda conn, job_id, payload: processed.append((conn, job_id, payload)))

    with pytest.raises(KeyboardInterrupt):
        worker_main.run_worker()

    assert fetch_conn.commits == 1
    assert fetch_conn.closed is True
    assert process_conn.commits == 1
    assert process_conn.closed is True
    assert final_conn.closed is True
    assert processed == [(process_conn, 44, {"config_dir": "configs", "config_name": "config"})]


def test_run_worker_ignores_close_error_in_finally(monkeypatch):
    class CloseFailingConnection(FakeConnection):
        def close(self):
            self.closed = True
            raise RuntimeError("close failed")

    conn = CloseFailingConnection()

    monkeypatch.setattr(worker_main, "wait_for_database", lambda: None)
    monkeypatch.setattr(worker_main.Base.metadata, "create_all", lambda bind: None)
    monkeypatch.setattr(worker_main, "get_connection", lambda: conn)
    monkeypatch.setattr(worker_main, "fetch_next_job", lambda active_conn: (_ for _ in ()).throw(KeyboardInterrupt))

    with pytest.raises(KeyboardInterrupt):
        worker_main.run_worker()

    assert conn.closed is True
