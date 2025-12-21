from typing import Dict, Tuple, List, Callable

from PyQt6 import uic
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter, QLabel, QToolButton, QListWidgetItem, QSpacerItem,
    QSizePolicy, QPushButton
)

from GameController import GameController
from drawing.SquareCanvas import SquareCanvas
from drawing.constants import CROWN_SYM
from game.Edge import Edge
from game.Player import PlayerNumber, Player
from game.PlayerAssets import Buildable
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from view.display import format_counter_offer, get_player_lead_status


class MainWindow(QMainWindow):
    SIDE_PANEL_WIDTH = 320
    LABEL_LINE_LENGTH = 38
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
        self.trade_designer_widget = uic.loadUi("drawing/ui/trade_designer.ui")
        self.select_trade_widget = uic.loadUi("drawing/ui/select_trade.ui")
        self.trade_manager_widget = uic.loadUi("drawing/ui/trade_manager.ui")

        self.verticalSpacer = self.find_last_vertical_spacer()
        self.safe_connect(self.side_panel.end_turn_btn, lambda: self.turnMade.emit(True))

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

    @staticmethod
    def safe_connect(button: QToolButton | QPushButton, slot: Callable):
        try:
            button.clicked.disconnect()   # type: ignore[attr-defined]
        except TypeError:
            pass
        button.clicked.connect(slot)

    def find_last_vertical_spacer(self) -> QSpacerItem | None:
        last_spacer = None
        layout = self.side_panel.frame.layout()
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
        if self.side_panel.frame.layout() is not None:
            self.side_panel.frame.layout().update()

    def restore_spacer(self):
        """Restores self.verticalSpacer to its original size and size policy."""
        if getattr(self, "verticalSpacer", None) is None:
            return

        spacer = self.verticalSpacer
        if not hasattr(spacer, "_original_size"):
            return

        w, h, h_policy, v_policy = getattr(spacer, "_original_size")
        spacer.changeSize(w, h, h_policy, v_policy)
        if self.side_panel.frame.layout() is not None:
            self.side_panel.frame.layout().update()

    def toggle_main_action_btns(self, show: bool):
        for i in range(self.side_panel.action_btn_layout.count()):
            widget: QWidget = self.side_panel.action_btn_layout.itemAt(i).widget()
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
            res: getattr(self.side_panel, f"bank_{res.name.lower()}_label")
            for res in Resource
        }

        for res, label in bank_labels.items():
            label.setText(str(controller.get_bank_resources()[res]))

        self.side_panel.bank_dev_label.setText(str(controller.get_development_deck().size()))

        # Fill in opponent labels
        stat_suffixes = {"victory_points": "vic", "num_resources": "res", "development_cards": "dev",
                         "army_size": "army", "longest_road": "road"}

        opponent_labels: Dict[PlayerNumber, Dict[str, QLabel]] = {
            pn: {
                stat: getattr(self.side_panel, f"p{pn.value+1}_{suffix}_label")
                for stat, suffix in stat_suffixes.items()
            }
            for pn in (PlayerNumber.P2, PlayerNumber.P3, PlayerNumber.P4)
        }

        player_labels: Dict[Resource, QLabel] = {
            res: getattr(self.side_panel, f"{res.name.lower()}_label")
            for res in Resource
        }

        for player in controller.get_all_players():
            num = player.playerNumber
            if num == PlayerNumber.P1:
                for res, label in player_labels.items():
                    label.setText(str(player.resources[res]))

                visible_vp, true_vp = player.calc_victory_points()
                true_vp_str = f" ({true_vp})" if visible_vp != true_vp else ""
                longest_road_crown = CROWN_SYM if player.has_longest_road else ""
                army_crown = CROWN_SYM if player.has_largest_army else ""
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
        self.side_panel.action_label.setText("" if player.is_human else f"{player} is thinking")
        self.toggle_main_action_btns(False)

    def display_round_info(self, controller: GameController, player: Player, dice_info: Tuple[int, int, int]):
        self.canvas.interactive_shapes.clear()
        self.canvas.disable_interactivity = False
        self.canvas.display_board(controller)
        self.display_resources(controller)

        d1, d2, total = dice_info
        self.side_panel.turn_label.setText(f"{player.name}'s turn")
        self.side_panel.main_label.setText(f"Dice rolled: {d1} + {d2} = {total}\nWhat would you like to do?")

        # Actions
        self.toggle_main_action_btns(True)
        buildable = controller.get_buildable_options(player)
        can_build = buildable[Buildable.ROAD] or buildable[Buildable.SETTLEMENT] or buildable[Buildable.CITY]

        def build(selected_buildable: Vertex | Edge):
            match selected_buildable:
                case Edge():
                    controller.try_build_road(player, selected_buildable)
                case Vertex():
                    if selected_buildable.building is None:
                        controller.try_build_settlement(player, selected_buildable)
                    else:
                        controller.try_build_city(player, selected_buildable)

            self.display_round_info(controller, player, dice_info)

        if can_build:
            self.canvas.draw_buildables(buildable)
            try:
                self.canvas.selectionMade.disconnect()
            except TypeError:
                pass
            self.canvas.selectionMade.connect(build)
            self.side_panel.action_label.setText("Click on the board to build")
        else:
            self.side_panel.action_label.setText("")

        self.side_panel.dev_btn.setEnabled(buildable[Buildable.DEVELOPMENT_CARD] or len(player.development_cards) > 0)
        self.side_panel.trade_btn.setEnabled(sum(player.resources.values()) > 0)
        self.safe_connect(self.side_panel.trade_btn, lambda: self.display_trade_menu(
            controller, player, lambda: self.display_round_info(controller, player, dice_info)))
        self.side_panel.dev_btn.setEnabled(False)  # TODO: Add development cards

    @staticmethod
    def create_quantity_handlers(
            current_counts: ResourceCount,
            quantity_btns: Dict[Resource, Tuple[QLabel, QToolButton, QToolButton]],
            caps: ResourceCount | None = None,
            on_update: Callable[[], None] | None = None,
            zero_other: Tuple[ResourceCount, dict[Resource, Tuple[QLabel, QToolButton, QToolButton]]] | None = None
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
            MainWindow.safe_connect(inc_btn, lambda _, r=res: increase(r))
            MainWindow.safe_connect(dec_btn, lambda _, r=res: decrease(r))

        # Initialise labels
        for res in current_counts:
            update_label(res)

    def display_trade_menu(self, controller: GameController, player: Player, back_action):
        self.display_resources(controller)
        trade_designer = self.trade_designer_widget
        trade_designer.setParent(self.side_panel)

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
        self.side_panel.main_label.hide()
        self.side_panel.action_label.hide()
        self.toggle_main_action_btns(False)
        self.minimise_spacer()
        self.side_panel.action_btn_layout.addWidget(trade_designer)

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
            self.side_panel.main_label.show()
            self.side_panel.action_label.show()
            self.restore_spacer()
            self.side_panel.action_btn_layout.removeWidget(trade_designer)
            trade_designer.setParent(None)
            back_action()

        def trade_with_bank():
            controller.try_trade_with_bank(player, selling, buying)
            self.display_trade_menu(controller, player, back_action)

        def trade_with_players():
            willing_players = controller.trade_with_players(player, selling, buying)
            self.side_panel.action_btn_layout.removeWidget(trade_designer)
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
        select_trade = self.select_trade_widget
        select_trade.setParent(self.side_panel)

        # Disable main action buttons and show the trade selector
        self.side_panel.action_btn_layout.addWidget(select_trade)
        select_trade.trade_list.clear()
        self.side_panel.action_label.show()

        # Case 1: no players are willing to trade
        if not willing_players:
            self.side_panel.action_label.setText(
                self.word_wrap("No players are willing to trade with you right now.")
            )
            select_trade.submit_btn.setText("Go back")
            select_trade.trade_list.hide()

            def back():
                self.side_panel.action_btn_layout.removeWidget(select_trade)
                select_trade.setParent(None)
                back_action()

            self.safe_connect(select_trade.submit_btn, back)
            return

        # Case 2: show available trade offers
        self.side_panel.action_label.setText(self.word_wrap(
            f"Available Trades for {format_counter_offer(buying, buying)}:"
        ))
        select_trade.submit_btn.setText("Cancel")
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

            self.side_panel.action_btn_layout.removeWidget(select_trade)
            select_trade.setParent(None)

            buying_player, counter_offer = deal
            if counter_offer is not None:
                selling = counter_offer  # Player accepted counteroffer

            controller.trade_between_players(player, selling, buying_player, buying)
            back_action()

        try:
            select_trade.trade_list.itemDoubleClicked.disconnect()
        except TypeError:
            pass
        select_trade.trade_list.itemDoubleClicked.connect(accept_trade)

        # Cancel and return to the previous action
        def cancel():
            self.side_panel.action_btn_layout.removeWidget(select_trade)
            select_trade.setParent(None)
            back_action()

        self.safe_connect(select_trade.submit_btn, cancel)

    def display_round_info_ai_start(self, player: Player, dice_info: Tuple[int, int, int], msg: str):
        d1, d2, total = dice_info
        self.side_panel.turn_label.setText(f"{player.name}'s turn")
        self.side_panel.main_label.setText(f"Dice rolled: {d1} + {d2} = {total}")
        self.side_panel.action_label.setText(self.word_wrap(msg))
        self.toggle_main_action_btns(False)

    def show_resource_chooser(self, player, num_resources: int, title: str,
                              resource_caps: ResourceCount | None = None):

        selection_widget = self.resource_selector_widget
        selection_widget.setParent(self.side_panel)

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

        self.side_panel.turn_label.setText(f"{player.name}'s turn")
        self.side_panel.main_label.setText(title)
        self.side_panel.action_label.setText(
            f"You need to select {num_resources} more resource{'s' if num_resources != 1 else ''}."
        )

        self.toggle_main_action_btns(False)
        self.side_panel.action_btn_layout.addWidget(selection_widget)

        def update_labels():
            total_remaining = num_resources - sum(chosen.values())
            self.side_panel.action_label.setText(
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
            self.side_panel.action_btn_layout.removeWidget(selection_widget)
            selection_widget.setParent(None)

        self.safe_connect(selection_widget.submit_btn, submit)
        update_labels()

    def display_trade_manager(self, player: Player, selling: ResourceCount,
                              buying: ResourceCount, selling_player: Player):

        trade_manager = self.trade_manager_widget
        trade_manager.setParent(self.side_panel)

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
        self.side_panel.action_btn_layout.addWidget(trade_manager)
        self.side_panel.main_label.setText(f"Trade Offer from {selling_player.name}")
        self.side_panel.action_label.setText(
            self.word_wrap(f"{selling_player.name} is buying {format_counter_offer(buying, buying)} for:")
        )

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
            self.side_panel.action_label.setText(self.word_wrap(txt))

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
            self.side_panel.action_btn_layout.removeWidget(trade_manager)
            trade_manager.setParent(None)
            self.restore_spacer()

        def decline():
            self.tradeDecisionMade.emit((False, None))
            self.side_panel.action_btn_layout.removeWidget(trade_manager)
            trade_manager.setParent(None)
            self.restore_spacer()

        self.safe_connect(trade_manager.accept_btn, accept)
        self.safe_connect(trade_manager.decline_btn, decline)
        update_buttons()
