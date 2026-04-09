"""Nearest dispatch solver: send closest available apparatus for each required type."""

from __future__ import annotations

import logging

import numpy as np

from emergency_response.models.core import (
    Apparatus,
    ApparatusStatus,
    ApparatusType,
    DispatchAction,
    FireStation,
    Incident,
)
from emergency_response.solver.base import DispatchSolver

logger = logging.getLogger(__name__)


class NearestDispatchSolver(DispatchSolver):
    """Greedily dispatch the closest available apparatus of each required type."""

    def solve(
        self,
        incident: Incident,
        stations: list[FireStation],
        apparatus: list[Apparatus],
        travel_time_matrix: np.ndarray,
        station_nodes: list[int],
    ) -> list[DispatchAction]:
        actions: list[DispatchAction] = []

        # Build station_id -> index in stations list
        station_idx_map = {s.id: i for i, s in enumerate(stations)}

        # Build station_id -> travel time to incident
        station_travel_times: dict[int, float] = {}
        for i, station in enumerate(stations):
            station_travel_times[station.id] = float(travel_time_matrix[i, 0])

        # For each required apparatus type, find closest available
        for app_type, count_needed in incident.required_apparatus.items():
            # Gather available apparatus of this type with their station travel times
            candidates: list[tuple[Apparatus, float]] = []
            for a in apparatus:
                if a.apparatus_type == app_type and a.status == ApparatusStatus.AVAILABLE:
                    tt = station_travel_times.get(a.station_id, 1e9)
                    candidates.append((a, tt))

            # Sort by travel time (nearest first)
            candidates.sort(key=lambda x: x[1])

            # Dispatch up to count_needed
            dispatched = 0
            for a, tt in candidates:
                if dispatched >= count_needed:
                    break
                if tt >= 1e9:
                    continue  # unreachable
                actions.append(DispatchAction(
                    apparatus_id=a.id,
                    incident_id=incident.id,
                    travel_time=tt,
                ))
                dispatched += 1

            if dispatched < count_needed:
                logger.debug(
                    "Incident %d: could only dispatch %d/%d %s",
                    incident.id, dispatched, count_needed, app_type.value,
                )

        return actions
