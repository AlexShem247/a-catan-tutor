from typing import Dict, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from game.Player import PlayerNumber
from game.PlayerAssets import Building
from game.Resources import HexType, Resource, HEX_TO_RESOURCE
from game.Vertex import Port

WINDOW_WIDTH, WINDOW_HEIGHT = 1400, 730
TITLE_COLOR = QColor(250, 200, 60)
BOARD_BG_COLOR = QColor(15, 112, 183)
HEX_TILE_RADIUS = 100
EDGE_COLOR = QColor(240, 220, 170)
PORT_EDGE_COLOR = QColor(220, 150, 50)
PLAN_OUTLINE_COLOR = QColor(100, 200, 200)
ROAD_THICKNESS = 10
VERTEX_SIZE = 15

CROWN_SYM = "♛"
SHOW_AI_BUILT_LOCATIONS = False

HIGHLIGHT_ANIMATION = True
AI_DECISION_ANIMATION_DELAY = 0.1  # Seconds
AI_DECISION_ANIMATION_DELAY_SIMULATION_MODE = 0.05  # Seconds
TUTOR_FEEDBACK_DISPLAY_SECONDS: Dict[str, float] = {
    "Excellent": 3.0,
    "Good": 4.0,
    "Okay": 6.0,
}
TUTOR_FEEDBACK_FADE_STEPS = 12

OUTLINE_COLOR = QColor(Qt.GlobalColor.black)
HIGHLIGHT_COLOR = QColor(Qt.GlobalColor.yellow)

TOKEN_COLOR = QColor(Qt.GlobalColor.white)
TOKEN_OUTLINE_COLOR = OUTLINE_COLOR
TOKEN_COMMON_COLOR = QColor(Qt.GlobalColor.red)

TERRAIN_COLORS: Dict[HexType, QColor] = {
    HexType.FIELDS: QColor(255, 184, 38),
    HexType.FOREST: QColor(27, 126, 36),
    HexType.PASTURE: QColor(162, 211, 49),
    HexType.MOUNTAINS: QColor(120, 120, 120),
    HexType.HILLS: QColor(200, 100, 60),
    HexType.DESERT: QColor(210, 180, 120)
}

RESOURCE_ICONS: Dict[Resource, str] = {
    Resource.WOOD: "assets/wood.png",
    Resource.BRICK: "assets/brick.png",
    Resource.SHEEP: "assets/sheep.png",
    Resource.WHEAT: "assets/wheat.png",
    Resource.ORE: "assets/ore.png",
}

HOME_ICON = "assets/home.png"
DESERT_ICON = "assets/cactus.png"
ROBBER_ICON = "assets/robber.png"
SEA_BACKGROUND = "assets/sea_background.png"
SETTLEMENT_OUTLINE = "assets/settlement_outline.png"
SETTLEMENT_OUTLINE_SOLID = "assets/settlement_outline_solid.png"
CITY_OUTLINE = "assets/city_outline.png"

PORT_ICONS: Dict[Port, str] = {
    Port.THREE_TO_ONE: "assets/port_generic.png",
    Port.WOOD: "assets/port_wood.png",
    Port.BRICK: "assets/port_brick.png",
    Port.SHEEP: "assets/port_sheep.png",
    Port.WHEAT: "assets/port_wheat.png",
    Port.ORE: "assets/port_ore.png",
}

PLAYER_COLORS: Dict[PlayerNumber, QColor] = {
    PlayerNumber.P1: QColor(0, 0, 255),
    PlayerNumber.P2: QColor(255, 0, 0),
    PlayerNumber.P3: QColor(0, 255, 0),
    PlayerNumber.P4: QColor(255, 125, 0),
}

SETTLEMENT_ICONS: Dict[Tuple[PlayerNumber, Building], str] = {
    (PlayerNumber.P1, Building.SETTLEMENT): "assets/settlement_1.png",
    (PlayerNumber.P1, Building.CITY): "assets/city_1.png",
    (PlayerNumber.P2, Building.SETTLEMENT): "assets/settlement_2.png",
    (PlayerNumber.P2, Building.CITY): "assets/city_2.png",
    (PlayerNumber.P3, Building.SETTLEMENT): "assets/settlement_3.png",
    (PlayerNumber.P3, Building.CITY): "assets/city_3.png",
    (PlayerNumber.P4, Building.SETTLEMENT): "assets/settlement_4.png",
    (PlayerNumber.P4, Building.CITY): "assets/city_4.png",
}


def hex_to_filepath(hex_type: HexType) -> str:
    """Convert a HexType to its corresponding file_path."""
    if hex_type == HexType.DESERT:
        return DESERT_ICON

    resource = HEX_TO_RESOURCE.get(hex_type)
    if resource is None:
        raise ValueError(f"No resource mapping for hex type {hex_type}")

    pixmap = RESOURCE_ICONS.get(resource)
    if pixmap is None:
        raise ValueError(f"No pixmap for resource {resource}")

    return pixmap
