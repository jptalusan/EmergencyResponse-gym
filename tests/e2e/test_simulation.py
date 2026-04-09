"""End-to-end simulation tests using mock geography (no network download)."""

from __future__ import annotations

from datetime import datetime

import pytest

from emergency_response.demand.empirical import EmpiricalIncidentModel
from emergency_response.env.emergency_env import EmergencyEnv
from emergency_response.models.core import (
    Apparatus,
    ApparatusStatus,
    ApparatusType,
    FireStation,
    Incident,
    IncidentLevel,
    IncidentType,
)
from emergency_response.models.scenario import Scenario
from emergency_response.policy.nearest import NearestDispatchPolicy
from emergency_response.solver.nearest import NearestDispatchSolver


def _make_incidents(n: int, start_time: float = 1_000_000.0, interval: float = 300.0) -> list[Incident]:
    """Create n incidents spread across nodes 1-4, every `interval` seconds."""
    return [
        Incident(
            id=i,
            lat=36.16 - (i % 2) * 0.02,
            lon=-86.74 - (i % 3) * 0.02,
            incident_type=IncidentType.EMS_RESCUE,
            level=IncidentLevel.MODERATE,
            datetime=datetime.fromtimestamp(start_time + i * interval),
            category="Nine",
            node=(i % 4) + 1,  # nodes 1-4
            report_time=start_time + i * interval,
        )
        for i in range(n)
    ]


@pytest.fixture
def scenario(mock_geography, sample_stations, sample_apparatus):
    return Scenario(
        geography=mock_geography,
        stations=sample_stations,
        apparatus=sample_apparatus,
        incidents_csv="",
        bounds_geojson=None,
        random_seed=42,
    )


@pytest.fixture
def incident_model():
    return EmpiricalIncidentModel(_make_incidents(20))


@pytest.fixture
def policy(mock_geography):
    solver = NearestDispatchSolver()
    return NearestDispatchPolicy(mock_geography, solver)


class TestBasicSimulation:
    def test_step_loop(self, scenario, incident_model, policy):
        env = EmergencyEnv(scenario, incident_model, policy)
        state = env.reset()

        assert state.new_incident is not None

        for _ in range(10):
            action = policy.dispatch(state)
            state, reward, done, info = env.step(action)
            assert reward <= 0.0  # negative response time
            assert "response_time" in info

        assert env.metrics.total_incidents == 10
        assert env.metrics.dispatched_incidents > 0

    def test_runs_until_done(self, scenario, incident_model, policy):
        env = EmergencyEnv(scenario, incident_model, policy)
        state = env.reset()

        steps = 0
        while True:
            action = policy.dispatch(state)
            state, reward, done, info = env.step(action)
            steps += 1
            if done:
                break

        assert steps == 20
        assert env.metrics.total_incidents == 20

    def test_reward_is_negative_response_time(self, scenario, incident_model, policy):
        env = EmergencyEnv(scenario, incident_model, policy)
        state = env.reset()

        action = policy.dispatch(state)
        state, reward, done, info = env.step(action)

        response_time = info["response_time"]
        if response_time is not None:
            assert reward == pytest.approx(-response_time)

    def test_mean_response_time_reasonable(self, scenario, incident_model, policy):
        env = EmergencyEnv(scenario, incident_model, policy)
        state = env.reset()

        for _ in range(20):
            action = policy.dispatch(state)
            state, reward, done, info = env.step(action)
            if done:
                break

        # With a 5-node graph where max travel time is ~230s + 60s delay
        assert env.metrics.mean_response_time > 0
        assert env.metrics.mean_response_time < 500.0


class TestDrain:
    def test_drain_resolves_incidents(self, scenario, incident_model, policy):
        env = EmergencyEnv(scenario, incident_model, policy)
        state = env.reset()

        for _ in range(5):
            action = policy.dispatch(state)
            state, reward, done, info = env.step(action)

        env.drain(max_drain_time=10000.0)

        # After draining, some incidents should be resolved
        assert env.metrics.resolved_incidents > 0

    def test_drain_returns_apparatus(self, scenario, incident_model, policy):
        env = EmergencyEnv(scenario, incident_model, policy)
        state = env.reset()

        for _ in range(3):
            action = policy.dispatch(state)
            state, reward, done, info = env.step(action)

        env.drain(max_drain_time=20000.0)

        # All apparatus should be available after sufficient drain
        available_count = sum(
            1 for a in state.apparatus
            if a.status == ApparatusStatus.AVAILABLE
        )
        assert available_count == len(state.apparatus)


class TestEnvironmentReset:
    def test_reset_clears_state(self, scenario, incident_model, policy):
        env = EmergencyEnv(scenario, incident_model, policy)
        state = env.reset()

        for _ in range(5):
            action = policy.dispatch(state)
            state, reward, done, info = env.step(action)

        # Reset
        state = env.reset()
        assert env.metrics.total_incidents == 0
        assert env.metrics.dispatched_incidents == 0
        assert len(state.active_incidents) == 0
        assert all(a.status == ApparatusStatus.AVAILABLE for a in state.apparatus)

    def test_reproducibility(self, scenario, policy):
        incidents1 = _make_incidents(10)
        incidents2 = _make_incidents(10)
        model1 = EmpiricalIncidentModel(incidents1)
        model2 = EmpiricalIncidentModel(incidents2)

        env1 = EmergencyEnv(scenario, model1, policy)
        env2 = EmergencyEnv(scenario, model2, policy)

        state1 = env1.reset()
        state2 = env2.reset()

        rewards1, rewards2 = [], []
        for _ in range(10):
            a1 = policy.dispatch(state1)
            state1, r1, _, _ = env1.step(a1)
            rewards1.append(r1)

            a2 = policy.dispatch(state2)
            state2, r2, _, _ = env2.step(a2)
            rewards2.append(r2)

        assert rewards1 == rewards2


class TestApparatusStateTransitions:
    def test_apparatus_goes_through_states(self, scenario, policy):
        # Two incidents 200s apart — apparatus from incident 1 will be mid-cycle
        # when incident 2 is presented (travel ~50-200s + 60s delay, resolution 1500s)
        incidents = _make_incidents(2, interval=200.0)
        model = EmpiricalIncidentModel(incidents)
        env = EmergencyEnv(scenario, model, policy)
        state = env.reset()

        # Before dispatch: all available
        assert all(a.status == ApparatusStatus.AVAILABLE for a in state.apparatus)

        action = policy.dispatch(state)
        state, reward, done, info = env.step(action)

        # After dispatch + 200s advance: some should be en_route or at_incident
        # (not done yet — resolution takes 1500s)
        dispatched = [a for a in state.apparatus if a.status != ApparatusStatus.AVAILABLE]
        assert len(dispatched) > 0

        # Finish and drain to completion
        action = policy.dispatch(state)
        state, reward, done, info = env.step(action)
        env.drain(max_drain_time=20000.0)

        # After drain: all should be back to available
        assert all(a.status == ApparatusStatus.AVAILABLE for a in state.apparatus)
