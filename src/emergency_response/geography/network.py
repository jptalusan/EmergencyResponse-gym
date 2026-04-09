"""NetworkGeography: TravelTimeProvider backed by OSMnx road network + precomputed travel times."""

from __future__ import annotations

import hashlib
import logging
import pickle
from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import shortest_path

from emergency_response.geography.h3_index import H3SpatialIndex
from emergency_response.models.core import Location, NodeLocation, PathLocation

logger = logging.getLogger(__name__)


class NetworkGeography:
    """Travel time provider using an OSMnx road network with cached all-pairs shortest paths."""

    def __init__(
        self,
        north: float,
        south: float,
        east: float,
        west: float,
        h3_resolution: int = 8,
        cache_dir: str = "cache",
        network_type: str = "drive",
    ):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        boundary_str = f"W{west}-S{south}-E{east}-N{north}-{network_type}"
        self._cache_hash = hashlib.md5(boundary_str.encode()).hexdigest()[:12]

        # Load or build graph
        graph_cache = self._cache_dir / f"graph_{self._cache_hash}.pickle"
        if graph_cache.exists():
            logger.info("Loading road network from cache: %s", graph_cache)
            with open(graph_cache, "rb") as f:
                self._graph = pickle.load(f)
        else:
            logger.info("Downloading road network from OSM for bbox N=%.4f S=%.4f E=%.4f W=%.4f", north, south, east, west)
            self._graph = ox.graph_from_bbox(bbox=(west, south, east, north), network_type=network_type)
            self._graph = ox.add_edge_speeds(self._graph, fallback=30)
            self._graph = ox.add_edge_travel_times(self._graph)
            logger.info("Caching road network to %s", graph_cache)
            with open(graph_cache, "wb") as f:
                pickle.dump(self._graph, f)

        # Build node index mappings
        osm_nodes = list(self._graph.nodes)
        self._osm_to_idx: dict[int, int] = {osm_id: idx for idx, osm_id in enumerate(osm_nodes)}
        self._idx_to_osm: dict[int, int] = {idx: osm_id for idx, osm_id in enumerate(osm_nodes)}
        self._num_nodes = len(osm_nodes)

        self._node_coords: list[tuple[float, float]] = [
            (self._graph.nodes[osm_id]["y"], self._graph.nodes[osm_id]["x"]) for osm_id in osm_nodes
        ]

        # H3 spatial index
        self._h3_index = H3SpatialIndex(h3_resolution, self._node_coords)

        # Load or compute travel time matrix
        matrix_cache = self._cache_dir / f"travel_times_{self._cache_hash}.npz"
        if matrix_cache.exists():
            logger.info("Loading travel time matrix from cache: %s", matrix_cache)
            data = np.load(matrix_cache)
            self._travel_time = data["travel_time"]
        else:
            logger.info("Computing all-pairs shortest path matrix for %d nodes...", self._num_nodes)
            self._travel_time = self._compute_travel_time_matrix()
            logger.info("Caching travel time matrix to %s", matrix_cache)
            np.savez_compressed(matrix_cache, travel_time=self._travel_time)

        logger.info("NetworkGeography ready: %d nodes", self._num_nodes)

    def _compute_travel_time_matrix(self) -> np.ndarray:
        rows, cols, weights = [], [], []
        for u, v, data in self._graph.edges(data=True):
            u_idx = self._osm_to_idx[u]
            v_idx = self._osm_to_idx[v]
            tt = data.get("travel_time", data.get("length", 1.0) / 10.0)
            rows.append(u_idx)
            cols.append(v_idx)
            weights.append(tt)

        sparse = csr_matrix((weights, (rows, cols)), shape=(self._num_nodes, self._num_nodes))
        dist_matrix = shortest_path(sparse, directed=True)
        dist_matrix[np.isinf(dist_matrix)] = 1e9
        return dist_matrix.astype(np.float32)

    # --- TravelTimeProvider interface ---

    def drive_time(self, origin: Location, destination: Location) -> float:
        assert isinstance(destination, NodeLocation)
        if isinstance(origin, NodeLocation):
            return float(self._travel_time[origin.node, destination.node])
        elif isinstance(origin, PathLocation):
            next_node = origin.path_nodes[origin.next_index]
            return origin.remaining_time + float(self._travel_time[next_node, destination.node])
        raise TypeError(f"Unsupported origin type: {type(origin)}")

    def drive_time_matrix(self, origins: list[int], destinations: list[int]) -> np.ndarray:
        return self._travel_time[np.ix_(origins, destinations)]

    def intermediate_location(self, origin: Location, destination: Location, time_budget: float) -> Location:
        assert isinstance(destination, NodeLocation)

        if isinstance(origin, NodeLocation):
            total_time = float(self._travel_time[origin.node, destination.node])
            if time_budget >= total_time:
                return destination

            origin_osm = self._idx_to_osm[origin.node]
            dest_osm = self._idx_to_osm[destination.node]
            path_osm = nx.shortest_path(self._graph, source=origin_osm, target=dest_osm, weight="travel_time")
            path_nodes = tuple(self._osm_to_idx[osm_id] for osm_id in path_osm)

            i = 1
            drive_time_to_i = float(self._travel_time[origin.node, path_nodes[i]])
            while drive_time_to_i < time_budget and i < len(path_nodes) - 1:
                i += 1
                drive_time_to_i = float(self._travel_time[origin.node, path_nodes[i]])

            drive_time_to_prev = float(self._travel_time[origin.node, path_nodes[i - 1]])

            return PathLocation(
                path_nodes=path_nodes,
                next_index=i,
                elapsed_time=time_budget - drive_time_to_prev,
                remaining_time=drive_time_to_i - time_budget,
            )

        elif isinstance(origin, PathLocation):
            if time_budget < origin.remaining_time:
                return PathLocation(
                    path_nodes=origin.path_nodes,
                    next_index=origin.next_index,
                    elapsed_time=origin.elapsed_time + time_budget,
                    remaining_time=origin.remaining_time - time_budget,
                )
            else:
                remaining_budget = time_budget - origin.remaining_time
                next_node = origin.path_nodes[origin.next_index]
                return self.intermediate_location(NodeLocation(next_node), destination, remaining_budget)

        raise TypeError(f"Unsupported origin type: {type(origin)}")

    def nearest_node(self, lat: float, lon: float) -> int:
        return self._h3_index.nearest_node(lat, lon)

    def node_coords(self, node: int) -> tuple[float, float]:
        return self._node_coords[node]

    @property
    def num_nodes(self) -> int:
        return self._num_nodes

    @property
    def h3_index(self) -> H3SpatialIndex:
        return self._h3_index
