from enum import IntEnum, Enum
from typing import List, Optional, TYPE_CHECKING

from game.HexTile import HexTile
from game.Player import Player

if TYPE_CHECKING:
    from game.Edge import Edge


class Building(Enum):
    SETTLEMENT = 0
    CITY = 1


class VertexDirection(IntEnum):
    TOP = 0
    TOP_RIGHT = 1
    BOTTOM_RIGHT = 2
    BOTTOM = 3
    BOTTOM_LEFT = 4
    TOP_LEFT = 5


class Vertex:
    def __init__(self):
        self.hexes: List[HexTile] = []
        self.edges: List[Edge] = []
        self.owner: Optional[Player] = None
        self.building: Optional[Building] = None

    def __repr__(self) -> str:
        if not self.owner:
            return "EMPTY"
        return f"{self.owner.name}({self.building.name if self.building else '?'})"
