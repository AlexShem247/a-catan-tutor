from typing import Dict, Tuple, List, Callable, Optional

from PyQt6 import uic
from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QObject, QSize
from PyQt6.QtGui import QIcon, QKeyEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter, QLabel, QToolButton, QSpacerItem,
    QSizePolicy, QPushButton, QLayout,
    QButtonGroup
)

from controllers.GameController import GameController
from ai.actions import Action, ActionType
from ai.tutor.explanations import ActionExplanation
from ai.tutor.feedback import TutorFeedbackExplanation
from ai.tutor.tutor import TutorStage
from game.Edge import Edge
from game.Player import PlayerNumber, Player
from game.PlayerAssets import Buildable
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from view.canvas.board_display_source import BoardDisplaySource
from view.canvas.SquareCanvas import SquareCanvas
from view.canvas.display_utils import format_counter_offer, get_player_lead_status
from view.panels.development_panel import DevelopmentPanel
from view.panels.endgame_review_panel import EndgameReviewPanel
from view.panels.settings_panel import SettingsPanel
from view.panels.TradePanel import TradePanel
from view.panels.TutorPanel import TutorPanel
from config.view_constants import (
    APP_ICON,
    CROWN_SYM,
    HOME_ICON,
    PLAYER_COLORS,
    RULES_ICON,
    SETTINGS_ICON,
)
from view.rich_text import tutor_window_title_html
from view.styles import (
    player_badge_stylesheet,
)
from view.View import GameMode


class MainWindow(QMainWindow):
    SIDE_PANEL_WIDTH = 360
    LABEL_LINE_LENGTH = 38
    startGame = pyqtSignal(object)
    turnMade = pyqtSignal(object)
    debugShortcutResult = pyqtSignal(object)
    tradeDecisionMade = pyqtSignal(object)
    tradeSelected = pyqtSignal(object)
    resourcesPicked = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Settlers of Catan")
        self.setWindowIcon(QIcon(APP_ICON))

        # Central widget
        central = QWidget(self)
        self.setCentralWidget(central)

        self.root_layout = QHBoxLayout(central)
        self.root_layout.setContentsMargins(0, 0, 0, 0)

        # Splitter
        self.splitter_layout = QSplitter(Qt.Orientation.Horizontal, self)
        self.root_layout.addWidget(self.splitter_layout)

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
        self.results_menu = uic.loadUi("view/ui/results_menu.ui")
        self.endgame_review_menu = uic.loadUi("view/ui/endgame_review.ui")
        self.start_menu = uic.loadUi("view/ui/start_menu.ui")
        self.tutor_panel = TutorPanel(self, self.tutor_menu)
        self.trade_panel = TradePanel(
            self,
            self.resource_selector_widget,
            self.trade_designer_widget,
            self.select_trade_widget,
            self.trade_manager_widget,
        )
        self.endgame_review_panel = EndgameReviewPanel(self, self.results_menu, self.endgame_review_menu)
        self.development_panel = DevelopmentPanel(self, self.development_manager_widget)
        self.settings_panel = SettingsPanel(self)
        self.endgame_winner_trophy_label = self.endgame_review_panel.winner_trophy_label
        self.endgame_replay_canvas = self.endgame_review_panel.replay_canvas
        self.endgame_replay_splitter = self.endgame_review_panel.replay_splitter
        self.victory_points_plot = self.endgame_review_panel.victory_points_plot
        self.history_nav_widget = self.tutor_panel.history_nav_widget
        self.history_prev_btn = self.tutor_panel.history_prev_btn
        self.history_detail_btn = self.tutor_panel.history_detail_btn
        self.history_next_btn = self.tutor_panel.history_next_btn
        self.history_exit_btn = self.tutor_panel.history_exit_btn

        self.rule_window = uic.loadUi("view/ui/rules_window.ui")
        self.rule_window.setWindowIcon(QIcon(APP_ICON))
        self.settings_window = uic.loadUi("view/ui/settings_window.ui")
        self.settings_window.setWindowIcon(QIcon(APP_ICON))
        self.settings_difficulty_group = QButtonGroup(self.settings_window)
        self.settings_difficulty_group.setExclusive(True)
        self.settings_difficulty_group.addButton(self.settings_window.easy_difficulty_radio)
        self.settings_difficulty_group.addButton(self.settings_window.medium_difficulty_radio)
        self.settings_difficulty_group.addButton(self.settings_window.hard_difficulty_radio)
        self.safe_connect(self.start_menu.help_btn, self.show_rules)
        self.safe_connect(self.start_menu.settings_btn, self.show_settings)
        self.safe_connect(self.main_menu.help_btn, self.show_rules)
        self.tutor_menu.title_label.setText(tutor_window_title_html())
        button_icon_size = QSize(18, 18)
        self.start_menu.help_btn.setIcon(QIcon(RULES_ICON))
        self.start_menu.help_btn.setIconSize(button_icon_size)
        self.start_menu.settings_btn.setIcon(QIcon(SETTINGS_ICON))
        self.start_menu.settings_btn.setIconSize(button_icon_size)
        self.main_menu.help_btn.setText("")
        self.main_menu.help_btn.setIcon(QIcon(RULES_ICON))
        self.main_menu.help_btn.setIconSize(self.main_menu.help_btn.size())
        self.main_menu.home_btn.setText("")
        self.main_menu.home_btn.setIcon(QIcon(HOME_ICON))
        self.main_menu.home_btn.setIconSize(self.main_menu.home_btn.size())
        self._apply_player_colour_indicators()
        self.settings_panel.capture_font_baselines()
        self.settings_panel.load_settings_into_ui()
        self.safe_connect(self.settings_window.apply_btn, self.settings_panel.save_settings)
        self.safe_connect(self.settings_window.reset_defaults_btn, self.settings_panel.reset_settings_to_default)
        self.safe_connect(self.settings_window.close_btn, self.settings_panel.close_settings_window)
        self.settings_window.font_size_spinbox.valueChanged.connect(self.settings_panel.preview_font_size)

        self.verticalSpacer = self.find_last_vertical_spacer()
        self.live_board_source: BoardDisplaySource | None = None
        self.fullscreen_panel: Optional[QWidget] = None
        self.debug_tutor_shortcut_handler: Optional[Callable[[], object]] = None
        self.debug_tutor_shortcut_finalizer: Optional[Callable[[], None]] = None
        self.main_action_btn_enabled_states: List[bool] = []
        self.restore_board_state_callback: Optional[Callable[[], None]] = None
        self.return_home_requested = False
        self.safe_connect(self.main_menu.end_turn_btn, lambda: self.turnMade.emit(Action(ActionType.END_TURN)))
        self.safe_connect(self.main_menu.home_btn, self.return_to_start_screen)

    def safe_connect(self, button: QToolButton | QPushButton, slot: Callable):
        try:
            button.clicked.disconnect()  # type: ignore[attr-defined]
        except TypeError:
            pass
        button.clicked.connect(slot)  # type: ignore[attr-defined]

    def set_restore_board_state_callback(self, callback: Optional[Callable[[], None]]):
        self.restore_board_state_callback = callback

    def return_to_start_screen(self):
        self.tutor_panel.stop_auto_feedback()
        self.return_home_requested = True
        home_action = Action(ActionType.RETURN_HOME)
        self.turnMade.emit(home_action)
        self.canvas.selectionMade.emit(home_action)
        self.tradeDecisionMade.emit(home_action)
        self.tradeSelected.emit(home_action)
        self.resourcesPicked.emit(home_action)

    def consume_return_home_request(self) -> bool:
        requested = self.return_home_requested
        self.return_home_requested = False
        return requested

    def show_rules(self):
        # Show the rule window
        self.rule_window.show()
        self.rule_window.raise_()  # Bring it to the front
        self.rule_window.activateWindow()  # Focus it

    def show_settings(self):
        self.settings_panel.load_settings_into_ui()
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _apply_player_colour_indicators(self) -> None:
        player_label_map = {
            PlayerNumber.P2: self.main_menu.p2_label,
            PlayerNumber.P3: self.main_menu.p3_label,
            PlayerNumber.P4: self.main_menu.p4_label,
        }
        for player_number, label in player_label_map.items():
            self._set_player_badge(
                label,
                label.text(),
                player_number,
                vertical_padding_px=3,
                horizontal_padding_px=8,
                font_size_px=12,
            )

    def _set_turn_label(self, player: Player) -> None:
        self._set_player_badge(
            self.main_menu.turn_label,
            f"{player.name}'s turn",
            player.player_number,
            vertical_padding_px=4,
            horizontal_padding_px=8,
        )

    def _resolve_turn_label_player(self, player: Player, explanation: ActionExplanation | None = None) -> Player:
        if explanation is None:
            return player

        if not isinstance(self.live_board_source, GameController):
            return player

        metadata_sources = []
        if explanation.metadata:
            metadata_sources.append(explanation.metadata)
        if explanation.chosen_candidate.metadata:
            metadata_sources.append(explanation.chosen_candidate.metadata)

        for metadata in metadata_sources:
            turn_player_number = metadata.get("turn_player_number")
            if turn_player_number is None:
                continue
            for candidate_player in self.live_board_source.get_all_players():
                if candidate_player.player_number == turn_player_number:
                    return candidate_player

        return player

    def _set_player_badge(
            self,
            label: QLabel,
            text: str,
            player_number: PlayerNumber,
            vertical_padding_px: int,
            horizontal_padding_px: int,
            font_size_px: int | None = None,
    ) -> None:
        colour = PLAYER_COLORS[player_number].lighter(150).name()
        label.setStyleSheet(player_badge_stylesheet(
            colour,
            vertical_padding_px,
            horizontal_padding_px,
            font_size_px=font_size_px,
        ))
        label.setText(text)

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

    def set_main_action_btns_enabled(self, enabled: bool):
        for i in range(self.main_menu.action_btn_layout.count()):
            widget: QWidget = self.main_menu.action_btn_layout.itemAt(i).widget()
            if widget:
                widget.setEnabled(enabled)

    def _capture_main_action_btn_enabled_states(self) -> List[bool]:
        states: List[bool] = []
        for i in range(self.main_menu.action_btn_layout.count()):
            widget: QWidget = self.main_menu.action_btn_layout.itemAt(i).widget()
            if widget:
                states.append(widget.isEnabled())
        return states

    def _restore_main_action_btn_enabled_states(self):
        if not self.main_action_btn_enabled_states:
            return
        state_index = 0
        for i in range(self.main_menu.action_btn_layout.count()):
            widget: QWidget = self.main_menu.action_btn_layout.itemAt(i).widget()
            if widget:
                widget.setEnabled(self.main_action_btn_enabled_states[state_index])
                state_index += 1
        self.main_action_btn_enabled_states = []

    def _clear_debug_tutor_shortcut_context(self):
        self.debug_tutor_shortcut_handler = None
        self.debug_tutor_shortcut_finalizer = None

    def set_debug_tutor_shortcut_handler(self, handler: Optional[Callable[[], object]]):
        self.debug_tutor_shortcut_handler = handler

    def set_debug_tutor_shortcut_finalizer(self, finalizer: Optional[Callable[[], None]]):
        self.debug_tutor_shortcut_finalizer = finalizer

    def _clear_tutor_shortcut_ui_state(self) -> None:
        if self.tutor_panel.dismiss_tutor_hint_callback is not None:
            self.tutor_panel.dismiss_tutor_hint_callback()
        self.trade_panel.clear_trade_preview()

    def _try_apply_tutor_shortcut(self, handler: Optional[Callable[[], object]]) -> bool:
        if handler is None:
            return False

        self._clear_tutor_shortcut_ui_state()
        result = handler()
        if self.debug_tutor_shortcut_finalizer is not None:
            self.debug_tutor_shortcut_finalizer()
        self.debugShortcutResult.emit(result)
        return True

    def _try_apply_tutor_recommended_move(self) -> bool:
        return self._try_apply_tutor_shortcut(self.debug_tutor_shortcut_handler)

    def _show_fullscreen_panel(self, panel: QWidget):
        current_size = self.size()
        if self.root_layout.indexOf(self.splitter_layout) != -1:
            self.root_layout.removeWidget(self.splitter_layout)
        self.splitter_layout.hide()

        if self.fullscreen_panel is not None and self.root_layout.indexOf(self.fullscreen_panel) != -1:
            self.root_layout.removeWidget(self.fullscreen_panel)
            self.fullscreen_panel.setParent(None)

        self.fullscreen_panel = panel
        panel.setMinimumSize(0, 0)
        panel.setMinimumWidth(0)
        self.root_layout.addWidget(panel)
        panel.show()
        self.resize(current_size)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.endgame_review_panel.reset_hover()

    def leaveEvent(self, event):
        self.endgame_review_panel.reset_hover()
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_F8 and self._try_apply_tutor_recommended_move():
            event.accept()
            return
        super().keyPressEvent(event)

    def _restore_splitter_layout(self):
        if self.fullscreen_panel is not None and self.root_layout.indexOf(self.fullscreen_panel) != -1:
            self.root_layout.removeWidget(self.fullscreen_panel)
            self.fullscreen_panel.setParent(None)
        self.fullscreen_panel = None

        if self.root_layout.indexOf(self.splitter_layout) == -1:
            self.root_layout.addWidget(self.splitter_layout)
        self.splitter_layout.show()

    @staticmethod
    def _clear_layout(layout: QLayout):
        while layout.count():
            item = layout.takeAt(0)
            child_layout = item.layout()
            widget = item.widget()

            if child_layout is not None:
                MainWindow._clear_layout(child_layout)
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if self.endgame_review_panel.handle_event_filter(watched, event):
            return True
        return super().eventFilter(watched, event)

    def closeEvent(self, _):
        quit()

    def display_resources(self, controller: BoardDisplaySource):
        if isinstance(controller, GameController):
            self.live_board_source = controller

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
                    name_text = f"{player.name} {status}"
                    labels["name"].setToolTip(f"{player.name} is currently in the lead")
                else:
                    name_text = player.name
                    labels["name"].setToolTip(None)
                self._set_player_badge(
                    labels["name"],
                    name_text,
                    player.player_number,
                    vertical_padding_px=2,
                    horizontal_padding_px=8,
                    font_size_px=12,
                )
                labels["victory_points"].setText(str(player.calc_victory_points()[0]))
                labels["num_resources"].setText(str(sum(player.resources.values())))
                labels["development_cards"].setText(str(len(player.development_cards)))
                labels["army_size"].setText(str(player.army_size))
                labels["longest_road"].setText(str(player.longest_road_length))

    def display_generic_info(self, player: Player, msg: str):
        self._clear_debug_tutor_shortcut_context()
        self.canvas.clear_planned_builds()
        self._set_turn_label(player)
        self.main_menu.main_label.show()
        self.main_menu.main_label.setText(msg)
        self.main_menu.action_label.show()
        self.main_menu.action_label.setText("" if player.is_human else f"{player} is thinking")
        self.toggle_main_action_btns(False)

    def display_round_info(self, controller: GameController, player: Player, dice_info: Tuple[int, int, int],
                           played_dev_card: bool = False):
        self.tutor_panel.reset_for_turn()
        self.canvas.clear_feedback_builds()
        self.canvas.interactive_shapes.clear()
        self.canvas.disable_interactivity = False
        self.canvas.display_board(controller)
        self.display_resources(controller)

        if controller.game_mode == GameMode.TUTOR and player.is_human:
            explanation = controller.get_tutor_turn_explanation(player, played_dev_card)
            if explanation is not None:
                self.display_tutor_init(player, TutorStage.TURN_ACTION, explanation)

        d1, d2, total = dice_info
        self._set_turn_label(player)
        self.main_menu.main_label.setText(f"Dice rolled: {d1} + {d2} = {total}\nWhat would you like to do?")

        # Actions
        self.toggle_main_action_btns(True)
        self.set_main_action_btns_enabled(True)

        self.draw_buildables_if_can_build(controller, player)
        can_afford_card = controller.get_buildable_options(player)[Buildable.DEVELOPMENT_CARD]
        self.main_menu.dev_btn.setEnabled(can_afford_card or len(player.development_cards) > 0)
        self.main_menu.trade_btn.setEnabled(sum(player.resources.values()) > 0)
        self.safe_connect(self.main_menu.trade_btn, lambda: self.display_trade_menu(
            controller, player, lambda: self.display_round_info(controller, player, dice_info, played_dev_card)))
        self.safe_connect(self.main_menu.dev_btn, lambda: self.development_panel.show_development_menu(
            controller, player, played_dev_card,
            lambda played: self.display_round_info(controller, player, dice_info, played)))
        self.safe_connect(self.main_menu.end_turn_btn, lambda: self.turnMade.emit(Action(ActionType.END_TURN)))
        self.tutor_panel.set_restore_tutor_menu_callback(
            lambda: self.display_round_info(controller, player, dice_info, played_dev_card),
            controller.game_mode == GameMode.TUTOR and player.is_human,
        )
        self.set_restore_board_state_callback(None)

    def configure_tutor_panel(self, game_mode: GameMode):
        self.tutor_panel.configure_for_game_mode(game_mode)

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

    def display_tutor_init(self, player: Player, stage: TutorStage, explanation: ActionExplanation):
        self.tutor_panel.display_tutor_init(player, stage, explanation)

    def display_explanation(self, player: Player, dice_info: Optional[Tuple[int, int, int]],
                            explanation: ActionExplanation):
        self.tutor_panel.display_explanation(player, dice_info, explanation)

    def display_tutor_action_feedback(self, feedback: TutorFeedbackExplanation) -> None:
        self.tutor_panel.display_tutor_action_feedback(feedback)

    def display_trade_menu(self, controller: GameController, player: Player, back_action):
        self.trade_panel.display_trade_menu(controller, player, back_action)

    def select_player_to_trade(self, controller: GameController, player: Player, selling: ResourceCount,
                               buying: ResourceCount, willing_players: List[Tuple[Player, ResourceCount | None]]):
        self.trade_panel.select_player_to_trade(controller, player, selling, buying, willing_players)

    def display_round_info_ai_start(self, player: Player, dice_info: Optional[Tuple[int, int, int]], msg: str):
        self._clear_debug_tutor_shortcut_context()
        self.tutor_panel.prepare_ai_wait_state()
        self.canvas.clear_feedback_builds()
        self.set_restore_board_state_callback(None)
        self.trade_panel.clear_trade_preview()
        self.canvas.clear_planned_builds()
        if dice_info:
            d1, d2, total = dice_info
            self.main_menu.main_label.setText(f"Dice rolled: {d1} + {d2} = {total}")

        if msg == "":
            msg = f"{player.name} ended their turn without taking any further actions."

        self._set_turn_label(player)
        self.main_menu.action_label.setText(msg)
        self.toggle_main_action_btns(False)
        self.tutor_menu.action_label.setText("Wait For Your Turn")
        self.tutor_menu.explanation_edit.setText("Opponent is making move")
        self.tutor_menu.explain_btn.setEnabled(False)
        self.tutor_menu.continue_btn.setEnabled(False)

    def show_resource_chooser(self, player, num_resources: int, title: str,
                              resource_caps: ResourceCount | None = None):
        self.trade_panel.show_resource_chooser(player, num_resources, title, resource_caps)

    def display_trade_manager(self, player: Player, selling: ResourceCount,
                              buying: ResourceCount, selling_player: Player):
        self.trade_panel.display_trade_manager(player, selling, buying, selling_player)

    def draw_buildables_if_can_build(self, controller, player):
        def build(selected_buildable: Vertex | Edge):
            match selected_buildable:
                case Edge():
                    self.turnMade.emit(Action(ActionType.BUILD, (Buildable.ROAD, selected_buildable)))
                case Vertex():
                    if selected_buildable.building is None:
                        self.turnMade.emit(Action(ActionType.BUILD, (Buildable.SETTLEMENT, selected_buildable)))
                    else:
                        self.turnMade.emit(Action(ActionType.BUILD, (Buildable.CITY, selected_buildable)))

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
        self._clear_debug_tutor_shortcut_context()
        if controller.game_mode in {GameMode.PLAY, GameMode.TUTOR}:
            self.endgame_review_panel.display_tutor_endgame_review(controller)
            return
        self.endgame_review_panel.display_results(controller)

    def _set_primary_side_panel(self, panel: QWidget):
        self._restore_splitter_layout()

        for widget in (self.main_menu, self.start_menu, self.results_menu):
            if self.splitter_layout.indexOf(widget) != -1:
                widget.setParent(None)

        panel.setMinimumWidth(0)
        panel.setMaximumWidth(self.SIDE_PANEL_WIDTH * 2)
        self.splitter_layout.addWidget(panel)
        panel.show()
        self.splitter_layout.setSizes([1000, self.SIDE_PANEL_WIDTH])

    def display_start_screen(self):
        self.return_home_requested = False
        self._clear_debug_tutor_shortcut_context()
        self.tutor_panel.reset_for_start_screen()
        self.open_tutor_menu(False)
        self.trade_panel.clear_trade_preview()
        self.restore_spacer()
        self.canvas.clear_planned_builds()
        self.canvas.interactive_shapes.clear()
        self.canvas.display_start_screen()
        self._set_primary_side_panel(self.start_menu)

        def play(game_mode: GameMode):
            self.open_tutor_menu(False)
            self._set_primary_side_panel(self.main_menu)
            self.startGame.emit(game_mode)

        def is_lab_mode() -> bool:
            return self.start_menu.lab_mode_btn.isChecked()

        def update_lab_mode(is_enabled: bool):
            self.start_menu.standard_mode_btn.setText("Quick Simulation" if is_enabled else "Start Game")
            self.start_menu.tutor_mode_btn.setText("Guided Simulation" if is_enabled else "Tutor Mode")
            self.start_menu.lab_mode_btn.setText("Back" if is_enabled else "Lab Mode")

        self.start_menu.lab_mode_btn.setCheckable(True)
        try:
            self.start_menu.lab_mode_btn.toggled.disconnect()
        except TypeError:
            pass

        self.start_menu.lab_mode_btn.setChecked(False)
        update_lab_mode(False)

        self.safe_connect(
            self.start_menu.standard_mode_btn,
            lambda: play(GameMode.SIMULATION if is_lab_mode() else GameMode.PLAY)
        )
        self.safe_connect(
            self.start_menu.tutor_mode_btn,
            lambda: play(GameMode.GUIDED if is_lab_mode() else GameMode.TUTOR)
        )
        self.start_menu.lab_mode_btn.toggled.connect(update_lab_mode)
