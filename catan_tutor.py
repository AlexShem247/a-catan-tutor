import sys

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from config.player_policies import EVO_VS_RULE_BASED, STANDARD_SINGLEPLAYER
from controllers.GameController import GameController
from view.MainWindow import MainWindow
from view.QtView import QtView


def main():
    controller = GameController(STANDARD_SINGLEPLAYER, EVO_VS_RULE_BASED)

    app = QApplication(sys.argv)
    app.setFont(QFont("Arial"))

    controller.view = QtView(MainWindow(), controller)
    controller.start_game()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
