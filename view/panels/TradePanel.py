from typing import Callable, Dict, Optional, Tuple, TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QListWidgetItem, QToolButton, QWidget

from controllers.GameController import GameController
from ai.actions import Action, ActionType
from ai.tutor.explanations import ActionExplanation, ExplanationTemplate
from game.Player import Player
from game.Resources import Resource, ResourceCount
from view.canvas.display_utils import format_counter_offer

if TYPE_CHECKING:
    from view.MainWindow import MainWindow


# noinspection PyProtectedMember,PyUnresolvedReferences
class TradePanel:
    def __init__(
        self,
        window: "MainWindow",
        resource_selector_widget: QWidget,
        trade_designer_widget: QWidget,
        select_trade_widget: QWidget,
        trade_manager_widget: QWidget,
    ):
        self.window = window
        self.resource_selector_widget = resource_selector_widget
        self.trade_designer_widget = trade_designer_widget
        self.select_trade_widget = select_trade_widget
        self.trade_manager_widget = trade_manager_widget
        self.active_trade_preview_widget: QWidget | None = None

    def clear_trade_preview(self) -> None:
        """Clear the trade preview."""
        if self.active_trade_preview_widget is None:
            return
        self.window.main_menu.action_btn_layout.removeWidget(self.active_trade_preview_widget)
        self.active_trade_preview_widget.setParent(None)
        self.active_trade_preview_widget = None
        self.window.restore_spacer()

    def display_trade_preview(self, explanation: ActionExplanation) -> None:
        """Display the trade preview."""
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
        elif template == ExplanationTemplate.YEAR_OF_PLENTY_RESOURCES:
            self._display_year_of_plenty_preview(explanation)
        elif template == ExplanationTemplate.MONOPOLY_RESOURCE:
            self._display_monopoly_preview(explanation)

    def _display_trade_partner_preview(self, explanation: ActionExplanation) -> None:
        """Display the trade partner preview."""
        partner_name = explanation.chosen_candidate.metadata.get("partner_name", "player")
        payment = explanation.chosen_candidate.metadata.get("payment", {})
        buying = explanation.chosen_candidate.metadata.get("buying", {})
        select_trade = self.select_trade_widget
        select_trade.setParent(self.window.main_menu)
        self.window.minimise_spacer()
        self.window.main_menu.action_btn_layout.addWidget(select_trade)
        self.active_trade_preview_widget = select_trade
        self.window.main_menu.action_label.setText(f"Selected Trade for {format_counter_offer(buying, buying)}:")
        select_trade.trade_list.clear()
        select_trade.trade_list.show()
        select_trade.submit_btn.hide()

        item = QListWidgetItem(f"Trade {partner_name}: {format_counter_offer(payment, payment)}")
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        select_trade.trade_list.addItem(item)
        select_trade.trade_list.setCurrentRow(0)
        select_trade.trade_list.setEnabled(False)

    def _display_trade_response_preview(self, explanation: ActionExplanation) -> None:
        """Display the trade response preview."""
        trade_manager = self.trade_manager_widget
        trade_manager.setParent(self.window.main_menu)
        self.window.minimise_spacer()
        self.window.main_menu.action_btn_layout.addWidget(trade_manager)
        self.active_trade_preview_widget = trade_manager

        decision = explanation.chosen_candidate.metadata.get("decision")
        opponent_name = explanation.chosen_candidate.metadata.get("opponent_name", "player")
        requested = explanation.chosen_candidate.metadata.get("payment", {})
        original_offer = explanation.chosen_candidate.metadata.get("selling_to_us", {})
        counter_offer = explanation.chosen_candidate.metadata.get("counter_payment")
        shown_offer = counter_offer if decision == "counter" and counter_offer is not None else original_offer

        self.window.main_menu.main_label.setText(f"Trade Offer from {opponent_name}")
        self.window.main_menu.action_label.setText(
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

    def _display_robber_preview(self, explanation: ActionExplanation) -> None:
        """Display the robber preview."""
        target_player = explanation.chosen_candidate.metadata.get("target_player_name")
        self.window.main_menu.main_label.setText("Move The Robber")
        if target_player:
            self.window.main_menu.action_label.setText(
                f"Move the robber to the highlighted tile and steal from {target_player} if possible."
            )
        else:
            self.window.main_menu.action_label.setText("Move the robber to the highlighted tile.")

    def _display_discard_preview(self, explanation: ActionExplanation) -> None:
        """Display the discard preview."""
        discard = explanation.chosen_candidate.metadata.get("discard_resources", {})
        total_to_discard = sum(discard.values())
        chooser = self.resource_selector_widget
        chooser.setParent(self.window.main_menu)
        self.window.minimise_spacer()
        self.window.main_menu.action_btn_layout.addWidget(chooser)
        self.active_trade_preview_widget = chooser
        self.window.main_menu.main_label.setText("The Robber Has Been Rolled!")
        self.window.main_menu.action_label.setText(
            f"Discard {total_to_discard} resource{'s' if total_to_discard != 1 else ''}."
        )
        for res in Resource:
            getattr(chooser, f"{res.name.lower()}_quantity").setText(str(discard.get(res, 0)))
            getattr(chooser, f"{res.name.lower()}_quantity_dec").setEnabled(False)
            getattr(chooser, f"{res.name.lower()}_quantity_inc").setEnabled(False)
        chooser.submit_btn.hide()

    def _display_year_of_plenty_preview(self, explanation: ActionExplanation) -> None:
        """Display the year of plenty preview."""
        selected = explanation.chosen_candidate.metadata.get("selected_resources", {})
        self._display_resource_choice_preview(
            "Year Of Plenty",
            "Take the highlighted resources from the bank.",
            selected,
        )

    def _display_monopoly_preview(self, explanation: ActionExplanation) -> None:
        """Display the monopoly preview."""
        selected = explanation.chosen_candidate.metadata.get("selected_resources", {})
        self._display_resource_choice_preview(
            "Monopoly",
            "Choose the highlighted resource to claim from the other players.",
            selected,
        )

    def _display_resource_choice_preview(self, title: str, action_text: str, selected: ResourceCount) -> None:
        """Display the resource choice preview."""
        chooser = self.resource_selector_widget
        chooser.setParent(self.window.main_menu)
        self.window.minimise_spacer()
        self.window.main_menu.action_btn_layout.addWidget(chooser)
        self.active_trade_preview_widget = chooser
        self.window.main_menu.main_label.setText(title)
        self.window.main_menu.action_label.setText(action_text)

        for res in Resource:
            getattr(chooser, f"{res.name.lower()}_quantity").setText(str(selected.get(res, 0)))
            getattr(chooser, f"{res.name.lower()}_quantity_dec").setEnabled(False)
            getattr(chooser, f"{res.name.lower()}_quantity_inc").setEnabled(False)

        chooser.submit_btn.hide()

    def create_quantity_handlers(
        self,
        current_counts: ResourceCount,
        quantity_btns: Dict[Resource, Tuple[QLabel, QToolButton, QToolButton]],
        caps: ResourceCount | None = None,
        on_update: Callable[[], None] | None = None,
        zero_other: Tuple[ResourceCount, Dict[Resource, Tuple[QLabel, QToolButton, QToolButton]]] | None = None,
    ) -> None:
        """Handle create quantity handlers."""
        if caps is None:
            caps = {res: float("inf") for res in current_counts}

        def update_label(res: Resource) -> None:
            quantity_btns[res][0].setText(str(current_counts[res]))

        def increase(res: Resource) -> None:
            if current_counts[res] < caps[res]:
                current_counts[res] += 1
                update_label(res)
                if zero_other is not None:
                    zero_other[0][res] = 0
                    zero_other[1][res][0].setText("0")
                if on_update:
                    on_update()

        def decrease(res: Resource) -> None:
            if current_counts[res] > 0:
                current_counts[res] -= 1
                update_label(res)
                if on_update:
                    on_update()

        for res, (_, dec_btn, inc_btn) in quantity_btns.items():
            self.window.safe_connect(inc_btn, lambda _, r=res: increase(r))
            self.window.safe_connect(dec_btn, lambda _, r=res: decrease(r))

        for res in current_counts:
            update_label(res)

    def display_trade_menu(self, controller: GameController, player: Player, back_action) -> None:
        """Display the trade menu workflow."""
        self.window.display_resources(controller)
        trade_designer = self.trade_designer_widget
        trade_designer.setParent(self.window.main_menu)

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

        self.window.main_menu.main_label.hide()
        self.window.main_menu.action_label.hide()
        self.window.toggle_main_action_btns(False)
        self.window.minimise_spacer()
        self.window.main_menu.action_btn_layout.addWidget(trade_designer)

        selling: ResourceCount = {res: 0 for res in Resource}
        buying: ResourceCount = {res: 0 for res in Resource}

        def update_buttons() -> None:
            for res, (_, dec_btn, inc_btn) in selling_btns.items():
                dec_btn.setEnabled(selling[res] > 0)
                inc_btn.setEnabled(selling[res] < player.resources[res])

            for res, (_, dec_btn, inc_btn) in buying_btns.items():
                dec_btn.setEnabled(buying[res] > 0)
                inc_btn.setEnabled(True)

            trade_incomplete = all(v == 0 for v in selling.values()) or all(v == 0 for v in buying.values())
            valid_bank_trade = (
                not trade_incomplete and controller.try_trade_with_bank(player, selling, buying, use_resources=False)
            )
            valid_player_trade = not trade_incomplete

            trade_designer.bank_trade_btn.setEnabled(valid_bank_trade)
            trade_designer.player_trade_btn.setEnabled(valid_player_trade)

        self.create_quantity_handlers(
            current_counts=selling,
            quantity_btns=selling_btns,
            caps=player.resources,
            on_update=update_buttons,
            zero_other=(buying, buying_btns),
        )
        self.create_quantity_handlers(
            current_counts=buying,
            quantity_btns=buying_btns,
            on_update=update_buttons,
            zero_other=(selling, selling_btns),
        )
        update_buttons()

        def terminate_trade() -> None:
            self.window.main_menu.main_label.show()
            self.window.main_menu.action_label.show()
            self.window.restore_spacer()
            self.window.main_menu.action_btn_layout.removeWidget(trade_designer)
            trade_designer.setParent(None)
            self.window.set_debug_tutor_shortcut_finalizer(None)
            back_action()

        def trade_with_bank() -> None:
            self.window.restore_spacer()
            self.window.main_menu.action_btn_layout.removeWidget(trade_designer)
            trade_designer.setParent(None)
            self.window.main_menu.main_label.show()
            self.window.main_menu.action_label.show()
            self.window.set_debug_tutor_shortcut_finalizer(None)
            self.window.turnMade.emit(Action(ActionType.TRADE_WITH_BANK, (selling.copy(), buying.copy())))

        def trade_with_players() -> None:
            self.window.restore_spacer()
            self.window.main_menu.action_btn_layout.removeWidget(trade_designer)
            trade_designer.setParent(None)
            self.window.main_menu.main_label.show()
            self.window.main_menu.action_label.show()
            self.window.set_debug_tutor_shortcut_finalizer(None)
            self.window.turnMade.emit(Action(ActionType.TRADE_WITH_PLAYER, (selling.copy(), buying.copy())))

        def cleanup_trade_designer() -> None:
            self.window.restore_spacer()
            self.window.main_menu.action_btn_layout.removeWidget(trade_designer)
            trade_designer.setParent(None)
            self.window.main_menu.main_label.show()
            self.window.main_menu.action_label.show()
            self.window.set_debug_tutor_shortcut_finalizer(None)

        self.window.set_debug_tutor_shortcut_finalizer(cleanup_trade_designer)
        self.window.safe_connect(trade_designer.terminate_btn, terminate_trade)
        self.window.safe_connect(trade_designer.bank_trade_btn, trade_with_bank)
        self.window.safe_connect(trade_designer.player_trade_btn, trade_with_players)

    def select_player_to_trade(
        self,
        controller: GameController,
        player: Player,
        selling: ResourceCount,
        buying: ResourceCount,
        willing_players,
    ) -> None:
        """Display the player-trade selection workflow."""
        self.window.display_resources(controller)
        self.clear_trade_preview()
        self.window.main_menu.action_label.show()

        if not willing_players:
            self.window.main_menu.action_label.setText("No players are willing to trade with you right now.")
            self.window.set_debug_tutor_shortcut_finalizer(None)
            QTimer.singleShot(0, lambda: self.window.tradeSelected.emit(None))
            return

        select_trade = self.select_trade_widget
        select_trade.setParent(self.window.main_menu)
        self.window.toggle_main_action_btns(False)
        self.window.minimise_spacer()
        self.window.main_menu.action_btn_layout.addWidget(select_trade)
        self.active_trade_preview_widget = select_trade
        select_trade.trade_list.clear()
        select_trade.trade_list.setEnabled(True)

        self.window.main_menu.action_label.setText(f"Available Trades for {format_counter_offer(buying, buying)}:")
        select_trade.submit_btn.setText("Cancel")
        select_trade.submit_btn.show()
        select_trade.trade_list.show()

        for trade_player, counter in willing_players:
            if counter is None:
                can_afford = True
                trade_str = format_counter_offer(selling, selling)
            else:
                can_afford = all(player.resources.get(res, 0) >= amt for res, amt in counter.items())
                trade_str = format_counter_offer(selling, counter)

            item = QListWidgetItem(f"Trade {trade_player.name}: {trade_str}")
            if not can_afford:
                item.setText(item.text() + " (CANNOT AFFORD)")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            item.setData(Qt.ItemDataRole.UserRole, (trade_player, counter) if can_afford else None)
            select_trade.trade_list.addItem(item)

        for i in range(select_trade.trade_list.count()):
            if select_trade.trade_list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled:
                select_trade.trade_list.setCurrentRow(i)
                break

        def accept_trade(trade: QListWidgetItem) -> None:
            deal = trade.data(Qt.ItemDataRole.UserRole)
            if not deal:
                return
            self.clear_trade_preview()
            self.window.set_debug_tutor_shortcut_finalizer(None)
            self.window.tradeSelected.emit(deal)

        try:
            select_trade.trade_list.itemDoubleClicked.disconnect()
        except TypeError:
            pass
        select_trade.trade_list.itemDoubleClicked.connect(accept_trade)

        def cancel() -> None:
            self.clear_trade_preview()
            self.window.set_debug_tutor_shortcut_finalizer(None)
            self.window.tradeSelected.emit(None)

        def cleanup_select_trade() -> None:
            self.clear_trade_preview()
            self.window.set_debug_tutor_shortcut_finalizer(None)

        self.window.set_debug_tutor_shortcut_finalizer(cleanup_select_trade)
        self.window.safe_connect(select_trade.submit_btn, cancel)

    def show_resource_chooser(
        self, player, num_resources: int, title: str, resource_caps: ResourceCount | None = None
    ) -> None:
        """Display the resource chooser widget."""
        self.clear_trade_preview()
        selection_widget = self.resource_selector_widget
        selection_widget.setParent(self.window.main_menu)

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

        self.window._set_turn_label(player)
        self.window.main_menu.main_label.setText(title)
        self.window.main_menu.action_label.setText(
            f"You need to select {num_resources} more resource{'s' if num_resources != 1 else ''}."
        )

        self.window.toggle_main_action_btns(False)
        self.window.main_menu.action_btn_layout.addWidget(selection_widget)
        selection_widget.submit_btn.show()

        def update_labels() -> None:
            total_remaining = num_resources - sum(chosen.values())
            self.window.main_menu.action_label.setText(
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
            on_update=update_labels,
        )

        def submit() -> None:
            self.window.main_menu.action_btn_layout.removeWidget(selection_widget)
            selection_widget.setParent(None)
            self.window.set_debug_tutor_shortcut_finalizer(None)
            self.window.resourcesPicked.emit(chosen)

        def cleanup_selection_widget() -> None:
            self.window.main_menu.action_btn_layout.removeWidget(selection_widget)
            selection_widget.setParent(None)
            self.window.set_debug_tutor_shortcut_finalizer(None)

        self.window.set_debug_tutor_shortcut_finalizer(cleanup_selection_widget)
        self.window.safe_connect(selection_widget.submit_btn, submit)
        update_labels()

    def display_trade_manager(self, player: Player, selling: ResourceCount, buying: ResourceCount, selling_player):
        """Display the trade manager widget."""
        self.clear_trade_preview()
        trade_manager = self.trade_manager_widget
        trade_manager.setParent(self.window.main_menu)

        selling_btns = {
            res: (
                getattr(trade_manager, f"{res.name.lower()}_quantity"),
                getattr(trade_manager, f"{res.name.lower()}_quantity_dec"),
                getattr(trade_manager, f"{res.name.lower()}_quantity_inc"),
            )
            for res in Resource
        }

        self.window.toggle_main_action_btns(False)
        self.window.minimise_spacer()
        self.window.main_menu.action_btn_layout.addWidget(trade_manager)
        self.active_trade_preview_widget = trade_manager
        self.window._set_turn_label(selling_player)
        self.window.main_menu.main_label.setText(f"Trade Offer from {selling_player.name}")
        self.window.main_menu.action_label.setText(
            f"{selling_player.name} is buying {format_counter_offer(buying, buying)} for:"
        )
        trade_manager.accept_btn.show()
        trade_manager.decline_btn.show()

        counter_offer = {res: selling.get(res, 0) for res in Resource}

        def update_buttons() -> None:
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
            self.window.main_menu.action_label.setText(txt)

        self.create_quantity_handlers(
            current_counts=counter_offer,
            quantity_btns=selling_btns,
            on_update=update_buttons,
        )

        def accept() -> None:
            trade_manager.accept_btn.setEnabled(False)
            trade_manager.decline_btn.setEnabled(False)
            modified = any(counter_offer[res] != selling.get(res, 0) for res in Resource)
            self.clear_trade_preview()
            self.window.set_debug_tutor_shortcut_finalizer(None)
            self.window.tradeDecisionMade.emit((True, counter_offer if modified else None))

        def decline() -> None:
            self.clear_trade_preview()
            self.window.set_debug_tutor_shortcut_finalizer(None)
            self.window.tradeDecisionMade.emit((False, None))

        def cleanup_trade_manager() -> None:
            self.clear_trade_preview()
            self.window.set_debug_tutor_shortcut_finalizer(None)

        self.window.set_debug_tutor_shortcut_finalizer(cleanup_trade_manager)
        self.window.safe_connect(trade_manager.accept_btn, accept)
        self.window.safe_connect(trade_manager.decline_btn, decline)
        update_buttons()
