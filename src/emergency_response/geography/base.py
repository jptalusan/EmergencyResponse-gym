"""TravelTimeProvider protocol — extensible interface for geography backends.

Initial implementation: NetworkGeography (OSMnx + NetworkX).
Future: OSRMGeography (real OSRM server).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from emergency_response.models.core import Location, NodeLocation


@runtime_checkable
class TravelTimeProvider(Protocol):
    """Interface for computing travel times and locations on a road network."""

    def drive_time(self, origin: Location, destination: Location) -> float:
        """Driving time from origin to destination in seconds."""
        ...

    def drive_time_matrix(self, origins: list[int], destinations: list[int]) -> np.ndarray:
        """Matrix of driving times between lists of node indices.

        Returns shape (len(origins), len(destinations)).
        """
        ...

    def intermediate_location(self, origin: Location, destination: Location, time_budget: float) -> Location:
        """Location reachable from origin toward destination after driving for time_budget seconds."""
        ...

    def nearest_node(self, lat: float, lon: float) -> int:
        """Return the graph node index nearest to the given lat/lon."""
        ...

    def node_coords(self, node: int) -> tuple[float, float]:
        """Return (lat, lon) for a graph node index."""
        ...

    @property
    def num_nodes(self) -> int:
        """Total number of nodes in the graph."""
        ...
