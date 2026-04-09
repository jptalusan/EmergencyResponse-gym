"""Unit tests for the empirical incident model."""

from datetime import datetime

from emergency_response.demand.empirical import EmpiricalIncidentModel
from emergency_response.models.core import (
    ApparatusType,
    Incident,
    IncidentLevel,
    IncidentStatus,
    IncidentType,
)


def _make_incidents(n: int, start_time: float = 1000.0, interval: float = 100.0) -> list[Incident]:
    return [
        Incident(
            id=i,
            lat=36.0 + i * 0.01,
            lon=-86.0,
            incident_type=IncidentType.EMS_RESCUE,
            level=IncidentLevel.MODERATE,
            datetime=datetime.fromtimestamp(start_time + i * interval),
            category="Nine",
            node=i % 5,
            report_time=start_time + i * interval,
        )
        for i in range(n)
    ]


class TestEmpiricalIncidentModel:
    def test_chronological_order(self):
        # Create out of order
        incidents = _make_incidents(5)
        incidents.reverse()
        model = EmpiricalIncidentModel(incidents)

        times = []
        while True:
            inc = model.get_next_incident()
            if inc is None:
                break
            times.append(inc.report_time)

        assert times == sorted(times)

    def test_total_incidents(self):
        model = EmpiricalIncidentModel(_make_incidents(10))
        assert model.total_incidents == 10

    def test_get_next_returns_none_when_exhausted(self):
        model = EmpiricalIncidentModel(_make_incidents(2))
        assert model.get_next_incident() is not None
        assert model.get_next_incident() is not None
        assert model.get_next_incident() is None

    def test_reset(self):
        model = EmpiricalIncidentModel(_make_incidents(3))
        model.get_next_incident()
        model.get_next_incident()
        model.reset()

        first = model.get_next_incident()
        assert first is not None
        assert first.report_time == 1000.0

    def test_peek_next_time(self):
        model = EmpiricalIncidentModel(_make_incidents(3))
        assert model.peek_next_time() == 1000.0
        model.get_next_incident()
        assert model.peek_next_time() == 1100.0

    def test_incident_gets_apparatus_requirements(self):
        model = EmpiricalIncidentModel(_make_incidents(1))
        inc = model.get_next_incident()
        assert ApparatusType.ENGINE in inc.required_apparatus
        assert ApparatusType.MEDIC in inc.required_apparatus

    def test_incident_has_fresh_state(self):
        model = EmpiricalIncidentModel(_make_incidents(1))
        inc = model.get_next_incident()
        assert inc.status == IncidentStatus.REPORTED
        assert inc.first_arrival_time is None
        assert len(inc.dispatched_units) == 0

    def test_two_runs_independent(self):
        model = EmpiricalIncidentModel(_make_incidents(3))

        # Run 1
        ids_1 = []
        while (inc := model.get_next_incident()) is not None:
            inc.status = IncidentStatus.RESOLVED  # mutate
            ids_1.append(inc.id)

        # Run 2
        model.reset()
        ids_2 = []
        while (inc := model.get_next_incident()) is not None:
            assert inc.status == IncidentStatus.REPORTED  # fresh state
            ids_2.append(inc.id)

        assert ids_1 == ids_2
