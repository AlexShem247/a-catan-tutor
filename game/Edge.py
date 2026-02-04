from enum import IntEnum
from typing import List, Optional, TYPE_CHECKING, Tuple

from game.Vertex import Vertex

if TYPE_CHECKING:
    from game.Player import Player


class EdgeDirection(IntEnum):
    NORTH_EAST = 0
    EAST = 1
    SOUTH_EAST = 2
    SOUTH_WEST = 3
    WEST = 4
    NORTH_WEST = 5


class Edge:
    def __init__(self, vertex1: Vertex, vertex2: Vertex, pos: Tuple[int, int, EdgeDirection]):
        self.vertices: List[Vertex] = [vertex1, vertex2]
        self.owner: Optional[Player] = None
        self.pos = pos

    def get_pos(self) -> str:
        q, r, direction = self.pos
        return f"{q}, {r}, {direction.name.title().replace('_', ' ')}"

    def get_other_vertex(self, vertex: Vertex) -> Vertex:
        """Given one vertex, return the other vertex of this edge."""
        if vertex == self.vertices[0]:
            return self.vertices[1]

        return self.vertices[0]

    def __repr__(self) -> str:
        if not self.owner:
            return f"PATH({self.get_pos()})"
        return f"{self.owner.name}-ROAD({self.get_pos()})"
