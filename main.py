import sys

from view.View import View
from PyQt6.QtWidgets import QApplication

from GameController import GameController
from view.MainWindow import MainWindow
from view.constants import WINDOW_WIDTH, WINDOW_HEIGHT

if __name__ == "__main__":
    controller = GameController()

    # Start Qt
    app = QApplication(sys.argv)
    window = MainWindow()
    controller.view = View(window, controller)
    window.setGeometry(120, 50, WINDOW_WIDTH, WINDOW_HEIGHT)
    window.show()
    controller.start_game()

    sys.exit(app.exec())
