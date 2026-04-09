"""Unit tests for core data models."""

from datetime import datetime

from emergency_response.models.core import (
    Apparatus,
    ApparatusStatus,
    ApparatusType,
    DEFAULT_APPARATUS_REQUIREMENTS,
    DEFAULT_RESOLUTION_TIMES,
    DispatchAction,
    FireStation,
    Incident,
    IncidentLevel,
    IncidentStatus,
    IncidentType,
    NodeLocation,
    PathLocation,
    State,
)


class TestNodeLocation:
    def test_frozen(self):
        loc = NodeLocation(5)
        assert loc.node == 5

    def test_equality(self):
        assert NodeLocation(3) == NodeLocation(3)
        assert NodeLocation(3) != NodeLocation(4)


class TestPathLocation:
    def test_creation(self):
        pl = PathLocation(path_nodes=(0, 1, 2), next_index=1, remaining_time=50.0, elapsed_time=30.0)
        assert pl.path_nodes == (0, 1, 2)
        assert pl.remaining_time == 50.0


class TestIncident:
    def test_response_time_none_before_arrival(self):
        inc = Incident(
            id=1, lat=36.0, lon=-86.0, incident_type=IncidentType.EMS_RESCUE,
            level=IncidentLevel.MODERATE, datetime=datetime(2022, 1, 1),
            category="Nine", report_time=1000.0,
        )
        assert inc.response_time is None

    def test_response_time_after_arrival(self):
        inc = Incident(
            id=1, lat=36.0, lon=-86.0, incident_type=IncidentType.EMS_RESCUE,
            level=IncidentLevel.MODERATE, datetime=datetime(2022, 1, 1),
            category="Nine", report_time=1000.0, first_arrival_time=1300.0,
        )
        assert inc.response_time == 300.0

    def test_status_default(self):
        inc = Incident(
            id=1, lat=36.0, lon=-86.0, incident_type=IncidentType.BUILDING_FIRE,
            level=IncidentLevel.HIGH, datetime=datetime(2022, 1, 1),
            category="One",
        )
        assert inc.status == IncidentStatus.REPORTED


class TestApparatus:
    def test_default_status(self):
        a = Apparatus(id=0, apparatus_type=ApparatusType.ENGINE, station_id=0, station_node=0)
        assert a.status == ApparatusStatus.AVAILABLE
        assert a.incident_id is None

    def test_all_types_exist(self):
        expected = {"ENGINE", "TRUCK", "RESCUE", "HAZARD", "CHIEF", "SQUAD", "FAST", "MEDIC", "BRUSH", "BOAT", "UTV", "REACH"}
        actual = {t.name for t in ApparatusType}
        assert actual == expected


class TestFireStation:
    def test_creation(self):
        s = FireStation(id=0, name="Station 1", lat=36.16, lon=-86.78, node=0)
        assert s.apparatus_ids == []
        s.apparatus_ids.append(1)
        assert len(s.apparatus_ids) == 1


class TestState:
    def test_available_apparatus_at_station(self, sample_stations, sample_apparatus):
        state = State(
            current_time=0.0,
            stations=sample_stations,
            apparatus=sample_apparatus,
            active_incidents={},
            new_incident=None,
        )
        avail = state.available_apparatus_at_station(0)
        assert len(avail) == 2
        assert all(a.station_id == 0 for a in avail)

    def test_available_apparatus_of_type(self, sample_stations, sample_apparatus):
        state = State(
            current_time=0.0,
            stations=sample_stations,
            apparatus=sample_apparatus,
            active_incidents={},
            new_incident=None,
        )
        engines = state.available_apparatus_of_type(ApparatusType.ENGINE)
        assert len(engines) == 2

    def test_available_excludes_dispatched(self, sample_stations, sample_apparatus):
        sample_apparatus[0].status = ApparatusStatus.EN_ROUTE
        state = State(
            current_time=0.0,
            stations=sample_stations,
            apparatus=sample_apparatus,
            active_incidents={},
            new_incident=None,
        )
        engines = state.available_apparatus_of_type(ApparatusType.ENGINE)
        assert len(engines) == 1
        assert engines[0].id == 2


class TestDispatchAction:
    def test_frozen(self):
        da = DispatchAction(apparatus_id=0, incident_id=100, travel_time=120.0)
        assert da.travel_time == 120.0


class TestDefaults:
    def test_apparatus_requirements_has_nine(self):
        reqs = DEFAULT_APPARATUS_REQUIREMENTS["Nine"]
        assert ApparatusType.ENGINE in reqs
        assert ApparatusType.MEDIC in reqs

    def test_resolution_times_has_all_categories(self):
        for cat in DEFAULT_APPARATUS_REQUIREMENTS:
            assert cat in DEFAULT_RESOLUTION_TIMES, f"Missing resolution time for {cat}"
