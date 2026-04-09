"""Unit tests for H3 spatial index."""

import pytest

from emergency_response.geography.h3_index import H3SpatialIndex


class TestH3SpatialIndex:
    @pytest.fixture
    def h3_index(self, node_coords):
        return H3SpatialIndex(resolution=8, node_coords=node_coords)

    def test_nearest_node_exact(self, h3_index, node_coords):
        # Query at exact node coordinates should return that node
        for i, (lat, lon) in enumerate(node_coords):
            assert h3_index.nearest_node(lat, lon) == i

    def test_nearest_node_close(self, h3_index):
        # Slightly offset from node 0 (36.16, -86.78)
        result = h3_index.nearest_node(36.161, -86.781)
        assert result == 0

    def test_nodes_in_hex(self, h3_index, node_coords):
        import h3

        hex_id = h3.latlng_to_cell(node_coords[0][0], node_coords[0][1], 8)
        nodes = h3_index.nodes_in_hex(hex_id)
        assert 0 in nodes

    def test_nodes_in_disk(self, h3_index, node_coords):
        import h3

        center = h3.latlng_to_cell(node_coords[0][0], node_coords[0][1], 8)
        nodes = h3_index.nodes_in_disk(center, k=5)
        # Should include all 5 nodes (they're close together)
        assert len(nodes) >= 1

    def test_empty_hex(self, h3_index):
        # A hex far away should have no nodes
        nodes = h3_index.nodes_in_hex("8000000000fffff")
        assert len(nodes) == 0
