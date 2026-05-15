from typing import TYPE_CHECKING, List, Optional

from game.Resources import HEX_TO_RESOURCE, HexType, Resource

if TYPE_CHECKING:
    from game.Vertex import Vertex


class HexTile:

    def __init__(self, q: int, r: int, hex_type: HexType, production_number: Optional[int] = None):
        self.q: int = q
        self.r: int = r
        self.type: HexType = hex_type
        self.production_number: Optional[int] = production_number
        self.vertices: List[Vertex] = []
        self.neighbors: List[HexTile] = []
        self.resource: Optional[Resource] = HEX_TO_RESOURCE.get(hex_type)
        self.robber = False

    def __repr__(self) -> str:
        if self.type == HexType.DESERT:
            return "DESERT"
        return f"{self.type.name.upper()}({self.production_number})"
