from enum import IntEnum, Enum
from typing import List, Optional, TYPE_CHECKING, Tuple

from game.HexTile import HexTile
from game.PlayerAssets import Building

if TYPE_CHECKING:
    from game.Player import Player
    from game.Edge import Edge


class VertexDirection(IntEnum):
    TOP = 0
    TOP_RIGHT = 1
    BOTTOM_RIGHT = 2
    BOTTOM = 3
    BOTTOM_LEFT = 4
    TOP_LEFT = 5


class Port(Enum):
    WOOD = 0
    BRICK = 1
    SHEEP = 2
    WHEAT = 3
    ORE = 4
    THREE_TO_ONE = 5


class Vertex:
    def __init__(self, pos: Tuple[int, int, VertexDirection]):
        self.hexes: List[HexTile] = []
        self.edges: List[Edge] = []
        self.owner: Optional[Player] = None
        self.building: Optional[Building] = None
        self.pos = pos
        self.port: Optional[Port] = None

    def get_pos(self) -> str:
        q, r, direction = self.pos
        return f"{q}, {r}, {direction.name.title().replace('_', ' ')}"

    def __repr__(self) -> str:
        if not self.owner:
            return f"EMPTY({self.get_pos()})"
        return f"{self.owner.name}-{self.building.name}({self.get_pos()})"
