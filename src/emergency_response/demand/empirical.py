"""Empirical incident model: replays historical incidents from CSV in chronological order."""

from __future__ import annotations

import copy
import logging

from emergency_response.demand.base import IncidentModel
from emergency_response.models.core import (
    DEFAULT_APPARATUS_REQUIREMENTS,
    Incident,
    IncidentStatus,
)

logger = logging.getLogger(__name__)


class EmpiricalIncidentModel(IncidentModel):
    """Serves pre-loaded incidents in chronological order (sorted by report_time)."""

    def __init__(self, incidents: list[Incident]):
        self._incidents = sorted(incidents, key=lambda inc: inc.report_time)
        self._index = 0

    def reset(self) -> None:
        self._index = 0

    def get_next_incident(self) -> Incident | None:
        if self._index >= len(self._incidents):
            return None

        template = self._incidents[self._index]
        self._index += 1

        # Deep copy so each run gets fresh mutable state
        inc = copy.copy(template)
        inc.status = IncidentStatus.REPORTED
        inc.dispatched_apparatus = {}
        inc.arrived_apparatus = {}
        inc.dispatched_units = []
        inc.first_arrival_time = None
        inc.resolution_time = None
        inc.resolved_at = None

        # Set apparatus requirements from category defaults
        inc.required_apparatus = dict(
            DEFAULT_APPARATUS_REQUIREMENTS.get(inc.category, {})
        )

        return inc

    def peek_next_time(self) -> float | None:
        if self._index >= len(self._incidents):
            return None
        return self._incidents[self._index].report_time

    @property
    def total_incidents(self) -> int:
        return len(self._incidents)
