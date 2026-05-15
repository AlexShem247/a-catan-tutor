from collections import defaultdict
from random import Random
from typing import Dict, List, Optional, Set, Tuple

from game.Edge import Edge, EdgeDirection
from game.HexTile import HexTile, HexType
from game.Player import Player
from game.Vertex import Building, Port, Vertex, VertexDirection

PRODUCTION_NUMBERS = [2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12]

PORT_TYPES = [
    Port.THREE_TO_ONE, Port.THREE_TO_ONE, Port.THREE_TO_ONE, Port.THREE_TO_ONE, Port.BRICK, Port.WOOD, Port.SHEEP,
    Port.WHEAT, Port.ORE
]


class Board:
    # Catan tile coordinates for 3-4-5-4-3 layout
    HEX_COORDS: List[Tuple[int, int]] = [(0, 0), (1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (2, 1), (-2, 2), (-1, 2),
                                         (0, 2), (1, 2), (2, 2), (-2, 3), (-1, 3), (0, 3), (1, 3), (-2, 4), (-1, 4),
                                         (0, 4)]
    MIN_R: int = 0
    MAX_R: int = 4

    def __init__(self, rng: Random):
        self.rng = rng
        self.hexes: List[HexTile] = []
        self.vertices: List[Vertex] = []
        self.edges: List[Edge] = []
        self.port_vertices: List[Tuple[Port, Vertex, Vertex]] = []
        self.hex_map: Dict[Tuple[int, int], HexTile] = {}
        self.production_to_hex: Dict[int, List[HexTile]] = defaultdict(list)
        self.vertex_map: Dict[Tuple[int, int, VertexDirection], Vertex] = {}
        self.edge_map: Dict[Tuple[int, int, EdgeDirection], Edge] = {}
        self.robber_position: HexTile = HexTile(0, 0, HexType.DESERT)

        self.create_hexes()
        self.create_vertices()
        self.create_edges()
        self.assign_neighbors()

    def create_hexes(self) -> None:
        """Create and assign the board hex tiles."""
        hex_types_sequence: List[HexType] = [
            HexType.FOREST, HexType.FOREST, HexType.FOREST, HexType.FOREST, HexType.HILLS, HexType.HILLS, HexType.HILLS,
            HexType.PASTURE, HexType.PASTURE, HexType.PASTURE, HexType.PASTURE, HexType.FIELDS, HexType.FIELDS,
            HexType.FIELDS, HexType.FIELDS, HexType.MOUNTAINS, HexType.MOUNTAINS, HexType.MOUNTAINS, HexType.DESERT
        ]

        self.rng.shuffle(hex_types_sequence)
        numbers = PRODUCTION_NUMBERS.copy()

        def get_adjacent_coords(q_val: int, r_val: int) -> List[Tuple[int, int]]:
            """Return axial coordinates of hexes adjacent to (q,r)."""
            directions = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
            return [(q_val + dq, r_val + dr) for dq, dr in directions]

        def assign_number(q_val: int, r_val: int, available: List[int]) -> Optional[int]:
            # Assign numbers with constraint that 6/8 are not adjacent
            self.rng.shuffle(available)
            for number in available:
                if number in (6, 8):
                    conflict = False
                    for nq, nr in get_adjacent_coords(q_val, r_val):
                        neighbor = self.hex_map.get((nq, nr))
                        if neighbor and neighbor.production_number in (6, 8):
                            conflict = True
                            break
                    if conflict:
                        continue
                return number
            return None  # Backtracking needed if stuck

        for i, (q, r) in enumerate(self.HEX_COORDS):
            hex_type = hex_types_sequence[i]
            production_number: Optional[int] = None
            if hex_type != HexType.DESERT:
                num = assign_number(q, r, numbers)
                if num is None:
                    # If assignment failed due to 6/8 conflicts, restart board generation
                    self.hexes.clear()
                    self.hex_map.clear()
                    self.production_to_hex.clear()
                    return self.create_hexes()
                production_number = num
                numbers.remove(num)

            hex_tile = HexTile(q, r, hex_type, production_number)
            self.hexes.append(hex_tile)
            self.hex_map[(q, r)] = hex_tile
            if hex_type == HexType.DESERT:
                hex_tile.robber = True
                self.robber_position = hex_tile
            else:
                self.production_to_hex[production_number].append(hex_tile)

    def create_vertices(self) -> None:
        """Create the board vertices and attach them to hexes."""
        vertex_map: Dict[Tuple[Tuple[int, int], ...], Vertex] = {}

        # Axial offsets for corners of a pointy-top hex
        corner_offsets: List[List[Tuple[int, int]]] = [
            [(0, 0), (1, -1), (0, -1)],  # top
            [(0, 0), (1, 0), (1, -1)],  # top-right
            [(0, 0), (0, 1), (1, 0)],  # bottom-right
            [(0, 0), (-1, 1), (0, 1)],  # bottom
            [(0, 0), (-1, 0), (-1, 1)],  # bottom-left
            [(0, 0), (0, -1), (-1, 0)]  # top-left
        ]

        for hex_tile in self.hexes:
            for idx, corner in enumerate(corner_offsets):
                key: Tuple[Tuple[int, int],
                           ...] = tuple(sorted([(hex_tile.q + dq, hex_tile.r + dr) for dq, dr in corner]))
                if key not in vertex_map:
                    vertex = Vertex((hex_tile.q, hex_tile.r, VertexDirection(idx)))
                    vertex_map[key] = vertex
                    self.vertices.append(vertex)
                vertex = vertex_map[key]
                if hex_tile not in vertex.hexes:
                    vertex.hexes.append(hex_tile)
                if vertex not in hex_tile.vertices:
                    hex_tile.vertices.append(vertex)

                # Store corner mapping
                self.vertex_map[(hex_tile.q, hex_tile.r, VertexDirection(idx))] = vertex

    def create_edges(self) -> None:
        """Create the board edges and connect them to vertices."""
        edge_map: Dict[Tuple[int, int], Edge] = {}

        for hex_tile in self.hexes:
            verts = hex_tile.vertices
            n = len(verts)
            for i in range(n):
                v1 = verts[i]
                v2 = verts[(i + 1) % n]  # Next vertex clockwise
                key: Tuple[int, int] = (min(id(v1), id(v2)), max(id(v1), id(v2)))

                if key not in edge_map:
                    edge = Edge(v1, v2, (hex_tile.q, hex_tile.r, EdgeDirection(i)))
                    edge_map[key] = edge
                    self.edges.append(edge)
                edge = edge_map[key]

                # Add connections
                if edge not in v1.edges:
                    v1.edges.append(edge)
                if edge not in v2.edges:
                    v2.edges.append(edge)

                # Store mapping by hex + direction
                self.edge_map[(hex_tile.q, hex_tile.r, EdgeDirection(i))] = edge

        # Assign ports
        water_edges = self._get_water_edges()
        num_edges = len(water_edges)

        available_edges = set(range(num_edges))
        blocked_edges = set()

        ports = PORT_TYPES[:]
        self.rng.shuffle(ports)

        for port in ports:
            candidates = [i for i in available_edges if i not in blocked_edges]

            if not candidates:
                # No legal placement left
                break

            i = self.rng.choice(candidates)

            edge = water_edges[i]
            v1, v2 = edge.vertices
            v1.port = v2.port = port
            self.port_vertices.append((port, v1, v2))

            # Block this edge ±2 to enforce 2-edge spacing
            blocked_edges.update({
                i,
                (i - 1) % num_edges,
                (i + 1) % num_edges,
                (i - 2) % num_edges,
                (i + 2) % num_edges,
            })

            available_edges.remove(i)

    def assign_neighbors(self) -> None:
        """Link neighboring vertices across the board."""
        directions: List[Tuple[int, int]] = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
        for hex_tile in self.hexes:
            for dq, dr in directions:
                neighbor = self.hex_map.get((hex_tile.q + dq, hex_tile.r + dr))
                if neighbor:
                    hex_tile.neighbors.append(neighbor)

    def build_settlement(self, vertex: Vertex, player: Player) -> None:
        """Build a settlement for the player on the given vertex."""
        vertex.owner = player
        vertex.building = Building.SETTLEMENT
        player.add_settlement(vertex)

    def build_city(self, vertex: Vertex, player: Player) -> None:
        """Upgrade the given settlement to a city."""
        vertex.building = Building.CITY
        player.add_city(vertex)

    def build_road(self, edge: Edge, player: Player) -> None:
        """Build a road for the player on the given edge."""
        edge.owner = player
        player.add_road(edge)

    @staticmethod
    def calculate_longest_road_length(roads: List[Edge]) -> int:
        """Calculate the longest connected road length."""
        if not roads:
            return 0

        # Build adjacency graph of connected roads
        road_graph = {}
        for road in roads:
            for vertex in road.vertices:
                if vertex not in road_graph:
                    road_graph[vertex] = []
                road_graph[vertex].append(road)

        max_length = 0

        # Try starting from each road and find the longest path
        for start_road in roads:
            for start_vertex in start_road.vertices:
                visited_roads = set()
                length = Board._dfs_longest_path(start_road, start_vertex, road_graph, visited_roads)
                max_length = max(max_length, length)

        return max_length

    @staticmethod
    def _dfs_longest_path(current_road: Edge, current_vertex: Vertex, road_graph: Dict, visited_roads: Set) -> int:
        """Explore road paths to find the longest valid route."""
        visited_roads.add(current_road)
        max_length = 1  # Current road counts as 1

        # Get the other vertex of current road
        other_vertex = None
        for vertex in current_road.vertices:
            if vertex != current_vertex:
                other_vertex = vertex
                break

        if other_vertex and other_vertex in road_graph:
            # Explore all unvisited roads connected to the other vertex
            for next_road in road_graph[other_vertex]:
                if next_road not in visited_roads:
                    # Check if this road is blocked by opponent's building
                    if not Board._is_road_blocked(other_vertex, current_road.owner):
                        length = 1 + Board._dfs_longest_path(next_road, other_vertex, road_graph, visited_roads.copy())
                        max_length = max(max_length, length)

        return max_length

    @staticmethod
    def _is_road_blocked(vertex: Vertex, player: Player) -> bool:
        """Check whether a road path is blocked at the vertex."""
        # If vertex has a building owned by another player, it blocks the path
        return vertex.owner is not None and vertex.owner != player

    def _get_water_edges(self) -> List[Edge]:
        """Return the water-facing edges on the board perimeter."""
        WIDTH = 6  # Edges in a hexagon
        directions = [
            t for i in range(2, WIDTH + 2)
            for t in [((i - 2) % WIDTH, (i - 1) % WIDTH), ((i - 2) % WIDTH, (i - 1) % WIDTH, i % WIDTH)]
        ]

        # Get all hexes grouped by row
        rows: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
        for x, y in self.hex_map.keys():
            rows[int(y)].append((int(x), int(y)))
        hexes = [sorted(rows[y], key=lambda t: t[0]) for y in sorted(rows)]
        water_hexes = [row[-1] for row in hexes[1:-1]] + hexes[-1][::-1] + \
                      [row[0] for row in hexes[1:-1]][::-1] + hexes[0]

        # Get water edges
        water_edges = []
        for pos, edge_directions in zip(water_hexes, directions):
            q, r = pos
            for d in edge_directions:
                water_edges.append(self.edge_map[(q, r, EdgeDirection(d))])
        return water_edges
