from typing import List, Optional, TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from game.Vertex import Vertex

HexType = Literal["forest", "hills", "pasture", "fields", "mountains", "desert"]


class HexTile:
    def __init__(self, q: int, r: int, hex_type: HexType, production_number: Optional[int] = None):
        self.q: int = q
        self.r: int = r
        self.type: HexType = hex_type
        self.production_number: Optional[int] = production_number
        self.vertices: List[Vertex] = []
        self.neighbors: List[HexTile] = []

    def __repr__(self) -> str:
        if self.type == "desert":
            return "DESERT"
        return f"{self.type.upper()}({self.production_number})"
