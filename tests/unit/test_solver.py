"""Unit tests for the nearest dispatch solver."""

import numpy as np
import pytest

from emergency_response.models.core import (
    Apparatus,
    ApparatusStatus,
    ApparatusType,
    DispatchAction,
    FireStation,
)
from emergency_response.solver.nearest import NearestDispatchSolver


class TestNearestDispatchSolver:
    @pytest.fixture
    def solver(self):
        return NearestDispatchSolver()

    def test_dispatches_closest_engine(self, solver, sample_stations, sample_apparatus, sample_incident):
        # Station 0 at node 0: travel to node 2 = 200s
        # Station 1 at node 3: travel to node 2 = 50s
        travel_times = np.array([[200.0], [50.0]], dtype=np.float32)
        station_nodes = [0, 3]

        actions = solver.solve(sample_incident, sample_stations, sample_apparatus, travel_times, station_nodes)

        # Should dispatch engine from station 1 (closer) and medic from station 0 (only option)
        engine_actions = [a for a in actions if sample_apparatus[a.apparatus_id].apparatus_type == ApparatusType.ENGINE]
        medic_actions = [a for a in actions if sample_apparatus[a.apparatus_id].apparatus_type == ApparatusType.MEDIC]

        assert len(engine_actions) == 1
        assert len(medic_actions) == 1
        assert engine_actions[0].travel_time == 50.0  # from station 1
        assert medic_actions[0].travel_time == 200.0  # from station 0

    def test_skips_unavailable_apparatus(self, solver, sample_stations, sample_apparatus, sample_incident):
        # Mark the closer engine as dispatched
        sample_apparatus[2].status = ApparatusStatus.EN_ROUTE

        travel_times = np.array([[200.0], [50.0]], dtype=np.float32)
        station_nodes = [0, 3]

        actions = solver.solve(sample_incident, sample_stations, sample_apparatus, travel_times, station_nodes)

        engine_actions = [a for a in actions if sample_apparatus[a.apparatus_id].apparatus_type == ApparatusType.ENGINE]
        assert len(engine_actions) == 1
        assert engine_actions[0].apparatus_id == 0  # falls back to station 0
        assert engine_actions[0].travel_time == 200.0

    def test_empty_when_nothing_available(self, solver, sample_stations, sample_apparatus, sample_incident):
        for a in sample_apparatus:
            a.status = ApparatusStatus.EN_ROUTE

        travel_times = np.array([[200.0], [50.0]], dtype=np.float32)
        actions = solver.solve(sample_incident, sample_stations, sample_apparatus, travel_times, [0, 3])
        assert len(actions) == 0

    def test_handles_unreachable_stations(self, solver, sample_stations, sample_apparatus, sample_incident):
        travel_times = np.array([[1e9], [50.0]], dtype=np.float32)
        actions = solver.solve(sample_incident, sample_stations, sample_apparatus, travel_times, [0, 3])

        # Should only dispatch from reachable station
        for a in actions:
            if sample_apparatus[a.apparatus_id].station_id == 0:
                assert sample_apparatus[a.apparatus_id].apparatus_type == ApparatusType.MEDIC
                # Medic only at station 0, even if unreachable still no other option
