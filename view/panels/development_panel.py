from itertools import groupby
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem, QWidget

from ai.actions import Action, ActionType
from controllers.GameController import GameController
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCard, DevelopmentCardType
from view.qt_compat import disconnect_signal

if TYPE_CHECKING:
    from view.MainWindow import MainWindow


# noinspection PyProtectedMember,PyUnresolvedReferences
class DevelopmentPanel:

    def __init__(self, window: "MainWindow", development_manager_widget: QWidget):
        self.window = window
        self.development_manager_widget = development_manager_widget

    def show_development_menu(
        self,
        controller: GameController,
        player: Player,
        played_dev_card: bool,
        back_action,
        pre_roll_mode: bool = False,
    ) -> None:
        """Show the development card menu for the current player."""
        self.window.canvas.display_board(controller)
        development_manager = self.development_manager_widget
        development_manager.setParent(self.window.main_menu)

        self.window.toggle_main_action_btns(False)
        self.window.minimise_spacer()
        self.window.main_menu.action_btn_layout.addWidget(development_manager)
        self.window.main_menu.main_label.hide()
        self.window.main_menu.action_label.setText(
            "You already played a card this turn." if played_dev_card else "Available Cards:")
        self.window._set_turn_label(player)

        def clean_up():
            self.window.main_menu.action_btn_layout.removeWidget(development_manager)
            development_manager.setParent(None)
            self.window.restore_spacer()
            self.window.main_menu.main_label.show()
            self.window.set_debug_tutor_shortcut_finalizer(None)

        def back():
            clean_up()
            back_action(played_dev_card)

        development_manager.card_list.clear()
        cards_by_type = {
            k: list(g)
            for k, g in groupby(
                sorted(player.development_cards, key=lambda c: c.card_type.value, reverse=True),
                key=lambda c: c.card_type,
            )
        }

        card_tooltips = {
            DevelopmentCardType.KNIGHT: "Play to move the robber and increase your army size",
            DevelopmentCardType.VICTORY_POINT: "Adds 1 hidden victory point to your total automatically",
            DevelopmentCardType.ROAD_BUILDING: "Play to build up to 2 free roads anywhere on the board",
            DevelopmentCardType.YEAR_OF_PLENTY: "Play to take any 2 resources from the bank",
            DevelopmentCardType.MONOPOLY: "Play to claim all cards of one resource type from all players",
        }

        for card_type, cards in cards_by_type.items():
            for card in cards:
                name = card.card_type.name.title().replace("_", " ")

                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, card)
                item.setToolTip(card_tooltips.get(card.card_type, ""))

                if card.card_type == DevelopmentCardType.VICTORY_POINT:
                    item.setText(f"{name} - Used Automatically")
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                else:
                    if card.playable:
                        item.setText(f"{name} - Playable")
                    else:
                        item.setText(f"{name} - Just bought")
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)

                development_manager.card_list.addItem(item)

                if played_dev_card:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)

        def card_double_clicked(card_item: QListWidgetItem):
            selected_card: DevelopmentCard = card_item.data(Qt.ItemDataRole.UserRole)
            if pre_roll_mode:
                clean_up()
                back_action(selected_card.card_type)
            else:
                self.window.turnMade.emit(Action(ActionType.PLAY_DEV_CARD, selected_card.card_type))
                clean_up()

        def buy_card():
            clean_up()
            self.window.turnMade.emit(Action(ActionType.BUY_DEV_CARD))

        can_afford_card = controller.get_buildable_options(player)[Buildable.DEVELOPMENT_CARD]

        disconnect_signal(development_manager.card_list.itemDoubleClicked)
        development_manager.card_list.itemDoubleClicked.connect(card_double_clicked)

        if pre_roll_mode:
            development_manager.back_btn.setText("Roll Dice")
            development_manager.buy_btn.hide()
        else:
            development_manager.back_btn.setText("Go Back")
            development_manager.buy_btn.show()

        self.window.set_debug_tutor_shortcut_finalizer(clean_up)
        self.window.safe_connect(development_manager.back_btn, back)
        development_manager.buy_btn.setEnabled(can_afford_card)
        self.window.safe_connect(development_manager.buy_btn, buy_card)
