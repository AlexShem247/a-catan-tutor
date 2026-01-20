import argparse
import sys

from PyQt6.QtWidgets import QApplication

from GameController import GameController
from config.player_policies import STANDARD_SINGLEPLAYER, BASIC_VS_RANDOM, ALL_RANDOM
from view.CLIView import CLIView
from view.MainWindow import MainWindow
from view.QtView import QtView


def main():
    parser = argparse.ArgumentParser(description="Run Catan game.")
    parser.add_argument("--cli", action="store_true", help="Run the CLI version of the game")
    args = parser.parse_args()

    controller = GameController(STANDARD_SINGLEPLAYER, BASIC_VS_RANDOM)

    if args.cli:
        controller.view = CLIView(controller)
        controller.start_game()
    else:
        app = QApplication(sys.argv)
        controller.view = QtView(MainWindow(), controller)
        controller.start_game()
        sys.exit(app.exec())


if __name__ == "__main__":
    main()
