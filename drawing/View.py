from typing import List, Dict, Tuple

from PyQt6.QtCore import QEventLoop

from drawing.MainWindow import MainWindow
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.Vertex import Vertex


class View:
    """Provides hook functions that interact with Qt for the controller."""

    def __init__(self, window: MainWindow):
        self.window = window
        self.canvas = window.canvas

    def display_board(self, game: Game, player: Player, msg: str):
        """Hook to display the board in the Qt window."""
        self.canvas.display_board(game)
        self.window.display_resources(game)
        self.window.display_turn_info(game, player, msg=msg)

    def display_board_turn(self, game: Game, player: Player, dice_roll: Tuple[int, int, int]):
        """Hook to display the board in the Qt window."""
        self.canvas.display_board(game)
        self.window.display_resources(game)
        self.window.display_turn_info(game, player, dice_roll=dice_roll)

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
