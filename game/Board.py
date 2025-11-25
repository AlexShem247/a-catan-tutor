import random
from typing import List, Optional, Dict, Tuple

from game.Edge import Edge, EdgeDirection
from game.HexTile import HexTile, HexType
from game.Player import Player
from game.Vertex import Vertex, VertexDirection, Building

HEX_TYPES: list[HexType] = ["forest", "hills", "pasture", "fields", "mountains", "desert"]

PRODUCTION_NUMBERS = [2, 3, 3, 4, 4, 5, 5, 6, 6,
                      8, 8, 9, 9, 10, 10, 11, 11, 12]


class Board:
    # Catan tile coordinates for 3-4-5-4-3 layout
    HEX_COORDS: List[Tuple[int, int]] = [
        (0, 0), (1, 0), (2, 0),
        (-1, 1), (0, 1), (1, 1), (2, 1),
        (-2, 2), (-1, 2), (0, 2), (1, 2), (2, 2),
        (-2, 3), (-1, 3), (0, 3), (1, 3),
        (-2, 4), (-1, 4), (0, 4)
    ]
    MIN_R: int = 0
    MAX_R: int = 4

    def __init__(self):
        self.hexes: List[HexTile] = []
        self.vertices: List[Vertex] = []
        self.edges: List[Edge] = []
        self.hex_map: Dict[Tuple[int, int], HexTile] = {}
        self.vertex_map: Dict[Tuple[int, int, VertexDirection], Vertex] = {}
        self.edge_map: Dict[Tuple[int, int, EdgeDirection], Edge] = {}

        self.create_hexes()
        self.create_vertices()
        self.create_edges()
        self.assign_neighbors()

    def create_hexes(self) -> None:
        hex_types_sequence: List[HexType] = [
            "forest", "forest", "forest", "forest",
            "hills", "hills", "hills",
            "pasture", "pasture", "pasture", "pasture",
            "fields", "fields", "fields", "fields",
            "mountains", "mountains", "mountains",
            "desert"
        ]

        random.shuffle(hex_types_sequence)
        prod_numbers = PRODUCTION_NUMBERS.copy()

        for i, (q, r) in enumerate(self.HEX_COORDS):
            hex_type = hex_types_sequence[i]
            production_number: Optional[int] = None
            if hex_type != "desert":
                production_number = prod_numbers.pop(0)
            hex_tile = HexTile(q, r, hex_type, production_number)
            self.hexes.append(hex_tile)
            self.hex_map[(q, r)] = hex_tile

    def create_vertices(self) -> None:
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
                key: Tuple[Tuple[int, int], ...] = tuple(
                    sorted([(hex_tile.q + dq, hex_tile.r + dr) for dq, dr in corner]))
                if key not in vertex_map:
                    vertex = Vertex()
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
        edge_map: Dict[Tuple[int, int], Edge] = {}
        for hex_tile in self.hexes:
            verts = hex_tile.vertices
            n = len(verts)
            for i in range(n):
                v1 = verts[i]
                v2 = verts[(i + 1) % n]  # Next vertex clockwise
                key: Tuple[int, int] = (min(id(v1), id(v2)), max(id(v1), id(v2)))
                if key not in edge_map:
                    edge = Edge(v1, v2)
                    edge_map[key] = edge
                    self.edges.append(edge)
                edge = edge_map[key]
                if edge not in v1.edges:
                    v1.edges.append(edge)
                if edge not in v2.edges:
                    v2.edges.append(edge)

                # store mapping by hex + direction
                self.edge_map[(hex_tile.q, hex_tile.r, EdgeDirection(i))] = edge

    def assign_neighbors(self) -> None:
        directions: List[Tuple[int, int]] = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
        for hex_tile in self.hexes:
            for dq, dr in directions:
                neighbor = self.hex_map.get((hex_tile.q + dq, hex_tile.r + dr))
                if neighbor:
                    hex_tile.neighbors.append(neighbor)

    def get_hex_tile(self, q: int, r: int) -> Optional[Vertex]:
        """Return the HexTile object for hex (q,r)."""
        return self.hex_map.get((q, r))

    def get_vertex(self, q: int, r: int, corner_index: VertexDirection) -> Optional[Vertex]:
        """Return the Vertex object for hex (q,r) at corner_index 0-5."""
        return self.vertex_map.get((q, r, corner_index))

    def get_edge(self, q: int, r: int, edge_index: EdgeDirection) -> Optional[Edge]:
        """Return the Edge object for hex (q,r) at edge_index 0-5."""
        return self.edge_map.get((q, r, edge_index))

    @staticmethod
    def build_settlement(vertex: Vertex, player: Player) -> None:
        """Directly build a settlement at the vertex, ignoring validation."""
        vertex.owner = player
        vertex.building = Building.SETTLEMENT
        player.add_settlement(vertex)

    @staticmethod
    def build_city(vertex: Vertex, player: Player) -> None:
        """Directly upgrade a settlement to a city, ignoring validation."""
        vertex.building = Building.CITY
        player.add_city(vertex)

    @staticmethod
    def build_road(edge: Edge, player: Player) -> None:
        """Directly assign ownership of a road, ignoring validation."""
        edge.owner = player
        player.add_road(edge)
