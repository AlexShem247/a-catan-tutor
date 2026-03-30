from itertools import groupby
from typing import Dict, Tuple, List, Callable, Optional

from PyQt6 import uic
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter, QLabel, QToolButton, QListWidgetItem, QSpacerItem,
    QSizePolicy, QPushButton
)

from GameController import GameController
from ai.ai_utils.explanations import ActionExplanation, ExplanationTemplate
from game.Edge import Edge
from game.Player import PlayerNumber, Player
from game.PlayerAssets import Buildable, DevelopmentCardType, DevelopmentCard
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from view.SquareCanvas import SquareCanvas
from config.view_constants import CROWN_SYM
from view.View import GameMode
from view.display_utils import format_counter_offer, get_player_lead_status


class MainWindow(QMainWindow):
    SIDE_PANEL_WIDTH = 320
    LABEL_LINE_LENGTH = 38
    startGame = pyqtSignal(object)
    turnMade = pyqtSignal(object)
    tradeDecisionMade = pyqtSignal(object)
    resourcesPicked = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Settlers of Catan")

        # Central widget
        central = QWidget(self)
        self.setCentralWidget(central)

        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Splitter
        self.splitter_layout = QSplitter(Qt.Orientation.Horizontal, self)
        layout.addWidget(self.splitter_layout)

        # Canvas
        self.canvas = SquareCanvas()
        self.splitter_layout.addWidget(self.canvas)

        # Side panel
        self.main_menu = uic.loadUi("view/ui/main_menu.ui")
        self.main_menu.setMinimumWidth(0)
        self.main_menu.setMaximumWidth(self.SIDE_PANEL_WIDTH * 2)
        self.splitter_layout.addWidget(self.main_menu)
        self.splitter_layout.setSizes([1000, self.SIDE_PANEL_WIDTH])

        # Prevent canvas from being squashed too much
        self.splitter_layout.setStretchFactor(0, 1)
        self.splitter_layout.setStretchFactor(1, 0)

        # Tutor panel
        self.tutor_menu = uic.loadUi("view/ui/tutor_menu.ui")
        self.tutor_menu.setMinimumWidth(0)
        self.tutor_menu.setMaximumWidth(self.SIDE_PANEL_WIDTH * 2)

        self.resource_selector_widget = uic.loadUi("view/ui/resource_selector.ui")
        self.trade_designer_widget = uic.loadUi("view/ui/trade_designer.ui")
        self.select_trade_widget = uic.loadUi("view/ui/select_trade.ui")
        self.trade_manager_widget = uic.loadUi("view/ui/trade_manager.ui")
        self.development_manager_widget = uic.loadUi("view/ui/development_manager.ui")
        self.development_manager_widget = uic.loadUi("view/ui/development_manager.ui")
        self.results_menu = uic.loadUi("view/ui/results_menu.ui")
        self.start_menu = uic.loadUi("view/ui/start_menu.ui")

        self.rule_window = uic.loadUi("view/ui/rules_window.ui")
        self.safe_connect(self.start_menu.help_btn, self.show_rules)
        self.safe_connect(self.main_menu.help_btn, self.show_rules)

        self.verticalSpacer = self.find_last_vertical_spacer()
        self.active_trade_preview_widget: QWidget | None = None
        self.safe_connect(self.main_menu.end_turn_btn, lambda: self.turnMade.emit(True))

    def safe_connect(self, button: QToolButton | QPushButton, slot: Callable):
        try:
            button.clicked.disconnect()  # type: ignore[attr-defined]
        except TypeError:
            pass
        button.clicked.connect(slot)

    def show_rules(self):
        # Show the rule window
        self.rule_window.show()
        self.rule_window.raise_()  # Bring it to the front
        self.rule_window.activateWindow()  # Focus it

    def find_last_vertical_spacer(self) -> QSpacerItem | None:
        last_spacer = None
        layout = self.main_menu.frame.layout()
        if layout is None:
            return None

        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.spacerItem() is not None:
                last_spacer = item.spacerItem()
        self.verticalSpacer = last_spacer
        return last_spacer

    def minimise_spacer(self):
        """Shrinks self.verticalSpacer to zero size, effectively hiding it."""
        if getattr(self, "verticalSpacer", None) is None:
            return

        spacer = self.verticalSpacer
        if not hasattr(spacer, "_original_size"):
            spacer._original_size = (
                spacer.geometry().width(),
                spacer.geometry().height(),
                spacer.sizePolicy().horizontalPolicy(),
                spacer.sizePolicy().verticalPolicy()
            )

        spacer.changeSize(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        if self.main_menu.frame.layout() is not None:
            self.main_menu.frame.layout().update()

    def restore_spacer(self):
        """Restores self.verticalSpacer to its original size and size policy."""
        if getattr(self, "verticalSpacer", None) is None:
            return

        spacer = self.verticalSpacer
        if not hasattr(spacer, "_original_size"):
            return

        w, h, h_policy, v_policy = getattr(spacer, "_original_size")
        spacer.changeSize(w, h, h_policy, v_policy)
        if self.main_menu.frame.layout() is not None:
            self.main_menu.frame.layout().update()

    def toggle_main_action_btns(self, show: bool):
        for i in range(self.main_menu.action_btn_layout.count()):
            widget: QWidget = self.main_menu.action_btn_layout.itemAt(i).widget()
            if widget:
                if show:
                    widget.show()
                else:
                    widget.hide()

    def closeEvent(self, _):
        quit()

    def display_resources(self, controller: GameController):
        # Fill in bank labels
        bank_labels: Dict[Resource, QLabel] = {
            res: getattr(self.main_menu, f"bank_{res.name.lower()}_label")
            for res in Resource
        }

        for res, label in bank_labels.items():
            label.setText(str(controller.get_bank_resources()[res]))

        self.main_menu.bank_dev_label.setText(str(controller.get_development_deck().size()))

        # Fill in opponent labels
        stat_suffixes = {"name": "", "victory_points": "vic_", "num_resources": "res_",
                         "development_cards": "dev_", "army_size": "army_", "longest_road": "road_"}
        opponent_prefixes: Dict[PlayerNumber, str] = {
            PlayerNumber.P2: "p2", PlayerNumber.P3: "p3", PlayerNumber.P4: "p4"
        }

        opponent_labels: Dict[PlayerNumber, Dict[str, QLabel]] = {
            pn: {
                stat: getattr(self.main_menu, f"{opponent_prefixes[pn]}_{suffix}label")
                for stat, suffix in stat_suffixes.items()
            }
            for pn in opponent_prefixes
        }

        player_labels: Dict[Resource, QLabel] = {
            res: getattr(self.main_menu, f"{res.name.lower()}_label")
            for res in Resource
        }

        for player in controller.get_all_players():
            num = player.player_number
            if num == PlayerNumber.P1:
                for res, label in player_labels.items():
                    label.setText(str(player.resources[res]))

                visible_vp, true_vp = player.calc_victory_points()
                true_vp_str = f" ({true_vp})" if visible_vp != true_vp else ""
                longest_road_crown = CROWN_SYM if player.has_longest_road else ""
                army_crown = CROWN_SYM if player.has_largest_army else ""
                lead_status = get_player_lead_status(player)

                self.main_menu.longest_road_label.setText(
                    f"Longest Road:\t{player.longest_road_length} {longest_road_crown}"
                )
                self.main_menu.army_size_label.setText(
                    f"Army Size:\t{player.army_size} {army_crown}"
                )
                self.main_menu.victory_points_label.setText(
                    f"Victory Points:\t{visible_vp}{true_vp_str} {lead_status}"
                )
            else:
                labels = opponent_labels[num]
                status = get_player_lead_status(player)
                if status:
                    labels["name"].setText(f"{player.name} {status}")
                    labels["name"].setToolTip(f"{player.name} is currently in the lead")
                else:
                    labels["name"].setText(player.name)
                    labels["name"].setToolTip(None)
                labels["victory_points"].setText(str(player.calc_victory_points()[0]))
                labels["num_resources"].setText(str(sum(player.resources.values())))
                labels["development_cards"].setText(str(len(player.development_cards)))
                labels["army_size"].setText(str(player.army_size))
                labels["longest_road"].setText(str(player.longest_road_length))

    def display_generic_info(self, player: Player, msg: str):
        self.main_menu.turn_label.setText(f"{player.name}'s turn")
        self.main_menu.main_label.show()
        self.main_menu.main_label.setText(msg)
        self.main_menu.action_label.show()
        self.main_menu.action_label.setText("" if player.is_human else f"{player} is thinking")
        self.toggle_main_action_btns(False)

    def display_round_info(self, controller: GameController, player: Player, dice_info: Tuple[int, int, int],
                           played_dev_card: bool = False):
        self.canvas.interactive_shapes.clear()
        self.canvas.disable_interactivity = False
        self.canvas.display_board(controller)
        self.display_resources(controller)

        d1, d2, total = dice_info
        self.main_menu.turn_label.setText(f"{player.name}'s turn")
        self.main_menu.main_label.setText(f"Dice rolled: {d1} + {d2} = {total}\nWhat would you like to do?")

        # Actions
        self.toggle_main_action_btns(True)

        self.draw_buildables_if_can_build(controller, player)
        can_afford_card = controller.get_buildable_options(player)[Buildable.DEVELOPMENT_CARD]
        self.main_menu.dev_btn.setEnabled(can_afford_card or len(player.development_cards) > 0)
        self.main_menu.trade_btn.setEnabled(sum(player.resources.values()) > 0)
        self.safe_connect(self.main_menu.trade_btn, lambda: self.display_trade_menu(
            controller, player, lambda: self.display_round_info(controller, player, dice_info, played_dev_card)))
        self.safe_connect(self.main_menu.dev_btn, lambda: self.show_development_menu(
            controller, player, played_dev_card,
            lambda played: self.display_round_info(controller, player, dice_info, played)))

    def open_tutor_menu(self, open_menu: bool):
        if open_menu:
            # Avoid adding it twice
            if self.splitter_layout.indexOf(self.tutor_menu) == -1:
                self.tutor_menu.setMinimumWidth(0)
                self.tutor_menu.setMaximumWidth(self.SIDE_PANEL_WIDTH * 2)
                self.splitter_layout.insertWidget(0, self.tutor_menu)
            self.tutor_menu.show()
            self.splitter_layout.setSizes([int(self.SIDE_PANEL_WIDTH * 0.8), 1000, self.SIDE_PANEL_WIDTH])

        else:
            if self.splitter_layout.indexOf(self.tutor_menu) != -1:
                self.tutor_menu.hide()
                self.tutor_menu.setParent(None)
            self.splitter_layout.setSizes([1000, self.SIDE_PANEL_WIDTH])

    def display_explanation(self, player: Player, dice_info: Optional[Tuple[int, int, int]],
                            explanation: ActionExplanation):
        self.display_round_info_ai_start(player, dice_info, "")
        self.toggle_main_action_btns(False)

        action, explanation_txt = explanation.generate_text_concise()
        self.tutor_menu.action_label.setText(action)
        self.tutor_menu.explanation_edit.setText(explanation_txt)
        self.main_menu.action_label.setText(f"{player} is thinking")

        self.tutor_menu.continue_btn.setEnabled(True)
        self.tutor_menu.continue_btn.setText("Continue")
        self.safe_connect(self.tutor_menu.continue_btn, lambda: self.turnMade.emit(True))

        self.tutor_menu.explain_btn.setEnabled(True)
        self.tutor_menu.explain_btn.setText("Why this move?")

        showing_comparative = False

        def toggle_explanation_detail():
            nonlocal showing_comparative

            if showing_comparative:
                action_, explanation_txt_ = explanation.generate_text_concise()
                self.tutor_menu.action_label.setText(action_)
                self.tutor_menu.explanation_edit.setText(explanation_txt_)
                self.tutor_menu.explain_btn.setText("Why this move?")
                showing_comparative = False
            else:
                self.tutor_menu.explanation_edit.setText(explanation.generate_text_detail())
                self.tutor_menu.explain_btn.setText("Show less")
                showing_comparative = True

        self.safe_connect(self.tutor_menu.explain_btn, toggle_explanation_detail)

        self.canvas.render_planned_builds(explanation.get_visual_build_plan())
        self.display_trade_preview(explanation)

    def clear_trade_preview(self):
        if self.active_trade_preview_widget is None:
            return

        self.main_menu.action_btn_layout.removeWidget(self.active_trade_preview_widget)
        self.active_trade_preview_widget.setParent(None)
        self.active_trade_preview_widget = None
        self.restore_spacer()

    def display_trade_preview(self, explanation: ActionExplanation):
        self.clear_trade_preview()

        template = explanation.metadata.get("template") or explanation.chosen_candidate.metadata.get("template")
        if template == ExplanationTemplate.TRADE_PARTNER:
            self._display_trade_partner_preview(explanation)
        elif template == ExplanationTemplate.TRADE_RESPONSE:
            self._display_trade_response_preview(explanation)
        elif template == ExplanationTemplate.ROBBER_TARGET:
            self._display_robber_preview(explanation)
        elif template == ExplanationTemplate.DISCARD_RESOURCES:
            self._display_discard_preview(explanation)

    def _display_trade_partner_preview(self, explanation: ActionExplanation):
        partner_name = explanation.chosen_candidate.metadata.get("partner_name", "player")
        payment = explanation.chosen_candidate.metadata.get("payment", {})
        buying = explanation.chosen_candidate.metadata.get("buying", {})

        select_trade = self.select_trade_widget
        select_trade.setParent(self.main_menu)
        self.minimise_spacer()
        self.main_menu.action_btn_layout.addWidget(select_trade)
        self.active_trade_preview_widget = select_trade

        self.main_menu.action_label.setText(f"Selected Trade for {format_counter_offer(buying, buying)}:")
        select_trade.trade_list.clear()
        select_trade.trade_list.show()
        select_trade.submit_btn.hide()

        item = QListWidgetItem(f"Trade {partner_name}: {format_counter_offer(payment, payment)}")
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        select_trade.trade_list.addItem(item)
        select_trade.trade_list.setCurrentRow(0)
        select_trade.trade_list.setEnabled(False)

    def _display_trade_response_preview(self, explanation: ActionExplanation):
        trade_manager = self.trade_manager_widget
        trade_manager.setParent(self.main_menu)
        self.minimise_spacer()
        self.main_menu.action_btn_layout.addWidget(trade_manager)
        self.active_trade_preview_widget = trade_manager

        decision = explanation.chosen_candidate.metadata.get("decision")
        opponent_name = explanation.chosen_candidate.metadata.get("opponent_name", "player")
        requested = explanation.chosen_candidate.metadata.get("payment", {})
        original_offer = explanation.chosen_candidate.metadata.get("selling_to_us", {})
        counter_offer = explanation.chosen_candidate.metadata.get("counter_payment")
        shown_offer = counter_offer if decision == "counter" and counter_offer is not None else original_offer

        self.main_menu.main_label.setText(f"Trade Offer from {opponent_name}")
        self.main_menu.action_label.setText(
            f"{opponent_name} is buying {format_counter_offer(requested, requested)} for:"
        )

        for res in Resource:
            getattr(trade_manager, f"{res.name.lower()}_quantity").setText(str(shown_offer.get(res, 0)))
            getattr(trade_manager, f"{res.name.lower()}_quantity_dec").setEnabled(False)
            getattr(trade_manager, f"{res.name.lower()}_quantity_inc").setEnabled(False)

        trade_manager.accept_btn.show()
        trade_manager.decline_btn.show()
        trade_manager.accept_btn.setEnabled(False)
        trade_manager.decline_btn.setEnabled(False)

        if decision == "accept":
            trade_manager.accept_btn.setText("Accepted")
            trade_manager.decline_btn.hide()
        elif decision == "counter":
            trade_manager.accept_btn.setText("Counteroffer")
            trade_manager.decline_btn.hide()
        else:
            trade_manager.decline_btn.setText("Rejected")
            trade_manager.accept_btn.hide()

    def _display_robber_preview(self, explanation: ActionExplanation):
        target_player = explanation.chosen_candidate.metadata.get("target_player_name")
        self.main_menu.main_label.setText("Move The Robber")
        if target_player:
            self.main_menu.action_label.setText(
                f"Move the robber to the highlighted tile and steal from {target_player} if possible."
            )
        else:
            self.main_menu.action_label.setText("Move the robber to the highlighted tile.")

    def _display_discard_preview(self, explanation: ActionExplanation):
        discard = explanation.chosen_candidate.metadata.get("discard_resources", {})
        total_to_discard = sum(discard.values())

        chooser = self.resource_selector_widget
        chooser.setParent(self.main_menu)
        self.minimise_spacer()
        self.main_menu.action_btn_layout.addWidget(chooser)
        self.active_trade_preview_widget = chooser

        self.main_menu.main_label.setText("The Robber Has Been Rolled!")
        self.main_menu.action_label.setText(
            f"Discard {total_to_discard} resource{'s' if total_to_discard != 1 else ''}."
        )

        for res in Resource:
            getattr(chooser, f"{res.name.lower()}_quantity").setText(str(discard.get(res, 0)))
            getattr(chooser, f"{res.name.lower()}_quantity_dec").setEnabled(False)
            getattr(chooser, f"{res.name.lower()}_quantity_inc").setEnabled(False)

        chooser.submit_btn.hide()

    def create_quantity_handlers(
            self,
            current_counts: ResourceCount,
            quantity_btns: Dict[Resource, Tuple[QLabel, QToolButton, QToolButton]],
            caps: ResourceCount | None = None,
            on_update: Callable[[], None] | None = None,
            zero_other: Tuple[ResourceCount, Dict[Resource, Tuple[QLabel, QToolButton, QToolButton]]] | None = None
    ):
        if caps is None:
            caps = {res: float("inf") for res in current_counts}

        def update_label(res: Resource):
            quantity_btns[res][0].setText(str(current_counts[res]))

        def increase(res: Resource):
            if current_counts[res] < caps[res]:
                current_counts[res] += 1
                update_label(res)

                if zero_other is not None:
                    # Reset other dict
                    zero_other[0][res] = 0
                    zero_other[1][res][0].setText("0")

                if on_update:
                    on_update()

        def decrease(res: Resource):
            if current_counts[res] > 0:
                current_counts[res] -= 1
                update_label(res)
                if on_update:
                    on_update()

        # Connect buttons
        for res, (_, dec_btn, inc_btn) in quantity_btns.items():
            self.safe_connect(inc_btn, lambda _, r=res: increase(r))
            self.safe_connect(dec_btn, lambda _, r=res: decrease(r))

        # Initialise labels
        for res in current_counts:
            update_label(res)

    def display_trade_menu(self, controller: GameController, player: Player, back_action):
        self.display_resources(controller)
        trade_designer = self.trade_designer_widget
        trade_designer.setParent(self.main_menu)

        # Map resources to labels/buttons
        def make_btns(prefix: str):
            return {
                res: (
                    getattr(trade_designer, f"{prefix}_{res.name.lower()}_quantity"),
                    getattr(trade_designer, f"{prefix}_{res.name.lower()}_quantity_dec"),
                    getattr(trade_designer, f"{prefix}_{res.name.lower()}_quantity_inc"),
                )
                for res in Resource
            }

        selling_btns = make_btns("selling")
        buying_btns = make_btns("buying")

        # UI setup
        self.main_menu.main_label.hide()
        self.main_menu.action_label.hide()
        self.toggle_main_action_btns(False)
        self.minimise_spacer()
        self.main_menu.action_btn_layout.addWidget(trade_designer)

        # Trade state
        selling: ResourceCount = {res: 0 for res in Resource}
        buying: ResourceCount = {res: 0 for res in Resource}

        def update_buttons():
            # Selling buttons capped by inventory
            for res, (_, dec_btn, inc_btn) in selling_btns.items():
                dec_btn.setEnabled(selling[res] > 0)
                inc_btn.setEnabled(selling[res] < player.resources[res])

            # Buying buttons
            for res, (_, dec_btn, inc_btn) in buying_btns.items():
                dec_btn.setEnabled(buying[res] > 0)
                inc_btn.setEnabled(True)

            # Validate trade
            trade_incomplete = all(v == 0 for v in selling.values()) or all(v == 0 for v in buying.values())
            valid_bank_trade = (not trade_incomplete and
                                controller.try_trade_with_bank(player, selling, buying, use_resources=False))
            valid_player_trade = not trade_incomplete

            trade_designer.bank_trade_btn.setEnabled(valid_bank_trade)
            trade_designer.player_trade_btn.setEnabled(valid_player_trade)

        # Bind quantity handlers
        self.create_quantity_handlers(
            current_counts=selling,
            quantity_btns=selling_btns,
            caps=player.resources,
            on_update=update_buttons,
            zero_other=(buying, buying_btns)
        )

        self.create_quantity_handlers(
            current_counts=buying,
            quantity_btns=buying_btns,
            on_update=update_buttons,
            zero_other=(selling, selling_btns)
        )

        update_buttons()

        # Button actions
        def terminate_trade():
            self.main_menu.main_label.show()
            self.main_menu.action_label.show()
            self.restore_spacer()
            self.main_menu.action_btn_layout.removeWidget(trade_designer)
            trade_designer.setParent(None)
            back_action()

        def trade_with_bank():
            controller.try_trade_with_bank(player, selling, buying)
            self.display_trade_menu(controller, player, back_action)
            self.draw_buildables_if_can_build(controller, player)

        def trade_with_players():
            willing_players = controller.trade_with_players(player, selling, buying)
            self.main_menu.action_btn_layout.removeWidget(trade_designer)
            trade_designer.setParent(None)
            self.select_player_to_trade(controller, player, selling, buying, willing_players,
                                        lambda: self.display_trade_menu(controller, player, back_action))

        self.safe_connect(trade_designer.terminate_btn, terminate_trade)
        self.safe_connect(trade_designer.bank_trade_btn, trade_with_bank)
        self.safe_connect(trade_designer.player_trade_btn, trade_with_players)

    def select_player_to_trade(self, controller: GameController, player: Player, selling: ResourceCount,
                               buying: ResourceCount, willing_players: List[Tuple[Player, ResourceCount | None]],
                               back_action):
        self.display_resources(controller)
        self.clear_trade_preview()
        select_trade = self.select_trade_widget
        select_trade.setParent(self.main_menu)

        # Disable main action buttons and show the trade selector
        self.main_menu.action_btn_layout.addWidget(select_trade)
        select_trade.trade_list.clear()
        select_trade.trade_list.setEnabled(True)
        self.main_menu.action_label.show()

        # Case 1: no players are willing to trade
        if not willing_players:
            self.main_menu.action_label.setText("No players are willing to trade with you right now.")
            select_trade.submit_btn.setText("Go back")
            select_trade.trade_list.hide()

            def back():
                self.main_menu.action_btn_layout.removeWidget(select_trade)
                select_trade.setParent(None)
                back_action()

            self.safe_connect(select_trade.submit_btn, back)
            return

        # Case 2: show available trade offers
        self.main_menu.action_label.setText(f"Available Trades for {format_counter_offer(buying, buying)}:")
        select_trade.submit_btn.setText("Cancel")
        select_trade.submit_btn.show()
        select_trade.trade_list.show()

        # Populate the list with trade offers
        for p, counter in willing_players:
            if counter is None:
                can_afford = True
                trade_str = format_counter_offer(selling, selling)
            else:
                can_afford = all(
                    player.resources.get(res, 0) >= amt
                    for res, amt in counter.items()
                )
                trade_str = format_counter_offer(selling, counter)

            item = QListWidgetItem(f"Trade {p.name}: {trade_str}")

            # Disable trades the player cannot afford
            if not can_afford:
                item.setText(item.text() + " (CANNOT AFFORD)")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)

            # Store the trade data on the item
            item.setData(Qt.ItemDataRole.UserRole, (p, counter) if can_afford else None)
            select_trade.trade_list.addItem(item)

        # Automatically select the first affordable trade
        for i in range(select_trade.trade_list.count()):
            if select_trade.trade_list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled:
                select_trade.trade_list.setCurrentRow(i)
                break

        # Accept a trade when the user double-clicks an item
        def accept_trade(trade: QListWidgetItem):
            nonlocal selling
            deal = trade.data(Qt.ItemDataRole.UserRole)
            if not deal:
                return

            self.main_menu.action_btn_layout.removeWidget(select_trade)
            select_trade.setParent(None)

            buying_player, counter_offer = deal
            if counter_offer is not None:
                selling = counter_offer  # Player accepted counteroffer

            controller.trade_between_players(player, selling, buying_player, buying)
            self.draw_buildables_if_can_build(controller, player)
            back_action()

        try:
            select_trade.trade_list.itemDoubleClicked.disconnect()
        except TypeError:
            pass
        select_trade.trade_list.itemDoubleClicked.connect(accept_trade)

        # Cancel and return to the previous action
        def cancel():
            self.main_menu.action_btn_layout.removeWidget(select_trade)
            select_trade.setParent(None)
            back_action()

        self.safe_connect(select_trade.submit_btn, cancel)

    def display_round_info_ai_start(self, player: Player, dice_info: Optional[Tuple[int, int, int]], msg: str):
        self.clear_trade_preview()
        if dice_info:
            d1, d2, total = dice_info
            self.main_menu.main_label.setText(f"Dice rolled: {d1} + {d2} = {total}")

        if msg == "":
            msg = f"{player.name} ended their turn without taking any further actions."

        self.main_menu.turn_label.setText(f"{player.name}'s turn")
        self.main_menu.action_label.setText(msg)
        self.toggle_main_action_btns(False)

        self.tutor_menu.action_label.setText("Wait For Your Turn")
        self.tutor_menu.explanation_edit.setText("")
        self.tutor_menu.explain_btn.setEnabled(False)
        self.tutor_menu.continue_btn.setEnabled(False)

    def show_resource_chooser(self, player, num_resources: int, title: str,
                              resource_caps: ResourceCount | None = None):
        self.clear_trade_preview()

        selection_widget = self.resource_selector_widget
        selection_widget.setParent(self.main_menu)

        quantity_btns = {
            res: (
                getattr(selection_widget, f"{res.name.lower()}_quantity"),
                getattr(selection_widget, f"{res.name.lower()}_quantity_dec"),
                getattr(selection_widget, f"{res.name.lower()}_quantity_inc"),
            )
            for res in Resource
        }

        chosen: ResourceCount = {res: 0 for res in Resource}
        if resource_caps is None:
            resource_caps = {res: num_resources for res in Resource}

        self.main_menu.turn_label.setText(f"{player.name}'s turn")
        self.main_menu.main_label.setText(title)
        self.main_menu.action_label.setText(
            f"You need to select {num_resources} more resource{'s' if num_resources != 1 else ''}."
        )

        self.toggle_main_action_btns(False)
        self.main_menu.action_btn_layout.addWidget(selection_widget)
        selection_widget.submit_btn.show()

        def update_labels():
            total_remaining = num_resources - sum(chosen.values())
            self.main_menu.action_label.setText(
                f"You need to select {total_remaining} more resource{'s' if total_remaining != 1 else ''}."
            )
            for res, (_, dec, inc) in quantity_btns.items():
                dec.setEnabled(chosen[res] > 0)
                inc.setEnabled(chosen[res] < resource_caps[res] and total_remaining > 0)
            selection_widget.submit_btn.setEnabled(total_remaining == 0)

        self.create_quantity_handlers(
            current_counts=chosen,
            quantity_btns=quantity_btns,
            caps=resource_caps,
            on_update=update_labels
        )

        def submit():
            self.resourcesPicked.emit(chosen)
            self.main_menu.action_btn_layout.removeWidget(selection_widget)
            selection_widget.setParent(None)

        self.safe_connect(selection_widget.submit_btn, submit)
        update_labels()

    def display_trade_manager(self, player: Player, selling: ResourceCount,
                              buying: ResourceCount, selling_player: Player):

        self.clear_trade_preview()
        trade_manager = self.trade_manager_widget
        trade_manager.setParent(self.main_menu)

        selling_btns = {
            res: (
                getattr(trade_manager, f"{res.name.lower()}_quantity"),
                getattr(trade_manager, f"{res.name.lower()}_quantity_dec"),
                getattr(trade_manager, f"{res.name.lower()}_quantity_inc"),
            )
            for res in Resource
        }

        self.toggle_main_action_btns(False)
        self.minimise_spacer()
        self.main_menu.action_btn_layout.addWidget(trade_manager)
        self.main_menu.main_label.setText(f"Trade Offer from {selling_player.name}")
        self.main_menu.action_label.setText(
            f"{selling_player.name} is buying {format_counter_offer(buying, buying)} for:"
        )
        trade_manager.accept_btn.show()
        trade_manager.decline_btn.show()

        counter_offer = {res: selling.get(res, 0) for res in Resource}

        def update_buttons():
            can_afford = all(player.resources.get(res, 0) >= amt for res, amt in buying.items())
            modified = any(counter_offer[res] != selling.get(res, 0) for res in Resource)
            all_zero = all(v == 0 for v in counter_offer.values())

            trade_manager.accept_btn.setEnabled(can_afford and not all_zero)
            trade_manager.accept_btn.setText("Propose Counteroffer" if modified else "Accept")

            for res, (_, dec_btn, inc_btn) in selling_btns.items():
                dec_btn.setEnabled(counter_offer[res] > 0 and can_afford)
                inc_btn.setEnabled(can_afford)

            trade_manager.decline_btn.setEnabled(True)

            txt = f"{selling_player.name} is buying {format_counter_offer(buying, buying)} for:"
            if not can_afford:
                txt += "\nYou do not have the required resources for this trade."
            self.main_menu.action_label.setText(txt)

        self.create_quantity_handlers(
            current_counts=counter_offer,
            quantity_btns=selling_btns,
            on_update=update_buttons
        )

        def accept():
            trade_manager.accept_btn.setEnabled(False)
            trade_manager.decline_btn.setEnabled(False)
            modified = any(counter_offer[res] != selling.get(res, 0) for res in Resource)
            self.tradeDecisionMade.emit((True, counter_offer if modified else None))
            self.main_menu.action_btn_layout.removeWidget(trade_manager)
            trade_manager.setParent(None)
            self.restore_spacer()

        def decline():
            self.tradeDecisionMade.emit((False, None))
            self.main_menu.action_btn_layout.removeWidget(trade_manager)
            trade_manager.setParent(None)
            self.restore_spacer()

        self.safe_connect(trade_manager.accept_btn, accept)
        self.safe_connect(trade_manager.decline_btn, decline)
        update_buttons()

    def show_development_menu(self, controller: GameController, player: Player, played_dev_card: bool, back_action,
                              pre_roll_mode: bool = False):
        self.canvas.display_board(controller)
        development_manager = self.development_manager_widget
        development_manager.setParent(self.main_menu)

        self.toggle_main_action_btns(False)
        self.minimise_spacer()
        self.main_menu.action_btn_layout.addWidget(development_manager)
        self.main_menu.main_label.hide()
        self.main_menu.action_label.setText(
            "You already played a card this turn." if played_dev_card else "Available Cards:"
        )
        self.main_menu.turn_label.setText(f"{player.name}'s turn")

        def clean_up():
            self.main_menu.action_btn_layout.removeWidget(development_manager)
            development_manager.setParent(None)
            self.restore_spacer()
            self.main_menu.main_label.show()

        def back():
            clean_up()
            back_action(played_dev_card)

        # Show playable cards
        development_manager.card_list.clear()
        cards_by_type = {k: list(g) for k, g in groupby(
            sorted(player.development_cards, key=lambda c: c.card_type.value, reverse=True),
            key=lambda c: c.card_type
        )}

        # Define tooltips for each card type
        card_tooltips = {
            DevelopmentCardType.KNIGHT: "Play to move the robber and increase your army size",
            DevelopmentCardType.VICTORY_POINT: "Adds 1 hidden victory point to your total automatically",
            DevelopmentCardType.ROAD_BUILDING: "Play to build up to 2 free roads anywhere on the board",
            DevelopmentCardType.YEAR_OF_PLENTY: "Play to take any 2 resources from the bank",
            DevelopmentCardType.MONOPOLY: "Play to claim all cards of one resource type from all players"
        }

        for card_type, cards in cards_by_type.items():
            for card in cards:
                name = card.card_type.name.title().replace("_", " ")

                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, card)

                # Set tooltip based on card type
                tooltip = card_tooltips.get(card.card_type, "")
                item.setToolTip(tooltip)

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
                back()
            controller.play_development_card(player, selected_card.card_type)
            if not pre_roll_mode:
                self.display_resources(controller)
                self.show_development_menu(controller, player, True, back_action)

        def buy_card():
            controller.try_buy_development_card(player)
            self.display_resources(controller)
            self.show_development_menu(controller, player, played_dev_card, back_action)

        can_afford_card = controller.get_buildable_options(player)[Buildable.DEVELOPMENT_CARD]

        try:
            development_manager.card_list.itemDoubleClicked.disconnect()
        except TypeError:
            pass
        development_manager.card_list.itemDoubleClicked.connect(card_double_clicked)

        if pre_roll_mode:
            development_manager.back_btn.setText("Roll Dice")
            development_manager.buy_btn.hide()
        else:
            development_manager.back_btn.setText("Go Back")
            development_manager.buy_btn.show()

        self.safe_connect(development_manager.back_btn, back)
        development_manager.buy_btn.setEnabled(can_afford_card)
        self.safe_connect(development_manager.buy_btn, buy_card)

    def draw_buildables_if_can_build(self, controller, player):
        def build(selected_buildable: Vertex | Edge):
            match selected_buildable:
                case Edge():
                    controller.try_build_road(player, selected_buildable)
                case Vertex():
                    if selected_buildable.building is None:
                        controller.try_build_settlement(player, selected_buildable)
                    else:
                        controller.try_build_city(player, selected_buildable)

            self.canvas.interactive_shapes.clear()
            self.canvas.display_board(controller)
            self.display_resources(controller)
            self.draw_buildables_if_can_build(controller, player)

        buildable = controller.get_buildable_options(player)
        can_build = buildable[Buildable.ROAD] or buildable[Buildable.SETTLEMENT] or buildable[Buildable.CITY]
        if can_build:
            self.canvas.draw_buildables(buildable)
            try:
                self.canvas.selectionMade.disconnect()
            except TypeError:
                pass
            self.canvas.selectionMade.connect(build)
            self.main_menu.action_label.setText("Click on the board to build")
        else:
            self.main_menu.action_label.setText("")

    def display_results(self, controller: GameController):
        # Close tutor menu
        self.open_tutor_menu(False)

        self.canvas.interactive_shapes.clear()
        self.canvas.display_board(controller)
        self.display_resources(controller)

        # Add the new results menu
        sizes = self.splitter_layout.sizes()
        self.main_menu.setParent(None)
        self.splitter_layout.addWidget(self.results_menu)
        self.splitter_layout.setSizes([sizes[0], sizes[1]])

        # Map all labels into dictionaries by rank
        all_labels = {}
        for i in range(1, 5):
            all_labels[i] = {
                "score": getattr(self.results_menu, f"score_{i}"),
                "player": getattr(self.results_menu, f"player_label_{i}"),
                "settlements": getattr(self.results_menu, f"settlements_{i}"),
                "cities": getattr(self.results_menu, f"cities_{i}"),
                "longest_road": getattr(self.results_menu, f"longest_road_{i}"),
                "largest_army": getattr(self.results_menu, f"largest_army_{i}"),
                "victory_cards": getattr(self.results_menu, f"victory_cards_{i}")
            }

            # Clear previous values
            for label in all_labels[i].values():
                label.setText("")
                label.hide()

        # Sort players by victory points (descending)
        sorted_players = sorted(controller.get_all_players(), key=lambda p: p.calc_victory_points()[1], reverse=True)

        self.results_menu.winner_label.setText(sorted_players[0].name + "!")

        # Fill in results for each ranking
        for rank, player in enumerate(sorted_players, start=1):
            labels = all_labels[rank]

            # Score and player name
            labels["score"].setText(f"{rank}. {player.name}: {player.calc_victory_points()[1]} pts")
            labels["score"].show()
            labels["player"].setText(f"{player.name}: {player.calc_victory_points()[1]} pts")
            labels["player"].show()

            # Settlements
            if player.settlements:
                labels["settlements"].setText(f"Settlements: {len(player.settlements)}")
                labels["settlements"].show()

            # Cities
            if player.cities:
                labels["cities"].setText(f"Cities: {len(player.cities)}")
                labels["cities"].show()

            # Longest Road
            if player.has_longest_road:
                labels["longest_road"].setText(f"Longest Road: {player.longest_road_length}")
                labels["longest_road"].show()

            # Largest Army
            if player.has_largest_army:
                labels["largest_army"].setText(f"Largest Army: {player.army_size}")
                labels["largest_army"].show()

            # Victory Point Cards
            num_vp_cards = len(
                [c for c in player.development_cards if c.card_type == DevelopmentCardType.VICTORY_POINT])
            if num_vp_cards > 0:
                labels["victory_cards"].setText(f"Victory Card Points: {num_vp_cards}")
                labels["victory_cards"].show()

        def return_to_main_menu():
            # Remove results panel
            layout_sizes = self.splitter_layout.sizes()
            self.results_menu.setParent(None)

            # Restore main menu
            self.splitter_layout.addWidget(self.main_menu)
            self.splitter_layout.setSizes(layout_sizes)
            self.main_menu.show()

            # Reset the game controller and game state
            controller.start_game()

        # Bind buttons
        self.safe_connect(self.results_menu.main_menu_btn, return_to_main_menu)
        self.safe_connect(self.results_menu.quit_btn, lambda: self.closeEvent(QCloseEvent()))

    def display_start_screen(self):
        self.canvas.interactive_shapes.clear()
        self.canvas.display_start_screen()

        # Add the new results menu
        sizes = self.splitter_layout.sizes()
        self.main_menu.setParent(None)
        self.splitter_layout.addWidget(self.start_menu)
        self.splitter_layout.setSizes([sizes[0], sizes[1]])

        def play(game_mode: GameMode):
            # Remove results panel
            layout_sizes = self.splitter_layout.sizes()
            self.start_menu.setParent(None)

            # Restore main menu
            self.splitter_layout.addWidget(self.main_menu)
            self.splitter_layout.setSizes(layout_sizes)
            self.main_menu.show()

            self.startGame.emit(game_mode)

        self.safe_connect(self.start_menu.play_game_btn, lambda: play(GameMode.PLAY))
        self.safe_connect(self.start_menu.run_simulation_btn, lambda: play(GameMode.SIMULATION))
        self.safe_connect(self.start_menu.run_guided_btn, lambda: play(GameMode.GUIDED))
