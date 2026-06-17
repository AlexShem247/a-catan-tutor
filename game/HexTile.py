from typing import TYPE_CHECKING

from game.Resources import HEX_TO_RESOURCE, HexType, Resource

if TYPE_CHECKING:
    from game.Vertex import Vertex


class HexTile:

    def __init__(self, q: int, r: int, hex_type: HexType, production_number: int | None = None):
        self.q: int = q
        self.r: int = r
        self.type: HexType = hex_type
        self.production_number: int | None = production_number
        self.vertices: list[Vertex] = []
        self.neighbors: list[HexTile] = []
        self.resource: Resource | None = HEX_TO_RESOURCE.get(hex_type)
        self.robber = False

    def __repr__(self) -> str:
        if self.type == HexType.DESERT:
            return "DESERT"
        return f"{self.type.name.upper()}({self.production_number})"
