from typing import List, Dict, Optional, Tuple

from PyQt6.QtCore import QEventLoop, QTimer

from GameController import GameController
from drawing.MainWindow import MainWindow
from drawing.constants import AI_DECISION_ANIMATION_DELAY
from game.Edge import Edge
from game.HexTile import HexTile
from game.Player import Player
from game.Vertex import Vertex


class View:
    """Provides hook functions that interact with Qt for the controller."""

    def __init__(self, window: MainWindow, controller: GameController):
        self.window = window
        self.canvas = window.canvas
        self.controller = controller

    def display_board(self, player: Optional[Player] = None, msg: Optional[str] = None):
        """Hook to display the board in the Qt window."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        if msg is not None and player is not None:
            self.window.display_generic_info(player, msg)
            if not player.is_human:
                ai_time_delay(AI_DECISION_ANIMATION_DELAY * 1)

    def display_board_ai(self, player: Player, msg: str):
        """Hook to display the board in the Qt window."""
        self.window.display_resources(self.controller)
        self.window.display_generic_info(player, msg)
        ai_time_delay(AI_DECISION_ANIMATION_DELAY * 1)

    def display_board_turn(self, params: Tuple[Player, Tuple[int, int, int]]):
        """Hook to display the board in the Qt window."""
        player, dice_info = params
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.window.display_round_info(self.controller, player, dice_info)

    def display_board_turn_ai(self, player: Player, dice_info: Tuple[int, int, int], msg: str):
        """Hook to display the board in the Qt window."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.window.display_round_info_ai_start(player, dice_info, msg)
        delay = (3 if "\n" in msg else 1) * AI_DECISION_ANIMATION_DELAY
        ai_time_delay(delay)

    def draw_selectable_vertices(self, vertices: List[Vertex]):
        """Draws which vertices are selectable"""
        self.canvas.draw_selectable_vertices(vertices)

    def draw_selectable_edges(self, edges: List[Edge]):
        """Draws which edges are selectable"""
        self.canvas.draw_selectable_edges(edges)

    def draw_selectable_tiles(self, tiles: List[HexTile]):
        """Draws which tiles are selectable"""
        self.canvas.draw_selectable_tiles(tiles)

    def draw_buildables(self, buildables: Dict):
        """Draws which tiles are selectable"""
        self.canvas.draw_buildables(buildables)


def select_blocking(view: View, draw_fn, options):
    loop = QEventLoop()
    selected = None

    def on_selected(obj):
        nonlocal selected
        selected = obj
        loop.quit()

    view.canvas.selectionMade.connect(on_selected)
    draw_fn(options)

    loop.exec()

    view.canvas.selectionMade.disconnect(on_selected)
    view.canvas.clear_interactives()

    return selected


def block_until_turn_finished(view: View, draw_fn, options):
    loop = QEventLoop()

    def on_selected(_):
        loop.quit()

    view.window.turnMade.connect(on_selected)
    draw_fn(options)

    loop.exec()

    view.window.turnMade.disconnect(on_selected)


def ai_time_delay(seconds: int):
    loop = QEventLoop()

    QTimer.singleShot(int(seconds * 1000), loop.quit)

    loop.exec()
