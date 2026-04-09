"""Base class for dispatch solvers."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from emergency_response.models.core import Apparatus, DispatchAction, FireStation, Incident


class DispatchSolver(ABC):
    """Abstract base class for computing dispatch decisions.

    A solver takes an incident and available resources, and returns
    a list of DispatchActions (which apparatus to send).
    """

    @abstractmethod
    def solve(
        self,
        incident: Incident,
        stations: list[FireStation],
        apparatus: list[Apparatus],
        travel_time_matrix: np.ndarray,
        station_nodes: list[int],
    ) -> list[DispatchAction]:
        """Compute dispatch actions for an incident.

        Args:
            incident: The incident to respond to.
            stations: All fire stations.
            apparatus: All apparatus (check status for availability).
            travel_time_matrix: Matrix of shape (n_stations, 1) with travel times
                from each station to the incident.
            station_nodes: Node index for each station (parallel to stations list).

        Returns:
            List of DispatchAction, one per apparatus to dispatch.
        """
        ...
