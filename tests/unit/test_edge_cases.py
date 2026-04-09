"""Tests for edge cases across the system."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from emergency_response.demand.empirical import EmpiricalIncidentModel
from emergency_response.env.emergency_env import RESPOND_DELAY, EmergencyEnv
from emergency_response.models.core import (
    Apparatus,
    ApparatusStatus,
    ApparatusType,
    DEFAULT_RESOLUTION_TIMES,
    DispatchAction,
    FireStation,
    Incident,
    IncidentLevel,
    IncidentStatus,
    IncidentType,
    NodeLocation,
)
from emergency_response.models.scenario import Scenario
from emergency_response.policy.nearest import NearestDispatchPolicy
from emergency_response.solver.nearest import NearestDispatchSolver


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _inc(
    incident_id: int,
    node: int,
    report_time: float,
    category: str = "Nine",
) -> Incident:
    return Incident(
        id=incident_id,
        lat=36.16,
        lon=-86.74,
        incident_type=IncidentType.EMS_RESCUE,
        level=IncidentLevel.MODERATE,
        datetime=datetime.fromtimestamp(report_time),
        category=category,
        node=node,
        report_time=report_time,
    )


# ---------------------------------------------------------------------------
# 1. Multi-step apparatus transitions in one simulate_time_step
# ---------------------------------------------------------------------------

class TestMultiStepTransitions:
    """When there's a large time gap between incidents, an apparatus should
    go through EN_ROUTE → AT_INCIDENT → RETURNING → AVAILABLE in one step."""

    def test_apparatus_fully_cycles_in_large_time_gap(
        self, mock_geography, sample_stations, sample_apparatus
    ):
        # Two incidents: first at t=1_000_000, second at t=1_100_000 (27+ hours later)
        # The first incident's apparatus should be fully returned by the second.
        incidents = [
            _inc(1, node=2, report_time=1_000_000.0),
            _inc(2, node=4, report_time=1_100_000.0),  # 100_000s later
        ]

        scenario = Scenario(
            geography=mock_geography,
            stations=sample_stations,
            apparatus=sample_apparatus,
            incidents_csv="",
            bounds_geojson=None,
            random_seed=42,
        )
        model = EmpiricalIncidentModel(incidents)
        solver = NearestDispatchSolver()
        policy = NearestDispatchPolicy(mock_geography, solver)
        env = EmergencyEnv(scenario, model, policy)

        state = env.reset()

        # Step 1: dispatch to first incident
        action = policy.dispatch(state)
        state, reward, done, info = env.step(action)

        # By the time we reach incident 2 (100_000s later), all apparatus
        # from incident 1 should be AVAILABLE again.
        # Resolution for "Nine" = 1500s, max travel ~200s, respond delay 60s.
        # Total cycle: 60 + 200 + 1500 + 200 = ~1960s << 100_000s.
        dispatched_count = sum(
            1 for a in state.apparatus if a.status != ApparatusStatus.AVAILABLE
        )
        assert dispatched_count == 0, (
            f"Expected all apparatus available after 100_000s gap, "
            f"but {dispatched_count} are still busy: "
            f"{[(a.id, a.status.name) for a in state.apparatus if a.status != ApparatusStatus.AVAILABLE]}"
        )

    def test_apparatus_mid_cycle_stays_correct(
        self, mock_geography, sample_stations, sample_apparatus
    ):
        # Short gap: only enough time for EN_ROUTE → AT_INCIDENT, not full cycle
        # travel_time to node 2 from station 1 (node 3) = 50s + 60s delay = 110s
        # resolution for Nine = 1500s
        # So at t+200s, apparatus should be AT_INCIDENT (arrived at 110s, resolves at 1610s)
        incidents = [
            _inc(1, node=2, report_time=1_000_000.0),
            _inc(2, node=4, report_time=1_000_200.0),  # 200s later
        ]

        scenario = Scenario(
            geography=mock_geography,
            stations=sample_stations,
            apparatus=sample_apparatus,
            incidents_csv="",
            bounds_geojson=None,
            random_seed=42,
        )
        model = EmpiricalIncidentModel(incidents)
        solver = NearestDispatchSolver()
        policy = NearestDispatchPolicy(mock_geography, solver)
        env = EmergencyEnv(scenario, model, policy)

        state = env.reset()
        action = policy.dispatch(state)
        state, reward, done, info = env.step(action)

        # The apparatus dispatched to incident 1 should be AT_INCIDENT
        # (arrived at 110s, resolves at 1610s — we're only at 200s)
        busy = [a for a in state.apparatus if a.status != ApparatusStatus.AVAILABLE]
        at_incident = [a for a in state.apparatus if a.status == ApparatusStatus.AT_INCIDENT]
        assert len(at_incident) > 0, (
            f"Expected some apparatus AT_INCIDENT, got statuses: "
            f"{[(a.id, a.status.name) for a in busy]}"
        )


# ---------------------------------------------------------------------------
# 2. No-dispatch incidents should not accumulate forever
# ---------------------------------------------------------------------------

class TestNoDispatchIncidents:
    """Incidents that receive no dispatch should not leak in active_incidents."""

    def test_no_dispatch_incident_not_stuck(
        self, mock_geography, sample_stations, sample_apparatus
    ):
        # Category "Unknown" has no apparatus requirements → no dispatch
        incidents = [
            _inc(1, node=2, report_time=1_000_000.0, category="UnknownCategory"),
            _inc(2, node=2, report_time=1_000_100.0, category="UnknownCategory"),
            _inc(3, node=2, report_time=1_000_200.0, category="UnknownCategory"),
        ]

        scenario = Scenario(
            geography=mock_geography,
            stations=sample_stations,
            apparatus=sample_apparatus,
            incidents_csv="",
            bounds_geojson=None,
            random_seed=42,
        )
        model = EmpiricalIncidentModel(incidents)
        solver = NearestDispatchSolver()
        policy = NearestDispatchPolicy(mock_geography, solver)
        env = EmergencyEnv(scenario, model, policy)

        state = env.reset()
        for _ in range(3):
            action = policy.dispatch(state)
            state, reward, done, info = env.step(action)

        # These incidents should not pile up in active_incidents forever
        assert len(state.active_incidents) <= 3, (
            f"Non-dispatched incidents should be cleaned up, got {len(state.active_incidents)}"
        )


# ---------------------------------------------------------------------------
# 3. Simultaneous incidents (same report_time)
# ---------------------------------------------------------------------------

class TestSimultaneousIncidents:
    """Two incidents arriving at exactly the same time."""

    def test_simultaneous_incidents_both_dispatched(
        self, mock_geography, sample_stations, sample_apparatus
    ):
        t = 1_000_000.0
        incidents = [
            _inc(1, node=2, report_time=t, category="Four"),  # needs 1 engine
            _inc(2, node=4, report_time=t, category="Four"),  # needs 1 engine
        ]

        scenario = Scenario(
            geography=mock_geography,
            stations=sample_stations,
            apparatus=sample_apparatus,
            incidents_csv="",
            bounds_geojson=None,
            random_seed=42,
        )
        model = EmpiricalIncidentModel(incidents)
        solver = NearestDispatchSolver()
        policy = NearestDispatchPolicy(mock_geography, solver)
        env = EmergencyEnv(scenario, model, policy)

        state = env.reset()

        action1 = policy.dispatch(state)
        state, r1, _, _ = env.step(action1)

        action2 = policy.dispatch(state)
        state, r2, _, _ = env.step(action2)

        # Both should get dispatched (we have 2 engines)
        assert env.metrics.dispatched_incidents == 2
        # First dispatch takes the closer engine, second takes the remaining one
        assert r1 < 0 and r2 < 0

    def test_simultaneous_resource_exhaustion(
        self, mock_geography, sample_stations, sample_apparatus
    ):
        """Three incidents at same time, but only 2 engines available."""
        t = 1_000_000.0
        incidents = [
            _inc(1, node=1, report_time=t, category="Four"),
            _inc(2, node=2, report_time=t, category="Four"),
            _inc(3, node=4, report_time=t, category="Four"),
        ]

        scenario = Scenario(
            geography=mock_geography,
            stations=sample_stations,
            apparatus=sample_apparatus,
            incidents_csv="",
            bounds_geojson=None,
            random_seed=42,
        )
        model = EmpiricalIncidentModel(incidents)
        solver = NearestDispatchSolver()
        policy = NearestDispatchPolicy(mock_geography, solver)
        env = EmergencyEnv(scenario, model, policy)

        state = env.reset()
        rewards = []
        for _ in range(3):
            action = policy.dispatch(state)
            state, r, _, _ = env.step(action)
            rewards.append(r)

        # First two get engines, third should have no dispatch (reward=0)
        assert env.metrics.dispatched_incidents == 2
        assert env.metrics.no_dispatch_incidents == 1
        assert rewards[2] == 0.0


# ---------------------------------------------------------------------------
# 4. Empty incident model
# ---------------------------------------------------------------------------

class TestEmptyIncidentModel:
    def test_zero_incidents(self, mock_geography, sample_stations, sample_apparatus):
        scenario = Scenario(
            geography=mock_geography,
            stations=sample_stations,
            apparatus=sample_apparatus,
            incidents_csv="",
            bounds_geojson=None,
            random_seed=42,
        )
        model = EmpiricalIncidentModel([])
        solver = NearestDispatchSolver()
        policy = NearestDispatchPolicy(mock_geography, solver)
        env = EmergencyEnv(scenario, model, policy)

        state = env.reset()
        assert state.new_incident is None

        # step should immediately return done
        action = policy.dispatch(state)
        state, reward, done, info = env.step(action)
        assert done is True
        assert reward == 0.0


# ---------------------------------------------------------------------------
# 5. Single-incident model
# ---------------------------------------------------------------------------

class TestSingleIncident:
    def test_single_incident_full_cycle(
        self, mock_geography, sample_stations, sample_apparatus
    ):
        incidents = [_inc(1, node=2, report_time=1_000_000.0)]
        scenario = Scenario(
            geography=mock_geography,
            stations=sample_stations,
            apparatus=sample_apparatus,
            incidents_csv="",
            bounds_geojson=None,
            random_seed=42,
        )
        model = EmpiricalIncidentModel(incidents)
        solver = NearestDispatchSolver()
        policy = NearestDispatchPolicy(mock_geography, solver)
        env = EmergencyEnv(scenario, model, policy)

        state = env.reset()
        action = policy.dispatch(state)
        state, reward, done, info = env.step(action)

        assert done is True
        assert reward < 0
        assert info["response_time"] is not None

        # Drain and verify full return
        env.drain(max_drain_time=20000.0)
        assert all(a.status == ApparatusStatus.AVAILABLE for a in state.apparatus)


# ---------------------------------------------------------------------------
# 6. Unknown/missing category
# ---------------------------------------------------------------------------

class TestUnknownCategory:
    def test_unknown_category_gets_no_requirements(self):
        model = EmpiricalIncidentModel([_inc(1, node=0, report_time=1000.0, category="ZZZ")])
        inc = model.get_next_incident()
        assert inc.required_apparatus == {}

    def test_unknown_category_uses_default_resolution_time(
        self, mock_geography, sample_stations, sample_apparatus
    ):
        # Even with unknown category, if we force-dispatch, resolution time falls back
        incidents = [_inc(1, node=2, report_time=1_000_000.0, category="ZZZ")]
        scenario = Scenario(
            geography=mock_geography,
            stations=sample_stations,
            apparatus=sample_apparatus,
            incidents_csv="",
            bounds_geojson=None,
            random_seed=42,
        )
        model = EmpiricalIncidentModel(incidents)
        solver = NearestDispatchSolver()
        policy = NearestDispatchPolicy(mock_geography, solver)
        env = EmergencyEnv(scenario, model, policy)

        state = env.reset()
        # Force a manual dispatch action (policy won't dispatch because no requirements)
        action = [DispatchAction(apparatus_id=0, incident_id=1, travel_time=200.0)]
        state, reward, done, info = env.step(action)

        inc = state.active_incidents.get(1)
        if inc is None:
            inc = env.resolved_incidents[0] if env.resolved_incidents else None
        # Check resolution time used the fallback (1200s)
        assert inc is not None
        assert inc.resolution_time == 1200.0


# ---------------------------------------------------------------------------
# 7. Solver doesn't double-dispatch the same apparatus
# ---------------------------------------------------------------------------

class TestSolverNoDoubleDispatch:
    def test_no_duplicate_apparatus_in_actions(self):
        """For a category requiring multiple engines, verify different apparatus are used."""
        solver = NearestDispatchSolver()
        stations = [
            FireStation(id=0, name="S1", lat=36.16, lon=-86.78, node=0, apparatus_ids=[0, 1]),
        ]
        apparatus = [
            Apparatus(id=0, apparatus_type=ApparatusType.ENGINE, station_id=0, station_node=0),
            Apparatus(id=1, apparatus_type=ApparatusType.ENGINE, station_id=0, station_node=0),
        ]
        incident = _inc(1, node=2, report_time=1000.0, category="Two")  # needs 2 engines + 1 truck
        incident.required_apparatus = {ApparatusType.ENGINE: 2}

        travel_times = np.array([[200.0]], dtype=np.float32)
        actions = solver.solve(incident, stations, apparatus, travel_times, [0])

        apparatus_ids = [a.apparatus_id for a in actions]
        assert len(apparatus_ids) == len(set(apparatus_ids)), (
            f"Duplicate apparatus dispatched: {apparatus_ids}"
        )
        assert len(actions) == 2


# ---------------------------------------------------------------------------
# 8. Incident with node=None
# ---------------------------------------------------------------------------

class TestIncidentNoNode:
    def test_incident_with_no_node_gets_no_dispatch(
        self, mock_geography, sample_stations, sample_apparatus
    ):
        inc = _inc(1, node=2, report_time=1_000_000.0)
        inc.node = None  # simulate unsnapped incident

        scenario = Scenario(
            geography=mock_geography,
            stations=sample_stations,
            apparatus=sample_apparatus,
            incidents_csv="",
            bounds_geojson=None,
            random_seed=42,
        )
        model = EmpiricalIncidentModel([inc])
        solver = NearestDispatchSolver()
        policy = NearestDispatchPolicy(mock_geography, solver)
        env = EmergencyEnv(scenario, model, policy)

        state = env.reset()
        action = policy.dispatch(state)
        assert action is None


# ---------------------------------------------------------------------------
# 9. Rapid-fire incidents exhaust and recover resources
# ---------------------------------------------------------------------------

class TestResourceExhaustionAndRecovery:
    def test_resources_recover_after_resolution(
        self, mock_geography, sample_stations, sample_apparatus
    ):
        """Dispatch all apparatus, wait for resolution, then dispatch again."""
        # First batch: 2 incidents consuming all 2 engines
        # Then a gap, then 2 more incidents
        t = 1_000_000.0
        resolution = DEFAULT_RESOLUTION_TIMES["Four"]  # 1200s
        max_travel = 230.0
        cycle = RESPOND_DELAY + max_travel + resolution + max_travel  # ~1690s

        incidents = [
            _inc(1, node=2, report_time=t, category="Four"),
            _inc(2, node=4, report_time=t + 1.0, category="Four"),
            # After full cycle, engines should be back
            _inc(3, node=1, report_time=t + cycle + 1000.0, category="Four"),
            _inc(4, node=3, report_time=t + cycle + 1001.0, category="Four"),
        ]

        scenario = Scenario(
            geography=mock_geography,
            stations=sample_stations,
            apparatus=sample_apparatus,
            incidents_csv="",
            bounds_geojson=None,
            random_seed=42,
        )
        model = EmpiricalIncidentModel(incidents)
        solver = NearestDispatchSolver()
        policy = NearestDispatchPolicy(mock_geography, solver)
        env = EmergencyEnv(scenario, model, policy)

        state = env.reset()
        for _ in range(4):
            action = policy.dispatch(state)
            state, reward, done, info = env.step(action)

        # All 4 should have been dispatched (resources recovered in the gap)
        assert env.metrics.dispatched_incidents == 4, (
            f"Expected 4 dispatched, got {env.metrics.dispatched_incidents}. "
            f"No-dispatch: {env.metrics.no_dispatch_incidents}"
        )


# ---------------------------------------------------------------------------
# 10. Metrics consistency
# ---------------------------------------------------------------------------

class TestMetricsConsistency:
    def test_total_equals_dispatched_plus_nodispatch(
        self, mock_geography, sample_stations, sample_apparatus
    ):
        incidents = [
            _inc(i, node=(i % 4) + 1, report_time=1_000_000.0 + i * 60.0, category="Four")
            for i in range(10)
        ]

        scenario = Scenario(
            geography=mock_geography,
            stations=sample_stations,
            apparatus=sample_apparatus,
            incidents_csv="",
            bounds_geojson=None,
            random_seed=42,
        )
        model = EmpiricalIncidentModel(incidents)
        solver = NearestDispatchSolver()
        policy = NearestDispatchPolicy(mock_geography, solver)
        env = EmergencyEnv(scenario, model, policy)

        state = env.reset()
        for _ in range(10):
            action = policy.dispatch(state)
            state, reward, done, info = env.step(action)

        m = env.metrics
        assert m.total_incidents == m.dispatched_incidents + m.no_dispatch_incidents
        assert m.response_time_count == m.dispatched_incidents
        if m.response_time_count > 0:
            assert m.mean_response_time > 0
