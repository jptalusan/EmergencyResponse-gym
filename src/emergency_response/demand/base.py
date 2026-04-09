"""Base class for incident demand models."""

from __future__ import annotations

from abc import ABC, abstractmethod

from emergency_response.models.core import Incident


class IncidentModel(ABC):
    """Abstract base class for incident generation/replay."""

    @abstractmethod
    def reset(self) -> None:
        """Reset to the beginning of the incident stream."""
        ...

    @abstractmethod
    def get_next_incident(self) -> Incident | None:
        """Return the next incident chronologically, or None if exhausted."""
        ...

    @abstractmethod
    def peek_next_time(self) -> float | None:
        """Return the report_time of the next incident without consuming it."""
        ...

    @property
    @abstractmethod
    def total_incidents(self) -> int:
        """Total number of incidents in the model."""
        ...
