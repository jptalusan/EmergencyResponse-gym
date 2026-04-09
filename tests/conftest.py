"""Shared test fixtures for the emergency response gym test suite."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import networkx as nx
import numpy as np
import pytest

from emergency_response.models.core import (
    Apparatus,
    ApparatusType,
    FireStation,
    Incident,
    IncidentLevel,
    IncidentStatus,
    IncidentType,
    NodeLocation,
    PathLocation,
)


@pytest.fixture
def simple_graph() -> nx.DiGraph:
    """A small 5-node directed graph with known travel times.

    Layout (travel_time on edges):
        0 --100s--> 1 --100s--> 2
        |                       ^
        +---150s--> 3 --50s-----+
                    |
                    +---80s---> 4
    """
    G = nx.DiGraph()
    nodes = {
        0: {"x": -86.78, "y": 36.16},
        1: {"x": -86.76, "y": 36.16},
        2: {"x": -86.74, "y": 36.16},
        3: {"x": -86.76, "y": 36.14},
        4: {"x": -86.74, "y": 36.14},
    }
    for node_id, attrs in nodes.items():
        G.add_node(node_id, **attrs)

    edges = [
        (0, 1, 100.0),
        (1, 0, 100.0),
        (1, 2, 100.0),
        (2, 1, 100.0),
        (0, 3, 150.0),
        (3, 0, 150.0),
        (3, 2, 50.0),
        (2, 3, 50.0),
        (3, 4, 80.0),
        (4, 3, 80.0),
    ]
    for u, v, tt in edges:
        G.add_edge(u, v, travel_time=tt, length=tt * 10)

    return G


@pytest.fixture
def node_locations() -> list[NodeLocation]:
    return [NodeLocation(i) for i in range(5)]


@pytest.fixture
def node_coords() -> list[tuple[float, float]]:
    """(lat, lon) for the 5-node graph."""
    return [
        (36.16, -86.78),
        (36.16, -86.76),
        (36.16, -86.74),
        (36.14, -86.76),
        (36.14, -86.74),
    ]


@pytest.fixture
def mock_geography(node_coords):
    """Mock geography with 5 nodes. Uses a precomputed travel time matrix."""
    geo = MagicMock()
    geo.num_nodes = 5

    # Precomputed all-pairs shortest paths for the 5-node graph
    # 0->1: 100, 0->2: 200 (via 3: 150+50=200, via 1: 100+100=200), 0->3: 150, 0->4: 230
    tt_matrix = np.array([
        [0.0,   100.0, 200.0, 150.0, 230.0],
        [100.0, 0.0,   100.0, 150.0, 230.0],
        [200.0, 100.0, 0.0,   50.0,  130.0],
        [150.0, 150.0, 50.0,  0.0,   80.0],
        [230.0, 230.0, 130.0, 80.0,  0.0],
    ], dtype=np.float32)

    def drive_time(origin, dest):
        if isinstance(origin, NodeLocation) and isinstance(dest, NodeLocation):
            return float(tt_matrix[origin.node, dest.node])
        if isinstance(origin, PathLocation):
            next_node = origin.path_nodes[origin.next_index]
            return origin.remaining_time + float(tt_matrix[next_node, dest.node])
        return 100.0

    def drive_time_matrix(origins, destinations):
        return tt_matrix[np.ix_(origins, destinations)]

    def intermediate_location(origin, dest, budget):
        if isinstance(origin, NodeLocation):
            return PathLocation(
                path_nodes=(origin.node, dest.node if isinstance(dest, NodeLocation) else 0),
                next_index=1,
                elapsed_time=budget,
                remaining_time=max(0, 100.0 - budget),
            )
        return origin

    def nearest_node(lat, lon):
        coords = np.array(node_coords)
        dists = np.sum((coords - np.array([lat, lon])) ** 2, axis=1)
        return int(np.argmin(dists))

    def _node_coords(node):
        return node_coords[node]

    geo.drive_time = MagicMock(side_effect=drive_time)
    geo.drive_time_matrix = MagicMock(side_effect=drive_time_matrix)
    geo.intermediate_location = MagicMock(side_effect=intermediate_location)
    geo.nearest_node = MagicMock(side_effect=nearest_node)
    geo.node_coords = MagicMock(side_effect=_node_coords)

    return geo


@pytest.fixture
def sample_stations() -> list[FireStation]:
    """Two fire stations at nodes 0 and 3."""
    return [
        FireStation(id=0, name="Station 1", lat=36.16, lon=-86.78, node=0, apparatus_ids=[0, 1]),
        FireStation(id=1, name="Station 2", lat=36.14, lon=-86.76, node=3, apparatus_ids=[2, 3, 4]),
    ]


@pytest.fixture
def sample_apparatus() -> list[Apparatus]:
    """5 apparatus across two stations."""
    return [
        Apparatus(id=0, apparatus_type=ApparatusType.ENGINE, station_id=0, station_node=0),
        Apparatus(id=1, apparatus_type=ApparatusType.MEDIC, station_id=0, station_node=0),
        Apparatus(id=2, apparatus_type=ApparatusType.ENGINE, station_id=1, station_node=3),
        Apparatus(id=3, apparatus_type=ApparatusType.TRUCK, station_id=1, station_node=3),
        Apparatus(id=4, apparatus_type=ApparatusType.RESCUE, station_id=1, station_node=3),
    ]


@pytest.fixture
def sample_incident() -> Incident:
    """An incident at node 2 requiring 1 engine + 1 medic."""
    return Incident(
        id=1001,
        lat=36.16,
        lon=-86.74,
        incident_type=IncidentType.EMS_RESCUE,
        level=IncidentLevel.MODERATE,
        datetime=datetime(2022, 1, 1, 0, 7, 25),
        category="Nine",
        node=2,
        report_time=1640995645.0,
        required_apparatus={ApparatusType.ENGINE: 1, ApparatusType.MEDIC: 1},
    )


def make_incident(
    incident_id: int,
    node: int,
    report_time: float,
    category: str = "Nine",
) -> Incident:
    """Helper to create incidents with minimal boilerplate."""
    return Incident(
        id=incident_id,
        lat=36.16,
        lon=-86.74,
        incident_type=IncidentType.EMS_RESCUE,
        level=IncidentLevel.MODERATE,
        datetime=datetime.fromtimestamp(report_time),
        category=category,
        node=node,
        report_time=report_time,
        required_apparatus={ApparatusType.ENGINE: 1, ApparatusType.MEDIC: 1},
    )
