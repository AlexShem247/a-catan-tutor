from typing import List, Dict

from PyQt6.QtCore import QEventLoop

from drawing.SquareCanvas import SquareCanvas
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Vertex import Vertex


class View:
    """Provides hook functions that interact with Qt for the controller."""

    def __init__(self, window: SquareCanvas):
        self.window = window

    def display_board(self, game: Game):
        """Hook to display the board in the Qt window."""
        self.window.display_board(game)

    def draw_selectable_vertices(self, vertices: List[Vertex]):
        """Draws which vertices are selectable"""
        self.window.draw_selectable_vertices(vertices)

    def draw_selectable_edges(self, edges: List[Edge]):
        """Draws which edges are selectable"""
        self.window.draw_selectable_edges(edges)

    def draw_selectable_tiles(self, tiles: List[HexTile]):
        """Draws which tiles are selectable"""
        self.window.draw_selectable_tiles(tiles)

    def draw_buildables(self, buildables: Dict):
        """Draws which tiles are selectable"""
        self.window.draw_buildables(buildables)


def select_blocking(view: View, draw_fn, options):
    loop = QEventLoop()
    selected = None

    def on_selected(obj):
        nonlocal selected
        selected = obj
        loop.quit()

    view.window.selectionMade.connect(on_selected)
    draw_fn(options)

    loop.exec()

    view.window.selectionMade.disconnect(on_selected)
    view.window.clear_interactives()

    return selected
