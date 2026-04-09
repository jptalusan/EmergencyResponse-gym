"""EmergencyEnv: event-driven gym environment for fire/EMS emergency response."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from emergency_response.demand.base import IncidentModel
from emergency_response.geography.base import TravelTimeProvider
from emergency_response.models.core import (
    Action,
    Apparatus,
    ApparatusStatus,
    DEFAULT_RESOLUTION_TIMES,
    DispatchAction,
    FireStation,
    Incident,
    IncidentStatus,
    NodeLocation,
    State,
)
from emergency_response.models.scenario import Scenario
from emergency_response.policy.base import DispatchPolicy

logger = logging.getLogger(__name__)

# Delay (seconds) between dispatch decision and apparatus starting to move
RESPOND_DELAY = 60.0


@dataclass(frozen=True, slots=True)
class ApparatusEvent:
    """A single event in an apparatus's lifecycle."""

    time: float
    apparatus_id: int
    apparatus_type: str
    station_id: int
    incident_id: int | None
    event: str  # "dispatch", "arrive", "resolve", "return"
    travel_time: float | None = None


@dataclass(frozen=True, slots=True)
class StepRecord:
    """One row per env.step() call."""

    step: int
    time: float
    incident_id: int
    category: str
    reward: float
    response_time: float | None
    num_dispatched: int
    active_incidents: int
    available_apparatus: int


@dataclass
class SimMetrics:
    """Running simulation metrics."""

    total_incidents: int = 0
    dispatched_incidents: int = 0
    fully_served_incidents: int = 0
    resolved_incidents: int = 0
    no_dispatch_incidents: int = 0
    total_response_time: float = 0.0
    response_time_count: int = 0

    @property
    def mean_response_time(self) -> float:
        return self.total_response_time / max(self.response_time_count, 1)


class EmergencyEnv:
    """Event-driven gym environment for emergency response simulation.

    Each step:
    1. Presents a new incident (state.new_incident).
    2. Receives dispatch actions from a policy.
    3. Simulates apparatus movement forward to the next incident time.
    4. Returns (state, reward, done, info).

    Reward = negative response time (travel time of first-arriving apparatus).
    """

    def __init__(
        self,
        scenario: Scenario,
        incident_model: IncidentModel,
        policy: DispatchPolicy,
    ):
        self._scenario = scenario
        self._geography = scenario.geography
        self._incident_model = incident_model
        self._policy = policy

        # Mutable state
        self._current_time: float = 0.0
        self._stations: list[FireStation] = []
        self._apparatus: list[Apparatus] = []
        self._active_incidents: dict[int, Incident] = {}
        self._resolved_incidents: list[Incident] = []
        self._new_incident: Incident | None = None
        self._metrics = SimMetrics()
        self._apparatus_events: list[ApparatusEvent] = []
        self._step_records: list[StepRecord] = []
        self._step_count: int = 0

    def _init_apparatus(self) -> None:
        """Deep copy apparatus from scenario so each run has fresh mutable state."""
        self._stations = []
        for s in self._scenario.stations:
            self._stations.append(FireStation(
                id=s.id, name=s.name, lat=s.lat, lon=s.lon,
                node=s.node, apparatus_ids=list(s.apparatus_ids),
            ))

        self._apparatus = []
        for a in self._scenario.apparatus:
            self._apparatus.append(Apparatus(
                id=a.id, apparatus_type=a.apparatus_type,
                station_id=a.station_id, station_node=a.station_node,
            ))

    def _get_state(self) -> State:
        return State(
            current_time=self._current_time,
            stations=self._stations,
            apparatus=self._apparatus,
            active_incidents=self._active_incidents,
            new_incident=self._new_incident,
        )

    def reset(self) -> State:
        """Initialize the environment and return the first state."""
        self._incident_model.reset()
        self._init_apparatus()
        self._active_incidents.clear()
        self._resolved_incidents.clear()
        self._metrics = SimMetrics()
        self._apparatus_events.clear()
        self._step_records.clear()
        self._step_count = 0

        # Get first incident
        self._new_incident = self._incident_model.get_next_incident()
        if self._new_incident is not None:
            self._current_time = self._new_incident.report_time
        else:
            self._current_time = 0.0

        return self._get_state()

    def step(self, action: Action) -> tuple[State, float, bool, dict]:
        """Process one incident with the given dispatch action.

        Args:
            action: List of DispatchActions, or None (no dispatch).

        Returns:
            (state, reward, done, info)
        """
        self._metrics.total_incidents += 1
        reward = 0.0
        incident = self._new_incident

        if incident is None:
            return self._get_state(), 0.0, True, {"metrics": self._metrics}

        if action is not None and len(action) > 0:
            reward = self._execute_dispatch(incident, action)
            self._active_incidents[incident.id] = incident
        else:
            self._metrics.no_dispatch_incidents += 1
            incident.status = IncidentStatus.REPORTED
            self._active_incidents[incident.id] = incident

        # Advance to next incident time
        self._new_incident = self._incident_model.get_next_incident()
        done = self._new_incident is None

        if not done:
            next_time = self._new_incident.report_time
        else:
            # No more incidents — advance a drain period to let apparatus return
            next_time = self._current_time + 3600.0

        # Simulate forward
        self._simulate_time_step(next_time)
        self._current_time = next_time

        # Record step trace
        self._step_count += 1
        num_dispatched = len(action) if action else 0
        available_count = sum(
            1 for a in self._apparatus if a.status == ApparatusStatus.AVAILABLE
        )
        self._step_records.append(StepRecord(
            step=self._step_count,
            time=incident.report_time,
            incident_id=incident.id,
            category=incident.category,
            reward=reward,
            response_time=incident.response_time,
            num_dispatched=num_dispatched,
            active_incidents=len(self._active_incidents),
            available_apparatus=available_count,
        ))

        info = {
            "metrics": self._metrics,
            "response_time": incident.response_time,
            "incident_id": incident.id,
        }
        return self._get_state(), reward, done, info

    def _execute_dispatch(self, incident: Incident, actions: list[DispatchAction]) -> float:
        """Execute dispatch actions and return reward (negative response time)."""
        self._metrics.dispatched_incidents += 1
        incident.status = IncidentStatus.RESPONDED

        min_travel_time = float("inf")

        for da in actions:
            apparatus = self._apparatus[da.apparatus_id]
            apparatus.status = ApparatusStatus.EN_ROUTE
            apparatus.incident_id = incident.id
            apparatus.dispatch_time = self._current_time
            apparatus.arrival_time = self._current_time + RESPOND_DELAY + da.travel_time

            if incident.node is not None:
                apparatus.location = NodeLocation(incident.node)

            # Track on incident
            app_type = apparatus.apparatus_type
            incident.dispatched_apparatus[app_type] = (
                incident.dispatched_apparatus.get(app_type, 0) + 1
            )
            incident.dispatched_units.append((da.apparatus_id, da.travel_time))

            self._apparatus_events.append(ApparatusEvent(
                time=self._current_time,
                apparatus_id=da.apparatus_id,
                apparatus_type=apparatus.apparatus_type.value,
                station_id=apparatus.station_id,
                incident_id=incident.id,
                event="dispatch",
                travel_time=da.travel_time,
            ))

            if da.travel_time < min_travel_time:
                min_travel_time = da.travel_time

        # Set first arrival time (for response time calculation)
        if min_travel_time < float("inf"):
            incident.first_arrival_time = self._current_time + RESPOND_DELAY + min_travel_time
            self._metrics.total_response_time += min_travel_time + RESPOND_DELAY
            self._metrics.response_time_count += 1

        # Set resolution time from category defaults
        base_resolution = DEFAULT_RESOLUTION_TIMES.get(incident.category, 1200.0)
        incident.resolution_time = base_resolution
        incident.resolved_at = self._current_time + RESPOND_DELAY + min_travel_time + base_resolution

        # Reward = negative response time (lower response time = higher reward)
        response_time = min_travel_time + RESPOND_DELAY
        return -response_time

    def _simulate_time_step(self, end_time: float) -> None:
        """Advance apparatus states forward to end_time.

        Each apparatus may transition through multiple states in a single call
        (e.g., EN_ROUTE → AT_INCIDENT → RETURNING → AVAILABLE) when the time
        gap is large enough.
        """
        resolved_ids: list[int] = []

        for apparatus in self._apparatus:
            # Loop to allow multi-step transitions within one time window
            changed = True
            while changed:
                changed = False

                if apparatus.status == ApparatusStatus.EN_ROUTE:
                    if apparatus.arrival_time is not None and apparatus.arrival_time <= end_time:
                        apparatus.status = ApparatusStatus.AT_INCIDENT
                        inc = self._active_incidents.get(apparatus.incident_id)
                        if inc is not None:
                            app_type = apparatus.apparatus_type
                            inc.arrived_apparatus[app_type] = (
                                inc.arrived_apparatus.get(app_type, 0) + 1
                            )
                        self._apparatus_events.append(ApparatusEvent(
                            time=apparatus.arrival_time,
                            apparatus_id=apparatus.id,
                            apparatus_type=apparatus.apparatus_type.value,
                            station_id=apparatus.station_id,
                            incident_id=apparatus.incident_id,
                            event="arrive",
                        ))
                        changed = True

                elif apparatus.status == ApparatusStatus.AT_INCIDENT:
                    inc = self._active_incidents.get(apparatus.incident_id)
                    if inc is not None and inc.resolved_at is not None and inc.resolved_at <= end_time:
                        apparatus.status = ApparatusStatus.RETURNING
                        return_travel = 0.0
                        for aid, tt in inc.dispatched_units:
                            if aid == apparatus.id:
                                return_travel = tt
                                break
                        apparatus.return_time = inc.resolved_at + return_travel
                        if inc.id not in resolved_ids:
                            resolved_ids.append(inc.id)
                        self._apparatus_events.append(ApparatusEvent(
                            time=inc.resolved_at,
                            apparatus_id=apparatus.id,
                            apparatus_type=apparatus.apparatus_type.value,
                            station_id=apparatus.station_id,
                            incident_id=apparatus.incident_id,
                            event="resolve",
                        ))
                        changed = True

                elif apparatus.status == ApparatusStatus.RETURNING:
                    if apparatus.return_time is not None and apparatus.return_time <= end_time:
                        self._apparatus_events.append(ApparatusEvent(
                            time=apparatus.return_time,
                            apparatus_id=apparatus.id,
                            apparatus_type=apparatus.apparatus_type.value,
                            station_id=apparatus.station_id,
                            incident_id=apparatus.incident_id,
                            event="return",
                        ))
                        apparatus.status = ApparatusStatus.AVAILABLE
                        apparatus.incident_id = None
                        apparatus.location = None
                        apparatus.dispatch_time = None
                        apparatus.arrival_time = None
                        apparatus.return_time = None
                        changed = True

        # Resolve incidents
        for inc_id in resolved_ids:
            inc = self._active_incidents.get(inc_id)
            if inc is not None and inc.status != IncidentStatus.RESOLVED:
                inc.status = IncidentStatus.RESOLVED
                self._metrics.resolved_incidents += 1
                self._resolved_incidents.append(inc)

        # Clean up fully resolved incidents where all apparatus have returned
        to_remove = []
        for inc_id, inc in self._active_incidents.items():
            if inc.status == IncidentStatus.RESOLVED:
                all_returned = all(
                    self._apparatus[aid].status == ApparatusStatus.AVAILABLE
                    for aid, _ in inc.dispatched_units
                )
                if all_returned:
                    to_remove.append(inc_id)

        # Also clean up non-dispatched incidents (no apparatus sent, nothing to wait for)
        for inc_id, inc in self._active_incidents.items():
            if not inc.dispatched_units and inc.status == IncidentStatus.REPORTED:
                to_remove.append(inc_id)

        for inc_id in to_remove:
            del self._active_incidents[inc_id]

    def drain(self, max_drain_time: float = 7200.0, step_size: float = 60.0) -> None:
        """Simulate forward until all active incidents are resolved and apparatus returned."""
        end_time = self._current_time + max_drain_time
        while self._current_time < end_time:
            if not self._active_incidents:
                all_available = all(
                    a.status == ApparatusStatus.AVAILABLE for a in self._apparatus
                )
                if all_available:
                    logger.info("Drain complete at t=%.0f", self._current_time)
                    break

            next_time = min(self._current_time + step_size, end_time)
            self._simulate_time_step(next_time)
            self._current_time = next_time

    @property
    def metrics(self) -> SimMetrics:
        return self._metrics

    @property
    def resolved_incidents(self) -> list[Incident]:
        return self._resolved_incidents

    @property
    def apparatus_events(self) -> list[ApparatusEvent]:
        return self._apparatus_events

    @property
    def step_records(self) -> list[StepRecord]:
        return self._step_records
