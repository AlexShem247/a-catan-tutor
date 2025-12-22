from typing import List, Dict, Optional, Tuple, TYPE_CHECKING

from drawing.MainWindow import MainWindow
from drawing.constants import AI_DECISION_ANIMATION_DELAY
from drawing.view_utils import ai_time_delay
from game.Edge import Edge
from game.HexTile import HexTile
from game.Player import Player
from game.Resources import ResourceCount
from game.Vertex import Vertex

if TYPE_CHECKING:
    from GameController import GameController


class View:
    """Provides hook functions that interact with Qt for the controller."""

    def __init__(self, window: MainWindow, controller: "GameController"):
        self.window = window
        self.canvas = window.canvas
        self.controller = controller
        self.canvasSelection = self.canvas.selectionMade
        self.turnMade = self.window.turnMade
        self.tradeDecisionMade = self.window.tradeDecisionMade
        self.resourcesPicked = self.window.resourcesPicked
        self.startGame = self.window.startGame
        self.ai_decision_animation_delay = AI_DECISION_ANIMATION_DELAY

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
        self.window.display_round_info(self.controller, player, dice_info, played_dev_card)

    def display_board_turn_ai(self, player: Player, dice_info: Tuple[int, int, int], msg: str):
        """Hook to display the board in the Qt window."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.window.display_round_info_ai_start(player, dice_info, msg)
        delay = (3 if "\n" in msg else 1) * self.ai_decision_animation_delay
        ai_time_delay(delay)

    def draw_selectable_vertices(self, vertices: List[Vertex], disable_interactivity: bool = False):
        """Draws which vertices are selectable"""
        self.canvas.disable_interactivity = disable_interactivity
        self.canvas.draw_selectable_vertices(vertices)

    def draw_selectable_edges(self, edges: List[Edge], disable_interactivity: bool = False):
        """Draws which edges are selectable"""
        self.canvas.disable_interactivity = disable_interactivity
        self.canvas.draw_selectable_edges(edges)

    def draw_selectable_tiles(self, tiles: List[HexTile]):
        """Draws which tiles are selectable"""
        self.canvas.draw_selectable_tiles(tiles)

    def draw_buildables(self, buildables: Dict):
        """Draws which tiles are selectable"""
        self.canvas.draw_buildables(buildables)

    def show_resource_chooser(self, player, num_resources: int, title: str,
                              resource_caps: ResourceCount | None = None):
        self.window.show_resource_chooser(player, num_resources, title, resource_caps)

    def display_trade_manager(self, player: Player, selling: ResourceCount,
                              buying: ResourceCount, selling_player: Player):
        """Displays trade and allows the option to accept, cancel or propose counter-offer"""
        self.window.display_trade_manager(player, selling, buying, selling_player)

    def pre_roll(self, player: Player):
        """Allows user to play development card before rolling dice"""
        self.window.show_development_menu(
            self.controller, player, False, lambda card: self.turnMade.emit(card), pre_roll_mode=True
        )

    def display_results(self):
        """Display game results"""
        self.window.display_results(self.controller)

    def display_start_screen(self):
        """Display game results"""
        self.window.display_start_screen()
