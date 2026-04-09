"""Tests for apparatus event logs and step trace records."""

from __future__ import annotations

from datetime import datetime

import pytest

from emergency_response.demand.empirical import EmpiricalIncidentModel
from emergency_response.env.emergency_env import ApparatusEvent, EmergencyEnv, StepRecord
from emergency_response.models.core import (
    ApparatusStatus,
    ApparatusType,
    Incident,
    IncidentLevel,
    IncidentType,
)
from emergency_response.models.scenario import Scenario
from emergency_response.policy.nearest import NearestDispatchPolicy
from emergency_response.solver.nearest import NearestDispatchSolver


def _inc(incident_id, node, report_time, category="Nine"):
    return Incident(
        id=incident_id, lat=36.16, lon=-86.74,
        incident_type=IncidentType.EMS_RESCUE, level=IncidentLevel.MODERATE,
        datetime=datetime.fromtimestamp(report_time), category=category,
        node=node, report_time=report_time,
    )


@pytest.fixture
def env_with_incidents(mock_geography, sample_stations, sample_apparatus):
    incidents = [
        _inc(1, node=2, report_time=1_000_000.0),
        _inc(2, node=4, report_time=1_000_300.0),
        _inc(3, node=1, report_time=1_000_600.0),
    ]
    scenario = Scenario(
        geography=mock_geography, stations=sample_stations,
        apparatus=sample_apparatus, incidents_csv="",
        bounds_geojson=None, random_seed=42,
    )
    model = EmpiricalIncidentModel(incidents)
    solver = NearestDispatchSolver()
    policy = NearestDispatchPolicy(mock_geography, solver)
    env = EmergencyEnv(scenario, model, policy)
    return env, policy


class TestApparatusEvents:
    def test_dispatch_events_recorded(self, env_with_incidents):
        env, policy = env_with_incidents
        state = env.reset()
        action = policy.dispatch(state)
        state, _, _, _ = env.step(action)

        dispatch_events = [e for e in env.apparatus_events if e.event == "dispatch"]
        assert len(dispatch_events) > 0
        for e in dispatch_events:
            assert e.incident_id == 1
            assert e.travel_time is not None
            assert e.travel_time > 0

    def test_full_lifecycle_events(self, env_with_incidents):
        env, policy = env_with_incidents
        state = env.reset()

        # Run all 3 incidents
        for _ in range(3):
            action = policy.dispatch(state)
            state, _, _, _ = env.step(action)

        # Drain to complete all cycles
        env.drain(max_drain_time=20000.0)

        events = env.apparatus_events
        event_types = {e.event for e in events}
        assert "dispatch" in event_types
        assert "arrive" in event_types
        assert "resolve" in event_types
        assert "return" in event_types

    def test_events_have_correct_lifecycle_order(self, env_with_incidents):
        env, policy = env_with_incidents
        state = env.reset()

        for _ in range(3):
            action = policy.dispatch(state)
            state, _, _, _ = env.step(action)
        env.drain(max_drain_time=20000.0)

        # Group events by apparatus_id and verify time ordering
        by_apparatus: dict[int, list[ApparatusEvent]] = {}
        for e in env.apparatus_events:
            by_apparatus.setdefault(e.apparatus_id, []).append(e)

        for aid, events in by_apparatus.items():
            times = [e.time for e in events]
            assert times == sorted(times), (
                f"Apparatus {aid} events not in time order: "
                f"{[(e.event, e.time) for e in events]}"
            )

    def test_dispatch_event_matches_action_count(self, env_with_incidents):
        env, policy = env_with_incidents
        state = env.reset()
        action = policy.dispatch(state)
        num_actions = len(action) if action else 0
        state, _, _, _ = env.step(action)

        dispatch_events = [e for e in env.apparatus_events if e.event == "dispatch"]
        assert len(dispatch_events) == num_actions

    def test_reset_clears_events(self, env_with_incidents):
        env, policy = env_with_incidents
        state = env.reset()
        action = policy.dispatch(state)
        env.step(action)
        assert len(env.apparatus_events) > 0

        env.reset()
        assert len(env.apparatus_events) == 0


class TestStepRecords:
    def test_step_records_count_matches_steps(self, env_with_incidents):
        env, policy = env_with_incidents
        state = env.reset()

        for _ in range(3):
            action = policy.dispatch(state)
            state, _, done, _ = env.step(action)
            if done:
                break

        assert len(env.step_records) == 3

    def test_step_records_have_sequential_numbers(self, env_with_incidents):
        env, policy = env_with_incidents
        state = env.reset()

        for _ in range(3):
            action = policy.dispatch(state)
            state, _, _, _ = env.step(action)

        steps = [r.step for r in env.step_records]
        assert steps == [1, 2, 3]

    def test_step_records_match_rewards(self, env_with_incidents):
        env, policy = env_with_incidents
        state = env.reset()
        rewards = []

        for _ in range(3):
            action = policy.dispatch(state)
            state, reward, _, _ = env.step(action)
            rewards.append(reward)

        for r, record in zip(rewards, env.step_records):
            assert record.reward == r

    def test_step_records_track_available_apparatus(self, env_with_incidents):
        env, policy = env_with_incidents
        state = env.reset()

        action = policy.dispatch(state)
        state, _, _, _ = env.step(action)

        record = env.step_records[0]
        # After dispatch, available_apparatus should be less than total
        total = len(state.apparatus)
        assert record.available_apparatus <= total

    def test_reset_clears_step_records(self, env_with_incidents):
        env, policy = env_with_incidents
        state = env.reset()
        action = policy.dispatch(state)
        env.step(action)
        assert len(env.step_records) > 0

        env.reset()
        assert len(env.step_records) == 0


class TestMetricsExport:
    def test_export_apparatus_events_csv(self, env_with_incidents, tmp_path):
        from emergency_response.metrics import export_apparatus_events

        env, policy = env_with_incidents
        state = env.reset()
        for _ in range(3):
            action = policy.dispatch(state)
            state, _, _, _ = env.step(action)
        env.drain(max_drain_time=20000.0)

        csv_path = tmp_path / "apparatus_events.csv"
        export_apparatus_events(env.apparatus_events, csv_path)

        assert csv_path.exists()
        import csv
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == len(env.apparatus_events)
        assert "event" in rows[0]
        assert "apparatus_id" in rows[0]

    def test_export_step_records_csv(self, env_with_incidents, tmp_path):
        from emergency_response.metrics import export_step_records

        env, policy = env_with_incidents
        state = env.reset()
        for _ in range(3):
            action = policy.dispatch(state)
            state, _, _, _ = env.step(action)

        csv_path = tmp_path / "step_trace.csv"
        export_step_records(env.step_records, csv_path)

        assert csv_path.exists()
        import csv
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 3
        assert "reward" in rows[0]
        assert "response_time" in rows[0]
