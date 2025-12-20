from typing import Dict, Tuple

from PyQt6 import uic
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter, QLabel, QPushButton, QToolButton
)

from GameController import GameController
from drawing.SquareCanvas import SquareCanvas
from game.Player import PlayerNumber, Player
from game.PlayerAssets import Buildable
from game.Resources import Resource, ResourceCount


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
    LABEL_LINE_LENGTH = 38
    turnMade = pyqtSignal(object)

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

        self.resource_selector_widget = uic.loadUi("drawing/ui/resource_selector.ui")

        self.toggle_main_action_btns(False)

    @staticmethod
    def word_wrap(msg: str, limit=LABEL_LINE_LENGTH) -> str:
        out = []
        for raw in msg.split("\n"):
            line = ""
            for w in raw.split():
                line, out = (w, out + [line]) if len(line) + len(w) + bool(line) > limit else (
                    f"{line} {w}" if line else w, out)
            out.append(line)
        return "\n".join(out)

    def toggle_main_action_btns(self, show: bool):
        for i in range(self.side_panel.action_btn_layout.count()):
            widget: QWidget = self.side_panel.action_btn_layout.itemAt(i).widget()
            if widget:
                if show:
                    widget.show()
                else:
                    widget.hide()

    def display_resources(self, controller: GameController):
        # Fill in bank labels
        bank_labels: Dict[Resource, QLabel] = {
            Resource.WOOD: self.side_panel.bank_wood_label,
            Resource.BRICK: self.side_panel.bank_brick_label,
            Resource.SHEEP: self.side_panel.bank_sheep_label,
            Resource.WHEAT: self.side_panel.bank_wheat_label,
            Resource.ORE: self.side_panel.bank_ore_label,
        }

        for res, label in bank_labels.items():
            label.setText(str(controller.get_bank_resources()[res]))

        self.side_panel.bank_dev_label.setText(str(controller.get_development_deck().size()))

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

        for player in controller.get_all_players():
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

    def display_generic_info(self, player: Player, msg: str):
        self.side_panel.turn_label.setText(f"{player.name}'s turn")
        self.side_panel.main_label.setText(msg)
        if player.is_human:
            self.side_panel.action_label.setText("")
        else:
            self.side_panel.action_label.setText(f"{player} is thinking")
        self.toggle_main_action_btns(False)

    def display_round_info(self, controller: GameController, player: Player, dice_info: Tuple[int, int, int]):
        d1, d2, total = dice_info
        self.side_panel.turn_label.setText(f"{player.name}'s turn")
        self.side_panel.main_label.setText(f"Dice rolled: {d1} + {d2} = {total}\nWhat would you like to do?")

        # Actions
        self.toggle_main_action_btns(True)
        buildable = controller.get_buildable_options(player)
        can_build = buildable[Buildable.ROAD] or buildable[Buildable.SETTLEMENT] or buildable[Buildable.CITY]
        self.side_panel.action_label.setText("Click on the board to build" if can_build else "")
        self.side_panel.dev_btn.setEnabled(buildable[Buildable.DEVELOPMENT_CARD] or len(player.development_cards) > 0)
        self.side_panel.trade_btn.setEnabled(sum(player.resources.values()) > 0)
        self.side_panel.trade_btn.setEnabled(False)  # TODO: Add trading
        self.side_panel.dev_btn.setEnabled(False)  # TODO: Add development cards
        self.side_panel.end_turn_btn.clicked.connect(lambda: self.turnMade.emit(True))

    def display_round_info_ai_start(self, player: Player, dice_info: Tuple[int, int, int], msg: str):
        d1, d2, total = dice_info
        self.side_panel.turn_label.setText(f"{player.name}'s turn")
        self.side_panel.main_label.setText(f"Dice rolled: {d1} + {d2} = {total}")
        self.side_panel.action_label.setText(self.word_wrap(msg))
        self.toggle_main_action_btns(False)

    def show_resource_chooser(self, player, num_resources: int, title: str,
                              resource_caps: ResourceCount | None = None):

        selection_widget = self.resource_selector_widget
        quantity_btns: Dict[Resource, Tuple[QLabel, QToolButton, QToolButton]] = {
            Resource.WOOD: (selection_widget.wood_quantity, selection_widget.wood_quantity_dec,
                            selection_widget.wood_quantity_inc),
            Resource.BRICK: (selection_widget.brick_quantity, selection_widget.brick_quantity_dec,
                             selection_widget.brick_quantity_inc),
            Resource.SHEEP: (selection_widget.sheep_quantity, selection_widget.sheep_quantity_dec,
                             selection_widget.sheep_quantity_inc),
            Resource.WHEAT: (selection_widget.wheat_quantity, selection_widget.wheat_quantity_dec,
                             selection_widget.wheat_quantity_inc),
            Resource.ORE: (selection_widget.ore_quantity, selection_widget.ore_quantity_dec,
                           selection_widget.ore_quantity_inc)
        }
        chosen: ResourceCount = {res: 0 for res in Resource}

        if resource_caps is None:
            resource_caps = {res: num_resources for res in Resource}

        self.side_panel.turn_label.setText(f"{player.name}'s turn")
        self.side_panel.main_label.setText(title)
        self.side_panel.action_label.setText(
            f"You need to select {num_resources} more resource{'s' if num_resources > 1 else ''}."
        )

        self.toggle_main_action_btns(False)
        self.side_panel.action_btn_layout.addWidget(selection_widget)

        # Bind buttons
        def update_labels():
            total_remaining = num_resources - sum(chosen.values())
            self.side_panel.action_label.setText(
                f"You need to select {total_remaining} more resource{'s' if total_remaining != 1 else ''}."
            )
            # Disable buttons that can't be used
            for res, (_, dec, inc) in quantity_btns.items():
                dec.setEnabled(chosen[res] > 0)
                inc.setEnabled(chosen[res] < resource_caps[res] and total_remaining > 0)

            selection_widget.submit_btn.setEnabled(total_remaining == 0)

        for res, (_, dec_btn, inc_btn) in quantity_btns.items():
            inc_btn.clicked.connect(lambda _, r=res: increase(r))
            dec_btn.clicked.connect(lambda _, r=res: decrease(r))

        def increase(res: Resource):
            total_remaining = num_resources - sum(chosen.values())
            if total_remaining > 0 and chosen[res] < resource_caps[res]:
                chosen[res] += 1
                update_quantity_display(res)
                update_labels()

        def decrease(res: Resource):
            if chosen[res] > 0:
                chosen[res] -= 1
                update_quantity_display(res)
                update_labels()

        def update_quantity_display(res: Resource):
            quantity_btns[res][0].setText(str(chosen[res]))

        def submit():
            self.canvas.selectionMade.emit(chosen)
            self.side_panel.action_btn_layout.removeWidget(selection_widget)
            selection_widget.setParent(None)

        selection_widget.submit_btn.clicked.connect(submit)

        update_labels()

        for res in Resource:
            update_quantity_display(res)
