"""Integration tests for worker processing with backend schemas and storage paths."""

from __future__ import annotations

import json

from backend.services import sim as sim_service
from worker import processor


class RecordingCursor:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))


class RecordingConnection:
    def __init__(self):
        self.cursor_obj = RecordingCursor()

    def cursor(self):
        return self.cursor_obj


def test_worker_process_job_runs_service_stores_files_and_updates_result(tmp_path, monkeypatch):
    source_output = tmp_path / "source_output"
    source_output.mkdir()
    incident_report = source_output / "incident_report.csv"
    apparatus_events = source_output / "apparatus_events.csv"
    step_trace = source_output / "step_trace.csv"
    for path in (incident_report, apparatus_events, step_trace):
        path.write_text(path.name)

    stored_output = tmp_path / "stored_output"
    stored_output.mkdir()

    def fake_run_sim(sim_input):
        assert sim_input.config_dir == "configs"
        assert sim_input.config_name == "config"
        return sim_service.SimOutput(
            path_incident_report=str(incident_report),
            path_apparatus_events=str(apparatus_events),
            path_step_trace=str(step_trace),
        )

    monkeypatch.setattr(processor, "run_sim", fake_run_sim)
    monkeypatch.setattr(processor.LocalStorage, "store_output", lambda job_id, result: str(stored_output))
    conn = RecordingConnection()

    processor.process_job(conn, 5, json.dumps({"config_dir": "configs", "config_name": "config"}))

    assert len(conn.cursor_obj.statements) == 1
    sql, params = conn.cursor_obj.statements[0]
    assert "SET status = 'done'" in sql
    assert params[1] == 5

    result = json.loads(params[0])
    assert result == {
        "path_incident_report": str(stored_output / "incident_report.csv"),
        "path_apparatus_events": str(stored_output / "apparatus_events.csv"),
        "path_step_trace": str(stored_output / "step_trace.csv"),
    }
