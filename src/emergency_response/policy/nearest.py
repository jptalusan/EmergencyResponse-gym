"""Nearest dispatch policy: dispatch closest available apparatus using a solver."""

from __future__ import annotations

from emergency_response.geography.base import TravelTimeProvider
from emergency_response.models.core import Action, State
from emergency_response.policy.base import DispatchPolicy
from emergency_response.solver.base import DispatchSolver


class NearestDispatchPolicy(DispatchPolicy):
    """Uses the solver to dispatch nearest available apparatus to each incident."""

    def __init__(self, geography: TravelTimeProvider, solver: DispatchSolver):
        self._geography = geography
        self._solver = solver

    def dispatch(self, state: State) -> Action:
        incident = state.new_incident
        if incident is None or incident.node is None:
            return None

        # Compute travel times from all stations to the incident
        station_nodes = [s.node for s in state.stations]
        travel_time_matrix = self._geography.drive_time_matrix(
            station_nodes, [incident.node]
        )

        actions = self._solver.solve(
            incident=incident,
            stations=state.stations,
            apparatus=state.apparatus,
            travel_time_matrix=travel_time_matrix,
            station_nodes=station_nodes,
        )

        return actions if actions else None
