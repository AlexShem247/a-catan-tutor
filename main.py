import argparse
import sys

from PyQt6.QtWidgets import QApplication

from GameController import GameController
from ai.BasicAI import BasicAI
from ai.RandomAI import RandomAI
from game.Game import PlayerConfig
from game.Player import PlayerNumber
from view.CLIView import CLIView
from view.MainWindow import MainWindow
from view.QtView import QtView


def main():
    parser = argparse.ArgumentParser(description="Run Catan game.")
    parser.add_argument("--cli", action="store_true", help="Run the CLI version of the game")
    args = parser.parse_args()

    human_player: PlayerConfig = {PlayerNumber.P1: None}
    ai_player: PlayerConfig = {PlayerNumber.P1: BasicAI}

    opponent_players: PlayerConfig = {
        PlayerNumber.P2: RandomAI,
        PlayerNumber.P3: RandomAI,
        PlayerNumber.P4: RandomAI,
    }

    controller = GameController(human_player | opponent_players, ai_player | opponent_players)

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
