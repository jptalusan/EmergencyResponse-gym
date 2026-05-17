"""Hydra entry point for running emergency response simulations."""

from __future__ import annotations

import logging
from pathlib import Path

import hydra
from omegaconf import DictConfig

logger = logging.getLogger(__name__)

def get_project_root() -> str:
    try:
        return hydra.utils.get_original_cwd()
    except ValueError:
        return str(Path.cwd())

def build_scenario(cfg: DictConfig, orig_cwd: str):
    """Build a Scenario from Hydra config."""
    from emergency_response.geography.network import NetworkGeography
    from emergency_response.models.scenario import Scenario
    from emergency_response.utils.loaders import load_bounds, load_stations

    geo_cfg = cfg.city.geography

    geography = NetworkGeography(
        north=geo_cfg.boundary.north,
        south=geo_cfg.boundary.south,
        east=geo_cfg.boundary.east,
        west=geo_cfg.boundary.west,
        h3_resolution=geo_cfg.h3_resolution,
        cache_dir=str(Path(orig_cwd) / geo_cfg.cache_dir),
        network_type=geo_cfg.network_type,
    )

    # Load bounds
    bounds_path = str(Path(orig_cwd) / geo_cfg.bounds_geojson)
    bounds_polygon = load_bounds(bounds_path)

    # Load stations
    stations_csv = str(Path(orig_cwd) / cfg.city.stations.csv_path)
    cache_dir = str(Path(orig_cwd) / geo_cfg.cache_dir)
    stations, apparatus = load_stations(stations_csv, geography, cache_dir=cache_dir)

    # Load incidents path (used later by demand model)
    incidents_csv = str(Path(orig_cwd) / cfg.demand.incidents_csv)

    return Scenario(
        geography=geography,
        stations=stations,
        apparatus=apparatus,
        incidents_csv=incidents_csv,
        bounds_geojson=bounds_path,
        random_seed=cfg.seed,
    ), bounds_polygon


def build_incident_model(cfg: DictConfig, scenario, geography, bounds_polygon):
    """Build an IncidentModel from config."""
    from emergency_response.demand.empirical import EmpiricalIncidentModel
    from emergency_response.utils.loaders import load_incidents

    cache_dir = Path(scenario.incidents_csv).parent.parent / "cache"

    if cfg.demand.type == "empirical":
        incidents = load_incidents(
            scenario.incidents_csv,
            geography=geography,
            bounds_polygon=bounds_polygon,
            cache_dir=str(cache_dir),
        )
        return EmpiricalIncidentModel(incidents)
    raise ValueError(f"Unknown demand type: {cfg.demand.type}")


def build_solver(cfg: DictConfig):
    """Build a DispatchSolver from config."""
    solver_type = cfg.solver.get("type", "nearest")

    if solver_type == "nearest":
        from emergency_response.solver.nearest import NearestDispatchSolver
        return NearestDispatchSolver()
    raise ValueError(f"Unknown solver type: {solver_type}")


def build_policy(cfg: DictConfig, geography, solver):
    """Build a DispatchPolicy from config."""
    policy_type = cfg.policy.type

    if policy_type == "nearest":
        from emergency_response.policy.nearest import NearestDispatchPolicy
        return NearestDispatchPolicy(geography, solver)
    raise ValueError(f"Unknown policy type: {policy_type}")


@hydra.main(version_base=None, config_path="../../configs", config_name="config")
def main(cfg: DictConfig) -> None:
    emergency_response_sim(cfg)
    return


def emergency_response_sim(cfg: DictConfig):
    """Run an emergency response simulation."""
    from emergency_response.env.emergency_env import EmergencyEnv
    from emergency_response.metrics import (
        build_records,
        export_apparatus_events,
        export_csv,
        export_step_records,
        print_summary,
    )

    orig_cwd = get_project_root()

    logger.info("Building scenario...")
    scenario, bounds_polygon = build_scenario(cfg, orig_cwd)
    logger.info("Scenario: %d stations, %d apparatus", len(scenario.stations), len(scenario.apparatus))

    incident_model = build_incident_model(cfg, scenario, scenario.geography, bounds_polygon)
    solver = build_solver(cfg)
    policy = build_policy(cfg, scenario.geography, solver)

    env = EmergencyEnv(scenario, incident_model, policy)
    state = env.reset()

    max_incidents = cfg.simulation.max_incidents
    logger.info("Running simulation for up to %d incidents with policy=%s", max_incidents, cfg.policy.type)

    all_incidents: list = []
    for i in range(max_incidents):
        action = policy.dispatch(state)
        state, reward, done, info = env.step(action)

        if state.new_incident is not None:
            pass  # will be processed next step

        # Track incident that was just processed
        inc_id = info.get("incident_id")
        if inc_id is not None:
            # Find it in active or resolved
            inc = state.active_incidents.get(inc_id)
            if inc is not None:
                all_incidents.append(inc)

        if (i + 1) % 100 == 0:
            m = env.metrics
            logger.info(
                "Incident %d/%d | Mean response time: %.0fs | Dispatched: %d | Resolved: %d",
                i + 1,
                max_incidents,
                m.mean_response_time,
                m.dispatched_incidents,
                m.resolved_incidents,
            )

        if done:
            break

    # Drain
    if cfg.simulation.get("drain", True):
        logger.info("Draining: waiting for all apparatus to return...")
        env.drain(max_drain_time=cfg.simulation.get("max_drain_time", 7200.0))

    # Collect all incidents (active + resolved)
    all_incidents = list(state.active_incidents.values()) + env.resolved_incidents
    records = build_records(all_incidents)
    print_summary(records)

    output_dir = Path(orig_cwd) / "output"
    export_csv(records, output_dir / "incident_report.csv")
    export_apparatus_events(env.apparatus_events, output_dir / "apparatus_events.csv")
    export_step_records(env.step_records, output_dir / "step_trace.csv")
    return (
        str(Path(output_dir / "incident_report.csv")),
        str(Path(output_dir / "apparatus_events.csv")),
        str(Path(output_dir / "step_trace.csv"))
    )


if __name__ == "__main__":
    main()
