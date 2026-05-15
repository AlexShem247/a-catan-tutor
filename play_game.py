import argparse
import sys
from random import randint

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from config.player_policies import EVO_VS_RULE_BASED, STANDARD_SINGLEPLAYER
from controllers.GameController import GameController
from view.MainWindow import MainWindow
from view.QtView import QtView


def main():
    parser = argparse.ArgumentParser(description="Run Catan game.")
    parser.add_argument("--seed", type=int, default=None, help="Optional seed for deterministic games")
    args = parser.parse_args()

    seed = args.seed if args.seed is not None else randint(0, 2**31 - 1)

    controller = GameController(
        STANDARD_SINGLEPLAYER,
        EVO_VS_RULE_BASED,
        game_seed=seed,
    )

    app = QApplication(sys.argv)
    app.setFont(QFont("Arial"))

    controller.view = QtView(MainWindow(), controller)
    controller.start_game()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
