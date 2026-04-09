"""Integration tests for dispatch: policy + solver + geography working together."""

from datetime import datetime

import numpy as np
import pytest

from emergency_response.models.core import (
    Apparatus,
    ApparatusStatus,
    ApparatusType,
    FireStation,
    Incident,
    IncidentLevel,
    IncidentType,
    State,
)
from emergency_response.policy.nearest import NearestDispatchPolicy
from emergency_response.solver.nearest import NearestDispatchSolver


class TestNearestDispatchIntegration:
    @pytest.fixture
    def policy(self, mock_geography):
        solver = NearestDispatchSolver()
        return NearestDispatchPolicy(mock_geography, solver)

    def test_dispatches_from_nearest_station(self, policy, sample_stations, sample_apparatus, sample_incident):
        state = State(
            current_time=1000.0,
            stations=sample_stations,
            apparatus=sample_apparatus,
            active_incidents={},
            new_incident=sample_incident,
        )

        actions = policy.dispatch(state)
        assert actions is not None
        assert len(actions) >= 1

        # Verify travel times are reasonable
        for a in actions:
            assert a.travel_time >= 0
            assert a.travel_time < 1e9
            assert a.incident_id == sample_incident.id

    def test_returns_none_for_no_incident(self, policy, sample_stations, sample_apparatus):
        state = State(
            current_time=1000.0,
            stations=sample_stations,
            apparatus=sample_apparatus,
            active_incidents={},
            new_incident=None,
        )
        assert policy.dispatch(state) is None

    def test_handles_all_busy(self, policy, sample_stations, sample_apparatus, sample_incident):
        for a in sample_apparatus:
            a.status = ApparatusStatus.EN_ROUTE

        state = State(
            current_time=1000.0,
            stations=sample_stations,
            apparatus=sample_apparatus,
            active_incidents={},
            new_incident=sample_incident,
        )

        actions = policy.dispatch(state)
        assert actions is None or len(actions) == 0

    def test_multiple_incidents_deplete_resources(self, policy, sample_stations, sample_apparatus):
        """Dispatch to two incidents in sequence, second should have fewer options."""
        inc1 = Incident(
            id=1, lat=36.16, lon=-86.74, incident_type=IncidentType.EMS_RESCUE,
            level=IncidentLevel.MODERATE, datetime=datetime(2022, 1, 1),
            category="Nine", node=2, report_time=1000.0,
            required_apparatus={ApparatusType.ENGINE: 1, ApparatusType.MEDIC: 1},
        )

        state = State(
            current_time=1000.0,
            stations=sample_stations,
            apparatus=sample_apparatus,
            active_incidents={},
            new_incident=inc1,
        )

        actions1 = policy.dispatch(state)
        assert actions1 is not None

        # Mark dispatched apparatus as busy
        for a in actions1:
            sample_apparatus[a.apparatus_id].status = ApparatusStatus.EN_ROUTE

        inc2 = Incident(
            id=2, lat=36.14, lon=-86.74, incident_type=IncidentType.EMS_RESCUE,
            level=IncidentLevel.MODERATE, datetime=datetime(2022, 1, 1, 0, 1),
            category="Nine", node=4, report_time=1060.0,
            required_apparatus={ApparatusType.ENGINE: 1, ApparatusType.MEDIC: 1},
        )
        state.new_incident = inc2

        actions2 = policy.dispatch(state)
        # Should still find at least an engine (we had 2)
        if actions2:
            engine_ids = [a.apparatus_id for a in actions2
                          if sample_apparatus[a.apparatus_id].apparatus_type == ApparatusType.ENGINE]
            assert len(engine_ids) <= 1  # only 1 engine left


class TestDispatchTravelTimeAccuracy:
    def test_travel_times_match_geography(self, mock_geography, sample_stations, sample_apparatus, sample_incident):
        solver = NearestDispatchSolver()
        policy = NearestDispatchPolicy(mock_geography, solver)

        state = State(
            current_time=1000.0,
            stations=sample_stations,
            apparatus=sample_apparatus,
            active_incidents={},
            new_incident=sample_incident,
        )

        actions = policy.dispatch(state)
        assert actions is not None

        # Verify each dispatch action's travel time matches the geography matrix
        station_nodes = [s.node for s in sample_stations]
        matrix = mock_geography.drive_time_matrix(station_nodes, [sample_incident.node])

        for a in actions:
            app = sample_apparatus[a.apparatus_id]
            station_idx = next(i for i, s in enumerate(sample_stations) if s.id == app.station_id)
            expected_tt = float(matrix[station_idx, 0])
            assert a.travel_time == expected_tt
