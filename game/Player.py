from enum import Enum

from game.Color import Color


class Player(Enum):
    P1 = 0
    P2 = 1
    P3 = 2
    P4 = 3

    def get_color(self) -> Color:
        return [Color.BLUE, Color.RED, Color.GREEN, Color.YELLOW][self.value]
