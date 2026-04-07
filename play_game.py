import argparse
import sys
from random import randint

from PyQt6.QtWidgets import QApplication

from GameController import GameController
from config.player_policies import STANDARD_SINGLEPLAYER, RULE_BASED_VS_BASIC
from view.CLIView import CLIView
from view.MainWindow import MainWindow
from view.QtView import QtView


def main():
    parser = argparse.ArgumentParser(description="Run Catan game.")
    parser.add_argument("--cli", action="store_true", help="Run the CLI version of the game")
    parser.add_argument("--seed", type=int, default=None, help="Optional seed for deterministic games")
    args = parser.parse_args()

    args.seed = randint(0, 2**31 - 1)
    args.seed = 593585961
    print(f"Game seed: {args.seed}")
    controller = GameController(STANDARD_SINGLEPLAYER, RULE_BASED_VS_BASIC, game_seed=args.seed)

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
