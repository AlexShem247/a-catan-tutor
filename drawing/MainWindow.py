from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton
)

from GameController import GameController
from drawing.SquareCanvas import SquareCanvas


class MainWindow(QMainWindow):

    def __init__(self, controller: GameController):
        super().__init__()
        self.setWindowTitle("Settlers of Catan")
        self.controller = controller

        central = QWidget()
        self.setCentralWidget(central)

        h_layout = QHBoxLayout(central)

        # Canvas
        self.canvas = SquareCanvas()
        h_layout.addWidget(self.canvas)

        # Side panel
        side_panel = QWidget()
        side_panel.setFixedWidth(100)
        side_layout = QVBoxLayout(side_panel)
        side_layout.addWidget(QPushButton("Button 1"))
        side_layout.addWidget(QPushButton("Button 2"))
        side_layout.addStretch()
        h_layout.addWidget(side_panel)
