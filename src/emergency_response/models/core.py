"""Core data models for the emergency response gym environment."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import TypeAlias


# --- Location types (same pattern as DVRP-gym) ---


@dataclass(frozen=True, slots=True)
class NodeLocation:
    """A location snapped to a graph node."""

    node: int


@dataclass(frozen=True, slots=True)
class PathLocation:
    """A location along an edge between two graph nodes."""

    path_nodes: tuple[int, ...]
    next_index: int
    remaining_time: float
    elapsed_time: float


Location: TypeAlias = NodeLocation | PathLocation


# --- Enums (mapped from C++ fire_simulator) ---


class ApparatusType(Enum):
    ENGINE = "Engine"
    TRUCK = "Truck"
    RESCUE = "Rescue"
    HAZARD = "Hazard"
    CHIEF = "Chief"
    SQUAD = "Squad"
    FAST = "FAST"
    MEDIC = "Medic"
    BRUSH = "Brush"
    BOAT = "Boat"
    UTV = "UTV"
    REACH = "REACH"


class ApparatusStatus(Enum):
    AVAILABLE = auto()
    DISPATCHED = auto()
    EN_ROUTE = auto()
    AT_INCIDENT = auto()
    RETURNING = auto()


class IncidentStatus(Enum):
    REPORTED = auto()
    RESPONDED = auto()  # first apparatus dispatched
    RESOLVING = auto()  # all required apparatus on scene
    RESOLVED = auto()


class IncidentLevel(Enum):
    LOW = "Low"
    MODERATE = "Moderate"
    HIGH = "High"
    CRITICAL = "Critical"


class IncidentType(Enum):
    BUILDING_FIRE = "Building Fire"
    EMS_RESCUE = "EMS & Rescue"
    VEHICLE_ACCIDENT = "Vehicle Accident"
    GAS_LEAK = "Gas Leak"
    SERVICE_CALL = "Service Call"
    HAZMAT = "Hazmat"
    ALARM = "Alarm"
    OTHER = "Other"


# Nashville FD incident categories
INCIDENT_CATEGORIES = [
    "One", "OneB", "OneC", "Two", "TwoB", "Three", "ThreeB",
    "Four", "FourB", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
    "Sixteen", "Seventeen", "Eighteen",
]


# --- Apparatus requirements by category (from C++ HardCodedFireModel) ---

DEFAULT_APPARATUS_REQUIREMENTS: dict[str, dict[ApparatusType, int]] = {
    "Nine": {ApparatusType.ENGINE: 1, ApparatusType.MEDIC: 1},
    "One": {ApparatusType.ENGINE: 3, ApparatusType.TRUCK: 1, ApparatusType.CHIEF: 1},
    "OneB": {ApparatusType.ENGINE: 3, ApparatusType.TRUCK: 1, ApparatusType.CHIEF: 1},
    "OneC": {ApparatusType.ENGINE: 3, ApparatusType.TRUCK: 1, ApparatusType.CHIEF: 1},
    "Two": {ApparatusType.ENGINE: 2, ApparatusType.TRUCK: 1},
    "TwoB": {ApparatusType.ENGINE: 2, ApparatusType.TRUCK: 1},
    "Three": {ApparatusType.ENGINE: 1, ApparatusType.MEDIC: 1},
    "ThreeB": {ApparatusType.ENGINE: 1, ApparatusType.MEDIC: 1},
    "Four": {ApparatusType.ENGINE: 1},
    "FourB": {ApparatusType.ENGINE: 1},
    "Five": {ApparatusType.ENGINE: 1},
    "Six": {ApparatusType.ENGINE: 1},
    "Seven": {ApparatusType.ENGINE: 1, ApparatusType.TRUCK: 1},
    "Eight": {ApparatusType.ENGINE: 1, ApparatusType.MEDIC: 1},
    "Ten": {ApparatusType.ENGINE: 1},
    "Eleven": {ApparatusType.ENGINE: 1, ApparatusType.HAZARD: 1},
    "Twelve": {ApparatusType.ENGINE: 2, ApparatusType.TRUCK: 1, ApparatusType.RESCUE: 1},
    "Thirteen": {ApparatusType.ENGINE: 1},
    "Fourteen": {ApparatusType.ENGINE: 1, ApparatusType.MEDIC: 1},
    "Fifteen": {ApparatusType.ENGINE: 1},
    "Sixteen": {ApparatusType.ENGINE: 1},
    "Seventeen": {ApparatusType.ENGINE: 1},
    "Eighteen": {ApparatusType.ENGINE: 1},
}

# Mean resolution time in seconds by category (simplified from C++ HistoricalFireModel)
DEFAULT_RESOLUTION_TIMES: dict[str, float] = {
    "One": 3600.0,
    "OneB": 3600.0,
    "OneC": 3600.0,
    "Two": 2400.0,
    "TwoB": 2400.0,
    "Three": 1800.0,
    "ThreeB": 1800.0,
    "Four": 1200.0,
    "FourB": 1200.0,
    "Five": 900.0,
    "Six": 900.0,
    "Seven": 1800.0,
    "Eight": 1500.0,
    "Nine": 1500.0,
    "Ten": 900.0,
    "Eleven": 2400.0,
    "Twelve": 2400.0,
    "Thirteen": 900.0,
    "Fourteen": 1500.0,
    "Fifteen": 900.0,
    "Sixteen": 900.0,
    "Seventeen": 900.0,
    "Eighteen": 900.0,
}


# --- Core data models ---


@dataclass(slots=True)
class Incident:
    """An emergency incident requiring response."""

    id: int
    lat: float
    lon: float
    incident_type: IncidentType
    level: IncidentLevel
    datetime: datetime
    category: str

    # Set after snapping to graph
    node: int | None = None

    # State tracking
    status: IncidentStatus = IncidentStatus.REPORTED
    required_apparatus: dict[ApparatusType, int] = field(default_factory=dict)
    dispatched_apparatus: dict[ApparatusType, int] = field(default_factory=dict)
    arrived_apparatus: dict[ApparatusType, int] = field(default_factory=dict)

    # Timing
    report_time: float = 0.0  # epoch seconds
    first_arrival_time: float | None = None  # response time = first_arrival - report_time
    resolution_time: float | None = None  # when incident fully resolved
    resolved_at: float | None = None

    # Dispatched apparatus tracking: list of (apparatus_id, travel_time)
    dispatched_units: list[tuple[int, float]] = field(default_factory=list)

    @property
    def response_time(self) -> float | None:
        if self.first_arrival_time is not None:
            return self.first_arrival_time - self.report_time
        return None


@dataclass(slots=True)
class Apparatus:
    """A single fire/EMS apparatus (vehicle)."""

    id: int
    apparatus_type: ApparatusType
    station_id: int
    station_node: int  # graph node of home station

    status: ApparatusStatus = ApparatusStatus.AVAILABLE
    location: Location | None = None  # current location (None = at station)
    incident_id: int | None = None

    # Timing
    dispatch_time: float | None = None
    arrival_time: float | None = None  # when it will arrive at incident
    return_time: float | None = None  # when it will return to station


@dataclass(slots=True)
class FireStation:
    """A fire station with its apparatus inventory."""

    id: int
    name: str
    lat: float
    lon: float
    node: int  # graph node (snapped)

    apparatus_ids: list[int] = field(default_factory=list)


# --- Action types ---


@dataclass(frozen=True, slots=True)
class DispatchAction:
    """Dispatch a specific apparatus to an incident."""

    apparatus_id: int
    incident_id: int
    travel_time: float  # seconds


Action: TypeAlias = list[DispatchAction] | None


# --- State ---


@dataclass(slots=True)
class State:
    """Full observable state of the emergency response system."""

    current_time: float
    stations: list[FireStation]
    apparatus: list[Apparatus]
    active_incidents: dict[int, Incident]
    new_incident: Incident | None  # the incident to respond to this step

    def available_apparatus_at_station(self, station_id: int) -> list[Apparatus]:
        return [
            a for a in self.apparatus
            if a.station_id == station_id and a.status == ApparatusStatus.AVAILABLE
        ]

    def available_apparatus_of_type(self, apparatus_type: ApparatusType) -> list[Apparatus]:
        return [
            a for a in self.apparatus
            if a.apparatus_type == apparatus_type and a.status == ApparatusStatus.AVAILABLE
        ]
