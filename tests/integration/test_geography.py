"""Integration tests for geography: NetworkGeography with a real small graph."""

import numpy as np
import pytest
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import shortest_path

from emergency_response.geography.h3_index import H3SpatialIndex
from emergency_response.models.core import NodeLocation


class TestTravelTimeMatrixFromGraph:
    """Test that a manually-built graph produces correct shortest path distances."""

    @pytest.fixture
    def travel_time_matrix(self, simple_graph):
        """Compute travel time matrix from the simple_graph fixture."""
        nodes = list(simple_graph.nodes)
        n = len(nodes)
        node_to_idx = {nid: i for i, nid in enumerate(nodes)}

        rows, cols, weights = [], [], []
        for u, v, data in simple_graph.edges(data=True):
            rows.append(node_to_idx[u])
            cols.append(node_to_idx[v])
            weights.append(data["travel_time"])

        sparse = csr_matrix((weights, (rows, cols)), shape=(n, n))
        matrix = shortest_path(sparse, directed=True)
        matrix[np.isinf(matrix)] = 1e9
        return matrix.astype(np.float32)

    def test_self_distance_zero(self, travel_time_matrix):
        for i in range(5):
            assert travel_time_matrix[i, i] == 0.0

    def test_direct_edge(self, travel_time_matrix):
        # 0 -> 1 = 100s direct
        assert travel_time_matrix[0, 1] == 100.0

    def test_shortest_path_via_intermediate(self, travel_time_matrix):
        # 0 -> 2: via 1 = 200s, via 3 = 150+50=200s (same)
        assert travel_time_matrix[0, 2] == 200.0

    def test_0_to_4(self, travel_time_matrix):
        # 0 -> 4: 0->3 (150) + 3->4 (80) = 230
        assert travel_time_matrix[0, 4] == 230.0

    def test_3_to_2(self, travel_time_matrix):
        # 3 -> 2 = 50 direct
        assert travel_time_matrix[3, 2] == 50.0

    def test_matrix_subselection(self, travel_time_matrix):
        """Test drive_time_matrix-style subselection."""
        origins = [0, 3]
        destinations = [2]
        sub = travel_time_matrix[np.ix_(origins, destinations)]
        assert sub.shape == (2, 1)
        assert sub[0, 0] == 200.0  # station 0 -> incident at 2
        assert sub[1, 0] == 50.0   # station 3 -> incident at 2


class TestH3NearestNodeIntegration:
    def test_nearest_node_returns_closest(self, node_coords):
        index = H3SpatialIndex(resolution=8, node_coords=node_coords)

        # Query near node 0 (36.16, -86.78)
        result = index.nearest_node(36.16, -86.78)
        assert result == 0

        # Query near node 4 (36.14, -86.74)
        result = index.nearest_node(36.14, -86.74)
        assert result == 4

    def test_midpoint_picks_nearest(self, node_coords):
        index = H3SpatialIndex(resolution=8, node_coords=node_coords)

        # Midpoint between node 1 (36.16, -86.76) and node 3 (36.14, -86.76)
        result = index.nearest_node(36.15, -86.76)
        assert result in (1, 3)  # either is valid, they're equidistant in lon
