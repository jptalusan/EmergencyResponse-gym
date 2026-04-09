"""Integration tests for coordinate snapping (stations/incidents to graph nodes)."""

import csv
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from emergency_response.utils.loaders import load_incidents, load_stations


class TestStationSnapping:
    def test_load_and_snap_stations(self, mock_geography, tmp_path):
        # Write a minimal stations CSV
        csv_path = tmp_path / "stations.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "StationID", "Stations", "lat", "lon", "Nashville Fire Stations",
                "Engine_ID", "Truck", "Rescue", "Hazard", "Squad", "FAST",
                "Medic", "Brush", "Boat", "UTV", "REACH", "Chief",
            ])
            writer.writerow([0, "Station 1", 36.16, -86.78, "Addr1", 1, "", 1, "", "", "", "", "", "", "", "", ""])
            writer.writerow([1, "Station 2", 36.14, -86.76, "Addr2", 1, 1, "", "", "", "", 1, "", "", "", "", ""])

        cache_dir = tmp_path / "cache"
        stations, apparatus = load_stations(csv_path, mock_geography, cache_dir=str(cache_dir))

        assert len(stations) == 2
        # Station 1 near (36.16, -86.78) -> node 0
        assert stations[0].node == 0
        # Station 2 near (36.14, -86.76) -> node 3
        assert stations[1].node == 3

        # Station 1: 1 engine + 1 rescue = 2 apparatus
        assert len(stations[0].apparatus_ids) == 2
        # Station 2: 1 engine + 1 truck + 1 medic = 3 apparatus
        assert len(stations[1].apparatus_ids) == 3
        assert len(apparatus) == 5


class TestIncidentSnapping:
    def test_load_and_snap_incidents(self, mock_geography, tmp_path):
        csv_path = tmp_path / "incidents.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["incident_id", "lat", "lon", "incident_type", "incident_level", "datetime", "category"])
            writer.writerow([1, 36.16, -86.74, "EMS & Rescue", "Moderate", "2022-01-01 00:07:25", "Nine"])
            writer.writerow([2, 36.14, -86.76, "Building Fire", "High", "2022-01-01 01:00:00", "One"])

        cache_dir = tmp_path / "cache"
        incidents = load_incidents(csv_path, geography=mock_geography, cache_dir=str(cache_dir))

        assert len(incidents) == 2
        # Sorted chronologically
        assert incidents[0].id == 1
        assert incidents[1].id == 2
        # Snapped to nearest nodes
        assert incidents[0].node == 2  # (36.16, -86.74) -> node 2
        assert incidents[1].node == 3  # (36.14, -86.76) -> node 3

    def test_bounds_filtering(self, mock_geography, tmp_path):
        from shapely.geometry import Polygon

        csv_path = tmp_path / "incidents.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["incident_id", "lat", "lon", "incident_type", "incident_level", "datetime", "category"])
            writer.writerow([1, 36.16, -86.74, "EMS & Rescue", "Moderate", "2022-01-01 00:00:00", "Nine"])
            writer.writerow([2, 40.00, -90.00, "EMS & Rescue", "Moderate", "2022-01-01 01:00:00", "Nine"])

        bounds = Polygon([(-87.0, 35.9), (-86.5, 35.9), (-86.5, 36.4), (-87.0, 36.4)])

        cache_dir = tmp_path / "cache"
        incidents = load_incidents(
            csv_path, geography=mock_geography,
            bounds_polygon=bounds, cache_dir=str(cache_dir),
        )

        assert len(incidents) == 1
        assert incidents[0].id == 1
