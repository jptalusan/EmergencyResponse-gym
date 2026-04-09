"""Scenario: assembled from Hydra config, holds all components needed to run a simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from emergency_response.geography.base import TravelTimeProvider
    from emergency_response.models.core import Apparatus, FireStation


@dataclass(frozen=True, slots=True)
class Scenario:
    """All configuration and components needed for a simulation run."""

    geography: TravelTimeProvider
    stations: list[FireStation]
    apparatus: list[Apparatus]
    incidents_csv: str
    bounds_geojson: str | None
    random_seed: int
