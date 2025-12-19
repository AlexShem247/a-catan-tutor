from typing import Dict, Tuple, Optional

from PyQt6 import uic
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter, QLabel
)

from drawing.SquareCanvas import SquareCanvas
from game.Game import Game
from game.Player import PlayerNumber, Player
from game.PlayerAssets import Buildable
from game.Resources import Resource


def get_player_lead_status(player: Player) -> str:
    """Return lead status."""
    player_vp = player.calc_victory_points()[0]
    best_opponent_vp = player.best_opponents_victory_point

    if player_vp > best_opponent_vp:
        return "♕"
    elif player_vp == best_opponent_vp and player_vp > 2:
        return 'Tied-♕'
    else:
        return ""


class MainWindow(QMainWindow):
    SIDE_PANEL_WIDTH = 320

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Settlers of Catan")

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
        self.side_panel.setMaximumWidth(self.SIDE_PANEL_WIDTH * 2)
        splitter.addWidget(self.side_panel)

        splitter.setSizes([
            1000,
            self.SIDE_PANEL_WIDTH
        ])

        # Prevent canvas from being squashed too much
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

    def display_resources(self, game):
        # Fill in bank labels
        bank_labels: Dict[Resource, QLabel] = {
            Resource.WOOD: self.side_panel.bank_wood_label,
            Resource.BRICK: self.side_panel.bank_brick_label,
            Resource.SHEEP: self.side_panel.bank_sheep_label,
            Resource.WHEAT: self.side_panel.bank_wheat_label,
            Resource.ORE: self.side_panel.bank_ore_label,
        }

        for res, label in bank_labels.items():
            label.setText(str(game.bank_resources[res]))

        self.side_panel.bank_dev_label.setText(str(game.development_deck.size()))

        # Fill in opponent labels
        opponent_labels: Dict[PlayerNumber, Dict[str, QLabel]] = {
            PlayerNumber.P2: {
                "victory_points": self.side_panel.p2_vic_label,
                "num_resources": self.side_panel.p2_res_label,
                "development_cards": self.side_panel.p2_dev_label,
                "army_size": self.side_panel.p2_army_label,
                "longest_road": self.side_panel.p2_road_label,
            },
            PlayerNumber.P3: {
                "victory_points": self.side_panel.p3_vic_label,
                "num_resources": self.side_panel.p3_res_label,
                "development_cards": self.side_panel.p3_dev_label,
                "army_size": self.side_panel.p3_army_label,
                "longest_road": self.side_panel.p3_road_label,
            },
            PlayerNumber.P4: {
                "victory_points": self.side_panel.p4_vic_label,
                "num_resources": self.side_panel.p4_res_label,
                "development_cards": self.side_panel.p4_dev_label,
                "army_size": self.side_panel.p4_army_label,
                "longest_road": self.side_panel.p4_road_label,
            },
        }

        player_labels: Dict[Resource, QLabel] = {
            Resource.WOOD: self.side_panel.wood_label,
            Resource.BRICK: self.side_panel.brick_label,
            Resource.SHEEP: self.side_panel.sheep_label,
            Resource.WHEAT: self.side_panel.wheat_label,
            Resource.ORE: self.side_panel.ore_label,
        }

        for res, label in bank_labels.items():
            label.setText(str(game.bank_resources[res]))

        for player in game.players:
            num = player.playerNumber
            if num == PlayerNumber.P1:
                for res, label in player_labels.items():
                    label.setText(str(player.resources[res]))

                visible_vp, true_vp = player.calc_victory_points()
                true_vp_str = f" ({true_vp})" if visible_vp != true_vp else ""
                longest_road_crown = "♕" if player.has_longest_road else ""
                army_crown = "♕" if player.has_largest_army else ""
                lead_status = get_player_lead_status(player)

                self.side_panel.longest_road_label.setText(
                    f"Longest Road:\t{player.longest_road_length} {longest_road_crown}"
                )
                self.side_panel.army_size_label.setText(
                    f"Army Size:\t{player.army_size} {army_crown}"
                )
                self.side_panel.victory_points_label.setText(
                    f"Victory Points:\t{visible_vp}{true_vp_str} {lead_status}"
                )
            else:
                labels = opponent_labels[num]
                labels["victory_points"].setText(str(player.calc_victory_points()[0]))
                labels["num_resources"].setText(str(sum(player.resources.values())))
                labels["development_cards"].setText(str(len(player.development_cards)))
                labels["army_size"].setText(str(player.army_size))
                labels["longest_road"].setText(str(player.longest_road_length))

    def display_turn_info(self, game: Game, player: Player, dice_roll: Optional[Tuple[int, int, int]] = None, msg: Optional[str] = None):
        if dice_roll:
            d1, d2, total = dice_roll
            self.side_panel.turn_label.setText(f"{player.name}'s turn")
            self.side_panel.main_label.setText(f"Dice rolled: {d1} + {d2} = {total}\nWhat would you like to do?")
        if msg:
            self.side_panel.main_label.setText(msg)

        # Actions
        buildable = game.get_buildable_options(player)
        can_build = buildable[Buildable.ROAD] or buildable[Buildable.SETTLEMENT] or buildable[Buildable.CITY]
        self.side_panel.action_label.setText("Click on the board to build" if can_build else "")
        self.side_panel.dev_btn.setEnabled(buildable[Buildable.DEVELOPMENT_CARD] or len(player.development_cards) > 0)
        self.side_panel.trade_btn.setEnabled(sum(player.resources.values()) > 0)

