"""Metrics and reporting for emergency response simulation."""

from __future__ import annotations

import csv
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from emergency_response.models.core import Incident

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IncidentRecord:
    """Flat record for one incident, suitable for CSV export."""

    incident_id: int
    lat: float
    lon: float
    incident_type: str
    level: str
    category: str
    report_time: float
    first_arrival_time: float | None
    response_time: float | None
    resolved_at: float | None
    resolution_duration: float | None
    num_apparatus_dispatched: int
    status: str


def incident_to_record(inc: Incident) -> IncidentRecord:
    resolution_duration = None
    if inc.resolved_at is not None and inc.first_arrival_time is not None:
        resolution_duration = inc.resolved_at - inc.first_arrival_time

    return IncidentRecord(
        incident_id=inc.id,
        lat=inc.lat,
        lon=inc.lon,
        incident_type=inc.incident_type.value,
        level=inc.level.value,
        category=inc.category,
        report_time=inc.report_time,
        first_arrival_time=inc.first_arrival_time,
        response_time=inc.response_time,
        resolved_at=inc.resolved_at,
        resolution_duration=resolution_duration,
        num_apparatus_dispatched=len(inc.dispatched_units),
        status=inc.status.name,
    )


def build_records(incidents: list[Incident]) -> list[IncidentRecord]:
    return [incident_to_record(inc) for inc in incidents]


def print_summary(records: list[IncidentRecord]) -> None:
    if not records:
        logger.info("No incidents to summarize.")
        return

    response_times = [r.response_time for r in records if r.response_time is not None]
    n_total = len(records)
    n_responded = len(response_times)
    n_resolved = sum(1 for r in records if r.status == "RESOLVED")

    logger.info("=" * 60)
    logger.info("SIMULATION SUMMARY")
    logger.info("=" * 60)
    logger.info("Total incidents:     %d", n_total)
    logger.info("Responded:           %d (%.1f%%)", n_responded, 100 * n_responded / max(n_total, 1))
    logger.info("Resolved:            %d (%.1f%%)", n_resolved, 100 * n_resolved / max(n_total, 1))

    if response_times:
        import numpy as np

        rt = np.array(response_times)
        logger.info("Response time (s):   mean=%.0f  median=%.0f  p90=%.0f  min=%.0f  max=%.0f",
                     np.mean(rt), np.median(rt), np.percentile(rt, 90), np.min(rt), np.max(rt))
    logger.info("=" * 60)


def export_csv(records: list[IncidentRecord], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(IncidentRecord.__dataclass_fields__.keys()))
        writer.writeheader()
        for r in records:
            writer.writerow(asdict(r))

    logger.info("Exported %d incident records to %s", len(records), path)


def export_apparatus_events(events, output_path: str | Path) -> None:
    """Export apparatus event log to CSV."""
    from emergency_response.env.emergency_env import ApparatusEvent

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["time", "apparatus_id", "apparatus_type", "station_id", "incident_id", "event", "travel_time"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for e in events:
            writer.writerow(asdict(e))

    logger.info("Exported %d apparatus events to %s", len(events), path)


def export_step_records(records, output_path: str | Path) -> None:
    """Export per-step reward trace to CSV."""
    from emergency_response.env.emergency_env import StepRecord

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "step", "time", "incident_id", "category", "reward",
        "response_time", "num_dispatched", "active_incidents", "available_apparatus",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(asdict(r))

    logger.info("Exported %d step records to %s", len(records), path)
