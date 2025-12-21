import sys
import traceback

from drawing.View import View

sys.excepthook = lambda exc_type, exc_value, tb: (traceback.print_exception(exc_type, exc_value, tb), sys.exit(-1))

import faulthandler
faulthandler.enable()

from PyQt6.QtWidgets import QApplication

from GameController import GameController
from drawing.MainWindow import MainWindow
from drawing.constants import WINDOW_WIDTH, WINDOW_HEIGHT
from game.Game import Game
from view.ai import random_initial_settlement_placement, random_initial_road_placement, make_round_move_ai, \
    trade_manager_ai, robber_discard_ai, place_robber_ai, year_of_plenty_selection_ai, monopoly_selection_ai
from view.ui import initial_settlement_placement, initial_road_placement, make_round_move, trade_manager, \
    place_robber, robber_discard, year_of_plenty_selection, monopoly_selection

if __name__ == "__main__":
    controller = GameController(
        Game(),
        get_settlement_choice=random_initial_settlement_placement,
        get_road_choice=random_initial_road_placement,
        get_settlement_choice_ai=random_initial_settlement_placement,
        get_road_choice_ai=random_initial_road_placement,
        play_round_hook=make_round_move,
        play_round_ai_hook=make_round_move_ai,
        trade_manager_hook=trade_manager,
        trade_manager_ai_hook=trade_manager_ai,
        robber_discard_hook=robber_discard,
        robber_discard_ai_hook=robber_discard_ai,
        place_robber_hook=place_robber,
        place_robber_ai_hook=place_robber_ai,
        year_of_plenty_selection=year_of_plenty_selection,
        year_of_plenty_selection_ai=year_of_plenty_selection_ai,
        monopoly_selection=monopoly_selection,
        monopoly_selection_ai=monopoly_selection_ai,
    )

    # Start Qt
    app = QApplication(sys.argv)
    window = MainWindow()
    controller.view = View(window, controller)
    window.setGeometry(120, 50, WINDOW_WIDTH, WINDOW_HEIGHT)
    window.show()
    controller.start_game()

    sys.exit(app.exec())
