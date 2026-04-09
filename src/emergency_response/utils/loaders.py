"""Data loaders for incidents, stations, and bounds."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from shapely.geometry import Point, shape

from emergency_response.geography.base import TravelTimeProvider
from emergency_response.models.core import (
    Apparatus,
    ApparatusType,
    FireStation,
    Incident,
    IncidentLevel,
    IncidentType,
)
from emergency_response.utils.cache import load_or_compute

logger = logging.getLogger(__name__)

# Column name -> ApparatusType mapping for stations CSV
_APPARATUS_COLUMNS: dict[str, ApparatusType] = {
    "Engine_ID": ApparatusType.ENGINE,
    "Truck": ApparatusType.TRUCK,
    "Rescue": ApparatusType.RESCUE,
    "Hazard": ApparatusType.HAZARD,
    "Squad": ApparatusType.SQUAD,
    "FAST": ApparatusType.FAST,
    "Medic": ApparatusType.MEDIC,
    "Brush": ApparatusType.BRUSH,
    "Boat": ApparatusType.BOAT,
    "UTV": ApparatusType.UTV,
    "REACH": ApparatusType.REACH,
    "Chief": ApparatusType.CHIEF,
}

_INCIDENT_TYPE_MAP: dict[str, IncidentType] = {
    "Building Fire": IncidentType.BUILDING_FIRE,
    "EMS & Rescue": IncidentType.EMS_RESCUE,
    "Vehicle Accident": IncidentType.VEHICLE_ACCIDENT,
    "Gas Leak": IncidentType.GAS_LEAK,
    "Service Call": IncidentType.SERVICE_CALL,
    "Hazmat": IncidentType.HAZMAT,
    "Alarm": IncidentType.ALARM,
}

_INCIDENT_LEVEL_MAP: dict[str, IncidentLevel] = {
    "Low": IncidentLevel.LOW,
    "Moderate": IncidentLevel.MODERATE,
    "High": IncidentLevel.HIGH,
    "Critical": IncidentLevel.CRITICAL,
}


def load_stations(
    csv_path: str | Path,
    geography: TravelTimeProvider,
    cache_dir: str | Path = "cache",
) -> tuple[list[FireStation], list[Apparatus]]:
    """Load fire stations and their apparatus from CSV, snapping to nearest graph nodes.

    Returns (stations, apparatus) with all apparatus IDs cross-referenced.
    """
    cache_path = Path(cache_dir) / "stations_snapped.pkl"

    def _build() -> tuple[list[FireStation], list[Apparatus]]:
        df = pd.read_csv(csv_path)
        stations: list[FireStation] = []
        all_apparatus: list[Apparatus] = []
        apparatus_id = 0

        for _, row in df.iterrows():
            station_id = int(row["StationID"])
            lat, lon = float(row["lat"]), float(row["lon"])
            node = geography.nearest_node(lat, lon)

            station = FireStation(
                id=station_id,
                name=str(row["Stations"]),
                lat=lat,
                lon=lon,
                node=node,
            )

            for col_name, app_type in _APPARATUS_COLUMNS.items():
                count = row.get(col_name, 0)
                if pd.isna(count) or count == "" or count == 0:
                    continue
                count = int(count)
                for _ in range(count):
                    apparatus = Apparatus(
                        id=apparatus_id,
                        apparatus_type=app_type,
                        station_id=station_id,
                        station_node=node,
                    )
                    station.apparatus_ids.append(apparatus_id)
                    all_apparatus.append(apparatus)
                    apparatus_id += 1

            stations.append(station)

        logger.info("Loaded %d stations with %d apparatus", len(stations), len(all_apparatus))
        return stations, all_apparatus

    return load_or_compute(cache_path, _build)


def load_incidents(
    csv_path: str | Path,
    geography: TravelTimeProvider | None = None,
    bounds_polygon=None,
    cache_dir: str | Path = "cache",
) -> list[Incident]:
    """Load incidents from CSV, optionally snapping to graph and filtering by bounds.

    Incidents are returned sorted chronologically.
    """
    cache_name = "incidents_snapped.pkl" if geography is not None else "incidents_raw.pkl"
    cache_path = Path(cache_dir) / cache_name

    def _build() -> list[Incident]:
        df = pd.read_csv(csv_path)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)

        incidents: list[Incident] = []
        skipped = 0

        for _, row in df.iterrows():
            lat, lon = float(row["lat"]), float(row["lon"])

            # Filter by bounds
            if bounds_polygon is not None:
                if not bounds_polygon.contains(Point(lon, lat)):
                    skipped += 1
                    continue

            inc_type = _INCIDENT_TYPE_MAP.get(row["incident_type"], IncidentType.OTHER)
            inc_level = _INCIDENT_LEVEL_MAP.get(row["incident_level"], IncidentLevel.MODERATE)

            dt = row["datetime"].to_pydatetime()
            node = geography.nearest_node(lat, lon) if geography is not None else None

            incident = Incident(
                id=int(row["incident_id"]),
                lat=lat,
                lon=lon,
                incident_type=inc_type,
                level=inc_level,
                datetime=dt,
                category=str(row["category"]),
                node=node,
                report_time=dt.timestamp(),
            )
            incidents.append(incident)

        if skipped > 0:
            logger.info("Filtered out %d incidents outside bounds", skipped)
        logger.info("Loaded %d incidents", len(incidents))
        return incidents

    return load_or_compute(cache_path, _build)


def load_bounds(geojson_path: str | Path):
    """Load service area boundary from GeoJSON. Returns a shapely Polygon or None."""
    path = Path(geojson_path)
    if not path.exists():
        logger.warning("Bounds GeoJSON not found: %s", path)
        return None

    with open(path) as f:
        data = json.load(f)

    features = data.get("features", [])
    if not features:
        return None

    return shape(features[0]["geometry"])
