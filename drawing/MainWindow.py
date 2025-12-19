from PyQt6 import uic
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter
)

from GameController import GameController
from drawing.SquareCanvas import SquareCanvas


class MainWindow(QMainWindow):

    SIDE_PANEL_WIDTH = 320

    def __init__(self, controller: GameController):
        super().__init__()
        self.setWindowTitle("Settlers of Catan")

        self.controller = controller

        # Central widget
        central = QWidget(self)
        self.setCentralWidget(central)

        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        layout.addWidget(splitter)

        # Canvas
        self.canvas = SquareCanvas()
        splitter.addWidget(self.canvas)

        # Side panel
        self.side_panel = uic.loadUi("drawing/ui/main_menu.ui")
        self.side_panel.setMinimumWidth(0)
        self.side_panel.setMaximumWidth(self.SIDE_PANEL_WIDTH*2)
        splitter.addWidget(self.side_panel)

        splitter.setSizes([
            1000,
            self.SIDE_PANEL_WIDTH
        ])

        # Prevent canvas from being squashed too much
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
