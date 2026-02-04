from typing import List, Dict, Optional, Tuple, Any

from PyQt6.QtCore import QEventLoop, QTimer, pyqtBoundSignal

from GameController import GameController
from game.Edge import Edge
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import DevelopmentCardType
from game.Resources import ResourceCount
from game.Vertex import Vertex
from view.MainWindow import MainWindow
from view.View import View
from config.view_constants import AI_DECISION_ANIMATION_DELAY, WINDOW_WIDTH, WINDOW_HEIGHT


class QtView(View):
    def __init__(self, window: MainWindow, controller: GameController):
        self.window = window
        self.canvas = window.canvas
        self.controller = controller
        self.ai_decision_animation_delay = AI_DECISION_ANIMATION_DELAY
        self.window.setGeometry(120, 50, WINDOW_WIDTH, WINDOW_HEIGHT)
        self.window.show()

    def display_board(self, player: Optional[Player] = None, msg: Optional[str] = None):
        """Hook to display the board in the Qt window."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        if msg is not None and player is not None:
            self.window.display_generic_info(player, msg)

    def display_board_ai(self, player: Player, msg: str):
        """Hook to display the board in the Qt window."""
        self.window.display_resources(self.controller)
        self.window.display_generic_info(player, msg)
        ai_time_delay(self.ai_decision_animation_delay * 1)

    def display_board_turn(self, player: Player, dice_info: Tuple[int, int, int], played_dev_card: bool = False):
        """Hook to display the board in the Qt window."""
        select_blocking(self, self.window.turnMade, self.window.display_round_info, self.controller,
                        player, dice_info, played_dev_card)

    def display_board_turn_ai(self, player: Player, dice_info: Tuple[int, int, int], msg: str):
        """Hook to display the board in the Qt window."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.window.display_round_info_ai_start(player, dice_info, msg)
        delay = (3 if "\n" in msg else 1) * self.ai_decision_animation_delay
        ai_time_delay(delay)

    def draw_selectable_vertices(self, vertices: List[Vertex], disable_interactivity: bool = False) -> Vertex:
        """Draws which vertices are selectable"""
        self.canvas.disable_interactivity = disable_interactivity
        self.canvas.draw_selectable_vertices(vertices)
        if not disable_interactivity:
            return select_blocking(self, self.canvas.selectionMade, self.canvas.draw_selectable_vertices, vertices)

    def draw_selectable_edges(self, edges: List[Edge], disable_interactivity: bool = False) -> Edge:
        """Draws which edges are selectable"""
        self.canvas.disable_interactivity = disable_interactivity
        self.canvas.draw_selectable_edges(edges)
        if not disable_interactivity:
            return select_blocking(self, self.canvas.selectionMade, self.canvas.draw_selectable_edges, edges)

    def draw_selectable_tiles(self, tiles: List[HexTile]) -> HexTile:
        """Draws which tiles are selectable"""
        return select_blocking(self, self.canvas.selectionMade, self.canvas.draw_selectable_tiles, tiles)

    def draw_buildables(self, buildables: Dict):
        """Draws which tiles are selectable"""
        self.canvas.draw_buildables(buildables)

    def show_resource_chooser(self, player, num_resources: int, title: str,
                              resource_caps: ResourceCount | None = None) -> ResourceCount:
        return select_blocking(self, self.window.resourcesPicked, self.window.show_resource_chooser,
                               player, num_resources, title, resource_caps)

    def display_trade_manager(self, player: Player, selling: ResourceCount,
                              buying: ResourceCount, selling_player: Player) -> Tuple[bool, Optional[ResourceCount]]:
        """Displays trade and allows the option to accept, cancel or propose counter-offer"""
        return select_blocking(
            self, self.window.tradeDecisionMade, self.window.display_trade_manager, player, selling,
            buying, selling_player
        )

    def pre_roll(self, player: Player) -> DevelopmentCardType | bool:
        """Allows user to play development card before rolling dice"""
        return select_blocking(self, self.window.turnMade, self.window.show_development_menu, self.controller,
                               player, False, lambda card: self.window.turnMade.emit(card), pre_roll_mode=True)

    def display_results(self):
        """Display game results"""
        self.window.display_results(self.controller)

    def display_start_screen(self) -> bool:
        return select_blocking(self, self.window.startGame, self.window.display_start_screen)


def select_blocking(view: QtView, signal: pyqtBoundSignal, draw_fn, *args, **kwargs) -> Any:
    """Block execution until the signal emits a value, then return that value."""
    loop = QEventLoop()
    selected = None

    def on_selected(obj):
        nonlocal selected
        selected = obj
        loop.quit()

    # Disconnect all previous handlers safely
    try:
        signal.disconnect()
    except TypeError:
        pass

    # Connect the new handler
    signal.connect(on_selected)

    draw_fn(*args, **kwargs)

    loop.exec()

    # Clean up
    try:
        signal.disconnect(on_selected)
    except TypeError:
        pass

    view.canvas.clear_interactives()

    return selected


def ai_time_delay(seconds: int):
    if seconds > 0:
        loop = QEventLoop()

        QTimer.singleShot(int(seconds * 1000), loop.quit)

        loop.exec()
