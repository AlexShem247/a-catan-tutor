from typing import Dict, Tuple

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor

from game.Player import PlayerNumber
from game.PlayerAssets import Building
from game.Resources import HEX_TO_RESOURCE, HexType, Resource
from game.Vertex import Port

# Window and top-level layout
APP_WINDOW_TITLE = "Catan - Explainable Al Tutor"
WINDOW_WIDTH, WINDOW_HEIGHT = 1400, 760
WINDOW_DEFAULT_X = 80
WINDOW_DEFAULT_Y = 50
MAIN_WINDOW_SIDE_PANEL_WIDTH = 360
MAIN_WINDOW_SIDE_PANEL_MAX_WIDTH = MAIN_WINDOW_SIDE_PANEL_WIDTH * 2
MAIN_WINDOW_BOARD_PANEL_DEFAULT_WIDTH = 1000
TUTOR_PANEL_DEFAULT_WIDTH_RATIO = 0.8
MAIN_WINDOW_HEADER_ICON_SIZE = QSize(18, 18)

# UI resource paths
UI_MAIN_MENU_PATH = "view/ui/main_menu.ui"
UI_TUTOR_MENU_PATH = "view/ui/tutor_menu.ui"
UI_RESOURCE_SELECTOR_PATH = "view/ui/resource_selector.ui"
UI_TRADE_DESIGNER_PATH = "view/ui/trade_designer.ui"
UI_SELECT_TRADE_PATH = "view/ui/select_trade.ui"
UI_TRADE_MANAGER_PATH = "view/ui/trade_manager.ui"
UI_DEVELOPMENT_MANAGER_PATH = "view/ui/development_manager.ui"
UI_RESULTS_MENU_PATH = "view/ui/results_menu.ui"
UI_ENDGAME_REVIEW_PATH = "view/ui/endgame_review.ui"
UI_START_MENU_PATH = "view/ui/start_menu.ui"
UI_RULES_WINDOW_PATH = "view/ui/rules_window.ui"
UI_SETTINGS_WINDOW_PATH = "view/ui/settings_window.ui"

# Shared badge and label styling
PLAYER_BADGE_FONT_SIZE_PX = 12
PLAYER_BADGE_FONT_WEIGHT = 700
PLAYER_BADGE_BORDER_RADIUS_PX = 12
PLAYER_BADGE_LIGHTER_FACTOR = 150
PLAYER_INDICATOR_BADGE_PADDING_PX = (3, 8)
TURN_LABEL_BADGE_PADDING_PX = (4, 8)
OPPONENT_BADGE_PADDING_PX = (2, 8)

# Tutor panel UI
TUTOR_WINDOW_ICON_SIZE_PX = 48
TUTOR_WINDOW_TITLE_ICON_PADDING_LEFT_PX = 8
TUTOR_HISTORY_NAV_BUTTON_SIZE_PX = 40
TUTOR_HISTORY_ACTION_HEIGHT_PX = 40
TUTOR_FEEDBACK_HISTORY_LIMIT = 100

# Endgame review and plot UI
ENDGAME_REVIEW_TROPHY_SIZE = QSize(80, 80)
ENDGAME_REPLAY_SPLITTER_HANDLE_WIDTH_PX = 8
ENDGAME_REVIEW_BREAKDOWN_PANEL_WIDTH = 200
ENDGAME_REPLAY_MIN_PANEL_WIDTH = 280
ENDGAME_FEEDBACK_CARD_LAYOUT_SPACING_PX = 8
ENDGAME_PLOT_LAYOUT_MARGINS = (10, 8, 10, 8)
ENDGAME_PLOT_TOOLTIP_BORDER_RADIUS_PX = 8
ENDGAME_PLOT_TOOLTIP_OFFSET_PX = 16
ENDGAME_PLOT_HOVER_DISTANCE_THRESHOLD_PX = 100
ENDGAME_PLOT_TARGET_TICK_PIXEL_SPACING = 80
ENDGAME_PLOT_LEGEND_OFFSET = (10, 10)
ENDGAME_PLOT_TARGET_VICTORY_POINTS = 10
ENDGAME_BADGE_BORDER_RADIUS_PX = 9
ENDGAME_BADGE_PADDING = "3px 8px"
ENDGAME_BADGE_FONT_WEIGHT = 700
ENDGAME_FEEDBACK_CARD_BORDER_RADIUS_PX = 8
ENDGAME_FEEDBACK_CARD_PADDING = "10px 12px"

# Board and canvas rendering
TITLE_COLOR = QColor(250, 200, 60)
BOARD_BG_COLOR = QColor(15, 112, 183)
HEX_TILE_RADIUS = 100
EDGE_COLOR = QColor(240, 220, 170)
PORT_EDGE_COLOR = QColor(220, 150, 50)
PLAN_OUTLINE_COLOR = QColor(100, 200, 200)
ROAD_THICKNESS = 10
VERTEX_SIZE = 15
CANVAS_ANIMATION_INTERVAL_MS = 16
CANVAS_ZOOM_HINT_FONT_SIZE_PX = 12
CANVAS_ZOOM_HINT_PADDING_PX = 12
SECONDS_TO_MILLISECONDS = 1000

# General display and animation behaviour
CROWN_SYM = "\u265b"
SHOW_AI_BUILT_LOCATIONS = False
HIGHLIGHT_ANIMATION = True
AI_DECISION_ANIMATION_DELAY = 1.0  # Seconds
AI_DECISION_ANIMATION_DELAY_SIMULATION_MODE = 0.05  # Seconds
TUTOR_FEEDBACK_MIN_DISPLAY_SECONDS = 3.0
TUTOR_FEEDBACK_MAX_DISPLAY_SECONDS = 7.0
TUTOR_FEEDBACK_FADE_STEPS = 12

# Shared colours
OUTLINE_COLOR = QColor(Qt.GlobalColor.black)
HIGHLIGHT_COLOR = QColor(Qt.GlobalColor.yellow)
TOKEN_COLOR = QColor(Qt.GlobalColor.white)
TOKEN_OUTLINE_COLOR = OUTLINE_COLOR
TOKEN_COMMON_COLOR = QColor(Qt.GlobalColor.red)
TOOLTIP_BACKGROUND_COLOR = QColor(17, 24, 39)
TOOLTIP_BORDER_COLOR = QColor(55, 65, 81)
TOOLTIP_TEXT_COLOR = QColor(249, 250, 251)
ENDGAME_PLOT_BACKGROUND_COLOR = QColor(249, 250, 251)
ENDGAME_RANK_CARD_DEFAULT_BACKGROUND_COLOR = QColor(249, 250, 251)
ENDGAME_RANK_CARD_DEFAULT_BORDER_COLOR = QColor(229, 231, 235)
ENDGAME_RANK_CARD_SELECTED_BACKGROUND_COLOR = QColor(239, 246, 255)
ENDGAME_RANK_CARD_SELECTED_BORDER_COLOR = QColor(37, 99, 235)
ENDGAME_RANK_CARD_BORDER_RADIUS_PX = 8
ENDGAME_RANK_CARD_DEFAULT_BORDER_WIDTH_PX = 1
ENDGAME_RANK_CARD_SELECTED_BORDER_WIDTH_PX = 2
ENDGAME_RANK_CARD_PADDING = "10px 12px"
ENDGAME_RANK_CARD_FONT_WEIGHT = 600

# Game board colour mappings
TERRAIN_COLORS: Dict[HexType, QColor] = {
    HexType.FIELDS: QColor(255, 184, 38),
    HexType.FOREST: QColor(27, 126, 36),
    HexType.PASTURE: QColor(162, 211, 49),
    HexType.MOUNTAINS: QColor(120, 120, 120),
    HexType.HILLS: QColor(200, 100, 60),
    HexType.DESERT: QColor(210, 180, 120),
}

# Asset paths
RESOURCE_ICONS: Dict[Resource, str] = {
    Resource.WOOD: "assets/wood.png",
    Resource.BRICK: "assets/brick.png",
    Resource.SHEEP: "assets/sheep.png",
    Resource.WHEAT: "assets/wheat.png",
    Resource.ORE: "assets/ore.png",
}
APP_ICON = "assets/logo.png"
HOME_ICON = "assets/home.png"
RULES_ICON = "assets/rules.png"
SETTINGS_ICON = "assets/settings.png"
DESERT_ICON = "assets/cactus.png"
ROBBER_ICON = "assets/robber.png"
SEA_BACKGROUND = "assets/sea_background.png"
SETTLEMENT_OUTLINE = "assets/settlement_outline.png"
SETTLEMENT_OUTLINE_SOLID = "assets/settlement_outline_solid.png"
CITY_OUTLINE = "assets/city_outline.png"
TUTOR_ICON = "assets/tutor.png"
TROPHY_ICON = "assets/trophy.png"

# Port and player assets
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

# Building sprites
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
