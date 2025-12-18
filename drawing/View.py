from drawing.SquareCanvas import SquareCanvas
from game.Game import Game


class View:
    """Provides hook functions that interact with Qt for the controller."""

    def __init__(self, window: SquareCanvas):
        self.window = window

    def display_board(self, game: Game):
        """Hook to display the board in the Qt window."""
        self.window.display_board(game)
