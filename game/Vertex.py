from enum import IntEnum, Enum
from typing import List, Optional, TYPE_CHECKING, Tuple

from game.HexTile import HexTile

if TYPE_CHECKING:
    from game.Player import Player
    from game.Edge import Edge


class Buildable(Enum):
    ROAD = ("road", 15)
    SETTLEMENT = ("settlement", 5)
    CITY = ("city", 4)

    def __init__(self, label: str, max_on_board: int):
        self.label = label
        self.max_on_board = max_on_board


class Building(Enum):
    SETTLEMENT = Buildable.SETTLEMENT
    CITY = Buildable.CITY

    def get_resource_yield(self) -> int:
        """Return how many resources this building produces per turn."""
        if self == Building.CITY:
            return 2

        return 1


class VertexDirection(IntEnum):
    TOP = 0
    TOP_RIGHT = 1
    BOTTOM_RIGHT = 2
    BOTTOM = 3
    BOTTOM_LEFT = 4
    TOP_LEFT = 5


class Vertex:
    def __init__(self, pos: Tuple[int, int, VertexDirection]):
        self.hexes: List[HexTile] = []
        self.edges: List[Edge] = []
        self.owner: Optional[Player] = None
        self.building: Optional[Building] = None
        self.pos = pos

    def get_pos(self) -> str:
        q, r, direction = self.pos
        return f"{q}, {r}, {direction.name.title().replace('_', ' ')}"

    def __repr__(self) -> str:
        if not self.owner:
            return f"EMPTY({self.get_pos()})"
        return f"{self.owner.name}-{self.building.name}({self.get_pos()})"
