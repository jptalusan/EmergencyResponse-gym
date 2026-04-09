"""Unit tests for data loaders."""

import json
import tempfile
from pathlib import Path

import pytest

from emergency_response.utils.loaders import load_bounds


class TestLoadBounds:
    def test_load_valid_geojson(self, tmp_path):
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-87.0, 35.9],
                        [-86.5, 35.9],
                        [-86.5, 36.4],
                        [-87.0, 36.4],
                        [-87.0, 35.9],
                    ]]
                }
            }]
        }
        path = tmp_path / "bounds.geojson"
        path.write_text(json.dumps(geojson))

        polygon = load_bounds(path)
        assert polygon is not None
        assert polygon.contains(
            __import__("shapely.geometry", fromlist=["Point"]).Point(-86.75, 36.15)
        )

    def test_returns_none_for_missing_file(self, tmp_path):
        polygon = load_bounds(tmp_path / "nonexistent.geojson")
        assert polygon is None

    def test_returns_none_for_empty_features(self, tmp_path):
        geojson = {"type": "FeatureCollection", "features": []}
        path = tmp_path / "empty.geojson"
        path.write_text(json.dumps(geojson))

        polygon = load_bounds(path)
        assert polygon is None
