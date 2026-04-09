"""H3 hexagonal spatial index for fast nearest-node queries."""

from __future__ import annotations

from collections import defaultdict

import h3
import numpy as np


class H3SpatialIndex:
    """Maps graph nodes to H3 hexagons for spatial lookups."""

    def __init__(self, resolution: int, node_coords: list[tuple[float, float]]):
        self.resolution = resolution
        self._node_coords = node_coords
        self._node_coords_array = np.array(node_coords)

        self.node_to_hex: dict[int, str] = {}
        self.hex_to_nodes: dict[str, list[int]] = defaultdict(list)

        for node_idx, (lat, lon) in enumerate(node_coords):
            h = h3.latlng_to_cell(lat, lon, resolution)
            self.node_to_hex[node_idx] = h
            self.hex_to_nodes[h].append(node_idx)

    def nearest_node(self, lat: float, lon: float) -> int:
        """Find the nearest graph node to a lat/lon point using H3 spatial narrowing."""
        target_hex = h3.latlng_to_cell(lat, lon, self.resolution)

        candidate_hexes = h3.grid_disk(target_hex, 1)
        candidates: list[int] = []
        for h in candidate_hexes:
            candidates.extend(self.hex_to_nodes.get(h, []))

        if not candidates:
            candidate_hexes = h3.grid_disk(target_hex, 2)
            for h in candidate_hexes:
                candidates.extend(self.hex_to_nodes.get(h, []))

        if not candidates:
            candidates = list(range(len(self._node_coords)))

        target = np.array([lat, lon])
        coords = self._node_coords_array[candidates]
        dists = np.sum((coords - target) ** 2, axis=1)
        best_idx = np.argmin(dists)
        return candidates[best_idx]

    def nodes_in_hex(self, hex_id: str) -> list[int]:
        return self.hex_to_nodes.get(hex_id, [])

    def nodes_in_disk(self, center_hex: str, k: int) -> list[int]:
        hexes = h3.grid_disk(center_hex, k)
        result: list[int] = []
        for h in hexes:
            result.extend(self.hex_to_nodes.get(h, []))
        return result
