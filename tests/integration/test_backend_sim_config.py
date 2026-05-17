"""Integration tests for backend sim route and configuration loading."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import sim as sim_service


def test_sim_route_loads_hydra_config_and_returns_core_output(tmp_path, monkeypatch):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("seed: 77\n")
    received_cfgs = []

    def fake_core_run(cfg):
        received_cfgs.append(cfg)
        return ("incident_report.csv", "apparatus_events.csv", "step_trace.csv")

    monkeypatch.setattr(sim_service, "core_run", fake_core_run)

    client = TestClient(app)
    response = client.post("/sim", json={"config_dir": str(config_dir), "config_name": "config"})

    assert response.status_code == 200
    assert response.json() == {
        "path_incident_report": "incident_report.csv",
        "path_apparatus_events": "apparatus_events.csv",
        "path_step_trace": "step_trace.csv",
    }
    assert len(received_cfgs) == 1
    assert received_cfgs[0].seed == 77
