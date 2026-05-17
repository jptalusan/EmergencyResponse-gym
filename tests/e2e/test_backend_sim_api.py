"""End-to-end tests for the backend simulation API."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import sim as sim_service


def test_sim_endpoint_loads_config_runs_service_and_returns_output_paths(tmp_path, monkeypatch):
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
                "seed: 123",
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
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    def fake_core_run(cfg):
        assert cfg.seed == 123
        assert Path(cfg.city.stations.csv_path).read_text() == "StationID,Stations,lat,lon\n"
        output_paths = []
        for filename in ("incident_report.csv", "apparatus_events.csv", "step_trace.csv"):
            path = output_dir / filename
            path.write_text(filename)
            output_paths.append(str(path))
        return tuple(output_paths)

    monkeypatch.setattr(sim_service, "core_run", fake_core_run)

    response = TestClient(app).post("/sim", json={"config_dir": str(config_dir), "config_name": "config"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "path_incident_report": str(output_dir / "incident_report.csv"),
        "path_apparatus_events": str(output_dir / "apparatus_events.csv"),
        "path_step_trace": str(output_dir / "step_trace.csv"),
    }
    assert Path(body["path_step_trace"]).read_text() == "step_trace.csv"
