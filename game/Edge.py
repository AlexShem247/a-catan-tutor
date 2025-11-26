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

    def __repr__(self) -> str:
        if not self.owner:
            return "PATH"
        return f"ROAD({self.owner.name})"
