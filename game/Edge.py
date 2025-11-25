from enum import IntEnum
from typing import List, Optional

from game.Player import Player
from game.Vertex import Vertex


class EdgeDirection(IntEnum):
    NORTH_EAST = 0
    EAST = 1
    SOUTH_EAST = 2
    SOUTH_WEST = 3
    WEST = 4
    NORTH_WEST = 5


class Edge:
    def __init__(self, vertex1: Vertex, vertex2: Vertex):
        self.vertices: List[Vertex] = [vertex1, vertex2]
        self.owner: Optional[Player] = None

    def __repr__(self) -> str:
        if not self.owner:
            return "PATH"
        return f"ROAD({self.owner.name})"
