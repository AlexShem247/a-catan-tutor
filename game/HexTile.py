from typing import List, Optional, TYPE_CHECKING, Literal, Dict

from game.Color import Color, colorise

if TYPE_CHECKING:
    from game.Vertex import Vertex

HexType = Literal["forest", "hills", "pasture", "fields", "mountains", "desert"]

TYPE_COLOR_MAP: Dict[HexType, Color] = {
    "forest": Color.DARK_GREEN,
    "hills": Color.RED_ORANGE,
    "pasture": Color.LIME_GREEN,
    "fields": Color.GOLD,
    "mountains": Color.GREY,
    "desert": Color.BEIGE,
}


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

    def display_for_grid(self) -> str:
        if self.type == "desert":
            label = "DESRT"
        else:
            label = self.type[0].upper() + f"({self.production_number:02})"

        color = TYPE_COLOR_MAP.get(self.type)

        if color is None:
            return label

        return colorise(label, color, underline=True)
