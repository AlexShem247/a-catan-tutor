from typing import Callable, Dict, List, Optional, Tuple

from PyQt6 import uic
from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QKeyEvent
from PyQt6.QtWidgets import (QAbstractScrollArea, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLayout, QMainWindow,
                             QPushButton, QScrollArea, QSizePolicy, QSpacerItem, QSplitter, QToolButton, QWidget)

from ai.actions import Action, ActionType
from ai.tutor.explanations import ActionExplanation
from ai.tutor.feedback import TutorFeedbackExplanation
from ai.tutor.tutor import TutorStage
from config.view_constants import (
    APP_ICON, APP_WINDOW_TITLE, CROWN_SYM, HOME_ICON, MAIN_WINDOW_BOARD_PANEL_DEFAULT_WIDTH,
    MAIN_WINDOW_HEADER_ICON_SIZE, MAIN_WINDOW_SIDE_PANEL_MAX_WIDTH, MAIN_WINDOW_SIDE_PANEL_WIDTH,
    OPPONENT_BADGE_PADDING_PX, PLAYER_BADGE_FONT_SIZE_PX, PLAYER_BADGE_LIGHTER_FACTOR, PLAYER_COLORS,
    PLAYER_INDICATOR_BADGE_PADDING_PX, RULES_ICON, SETTINGS_ICON, TURN_LABEL_BADGE_PADDING_PX,
    TUTOR_PANEL_DEFAULT_WIDTH_RATIO, UI_DEVELOPMENT_MANAGER_PATH, UI_ENDGAME_REVIEW_PATH, UI_MAIN_MENU_PATH,
    UI_RESOURCE_SELECTOR_PATH, UI_RESULTS_MENU_PATH, UI_RULES_WINDOW_PATH, UI_SELECT_TRADE_PATH,
    UI_SETTINGS_WINDOW_PATH, UI_START_MENU_PATH, UI_TRADE_DESIGNER_PATH, UI_TRADE_MANAGER_PATH, UI_TUTOR_MENU_PATH)
from controllers.GameController import GameController
from game.Edge import Edge
from game.Player import Player, PlayerNumber
from game.PlayerAssets import Buildable
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from view.canvas.board_display_source import BoardDisplaySource
from view.canvas.display_utils import format_counter_offer, get_player_lead_status
from view.canvas.SquareCanvas import SquareCanvas
from view.panels.development_panel import DevelopmentPanel
from view.panels.endgame_review_panel import EndgameReviewPanel
from view.panels.settings_panel import SettingsPanel
from view.panels.TradePanel import TradePanel
from view.panels.TutorPanel import TutorPanel
from view.rich_text import tutor_window_title_html
from view.styles import player_badge_stylesheet
from view.View import GameMode


# noinspection PyUnresolvedReferences
class MainWindow(QMainWindow):
    startGame = pyqtSignal(object)
    turnMade = pyqtSignal(object)
    debugShortcutResult = pyqtSignal(object)
    tradeDecisionMade = pyqtSignal(object)
    tradeSelected = pyqtSignal(object)
    resourcesPicked = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_WINDOW_TITLE)
        self.setWindowIcon(QIcon(APP_ICON))

        # Central widget
        central = QWidget(self)
        self.setCentralWidget(central)

        self.root_layout = QHBoxLayout(central)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.panel_hosts: Dict[QWidget, QWidget] = {}

        # Splitter
        self.splitter_layout = QSplitter(Qt.Orientation.Horizontal, self)
        self.root_layout.addWidget(self.splitter_layout)

        # Canvas
        self.canvas = SquareCanvas()
        self.splitter_layout.addWidget(self.canvas)

        # Side panel
        self.main_menu = self._load_ui(UI_MAIN_MENU_PATH)
        self.main_menu.setMinimumWidth(0)
        self.main_menu_host = self._create_side_panel_host(self.main_menu)
        self.splitter_layout.addWidget(self.main_menu_host)
        self.splitter_layout.setSizes([MAIN_WINDOW_BOARD_PANEL_DEFAULT_WIDTH, MAIN_WINDOW_SIDE_PANEL_WIDTH])

        # Prevent canvas from being squashed too much
        self.splitter_layout.setStretchFactor(0, 1)
        self.splitter_layout.setStretchFactor(1, 0)

        # Tutor panel
        self.tutor_menu = self._load_ui(UI_TUTOR_MENU_PATH)
        self.tutor_menu.setMinimumWidth(0)
        self.tutor_menu_host = self._create_side_panel_host(self.tutor_menu)

        self.resource_selector_widget = self._load_ui(UI_RESOURCE_SELECTOR_PATH)
        self.trade_designer_widget = self._load_ui(UI_TRADE_DESIGNER_PATH)
        self.select_trade_widget = self._load_ui(UI_SELECT_TRADE_PATH)
        self.trade_manager_widget = self._load_ui(UI_TRADE_MANAGER_PATH)
        self.development_manager_widget = self._load_ui(UI_DEVELOPMENT_MANAGER_PATH)
        self.results_menu = self._load_ui(UI_RESULTS_MENU_PATH)
        self.endgame_review_menu = self._load_ui(UI_ENDGAME_REVIEW_PATH)
        self.start_menu = self._load_ui(UI_START_MENU_PATH)
        self.start_menu_host = self._create_side_panel_host(self.start_menu)
        self.tutor_panel = TutorPanel(self, self.tutor_menu)
        self.trade_panel = TradePanel(self, self.resource_selector_widget, self.trade_designer_widget,
                                      self.select_trade_widget, self.trade_manager_widget)
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

        self.rule_window = self._load_ui(UI_RULES_WINDOW_PATH)
        self.rule_window.setWindowIcon(QIcon(APP_ICON))
        self.settings_window = self._load_ui(UI_SETTINGS_WINDOW_PATH)
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
        self.start_menu.help_btn.setIcon(QIcon(RULES_ICON))
        self.start_menu.help_btn.setIconSize(MAIN_WINDOW_HEADER_ICON_SIZE)
        self.start_menu.settings_btn.setIcon(QIcon(SETTINGS_ICON))
        self.start_menu.settings_btn.setIconSize(MAIN_WINDOW_HEADER_ICON_SIZE)
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

    @staticmethod
    def _load_ui(path: str) -> QWidget:
        """Load a Qt Designer UI file."""
        return uic.loadUi(path)

    def safe_connect(self, button: QToolButton | QPushButton, slot: Callable):
        """Reconnect a button click signal to the given slot."""
        try:
            button.clicked.disconnect()  # type: ignore[attr-defined]
        except TypeError:
            pass
        button.clicked.connect(slot)  # type: ignore[attr-defined]

    def _create_side_panel_host(self, panel: QWidget) -> QScrollArea:
        """Wrap a side panel in a scroll area so window height can shrink independently."""
        host = QScrollArea(self)
        host.setObjectName(f"{panel.objectName()}Host")
        host.setWidget(panel)
        host.setWidgetResizable(True)
        host.setFrameShape(QFrame.Shape.NoFrame)
        host.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        host.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        host.setMinimumWidth(0)
        host.setMaximumWidth(MAIN_WINDOW_SIDE_PANEL_MAX_WIDTH)
        host.hide()
        self.panel_hosts[panel] = host
        return host

    def _panel_host(self, panel: QWidget) -> QWidget:
        """Return the splitter host widget for a panel."""
        return self.panel_hosts.get(panel, panel)

    def _remove_panel_host(self, panel: QWidget) -> None:
        """Detach a panel host from the splitter without turning it into a floating window."""
        host = self._panel_host(panel)
        if self.splitter_layout.indexOf(host) == -1:
            return
        host.hide()
        host.setParent(self)

    def set_restore_board_state_callback(self, callback: Optional[Callable[[], None]]):
        """Store the callback used to restore the board state."""
        self.restore_board_state_callback = callback

    def return_to_start_screen(self):
        """Return the UI to the start screen workflow."""
        self.tutor_panel.stop_auto_feedback()
        self.return_home_requested = True
        home_action = Action(ActionType.RETURN_HOME)
        self.turnMade.emit(home_action)
        self.canvas.selectionMade.emit(home_action)
        self.tradeDecisionMade.emit(home_action)
        self.tradeSelected.emit(home_action)
        self.resourcesPicked.emit(home_action)

    def consume_return_home_request(self) -> bool:
        """Consume and clear any pending return-home request."""
        requested = self.return_home_requested
        self.return_home_requested = False
        return requested

    def show_rules(self):
        """Show the rules window."""
        # Show the rule window
        self.rule_window.show()
        self.rule_window.raise_()  # Bring it to the front
        self.rule_window.activateWindow()  # Focus it

    def show_settings(self):
        """Show the settings window with current values loaded."""
        self.settings_panel.load_settings_into_ui()
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _apply_player_colour_indicators(self) -> None:
        """Apply styled player indicators to the opponent labels."""
        player_label_map = {
            PlayerNumber.P2: self.main_menu.p2_label,
            PlayerNumber.P3: self.main_menu.p3_label,
            PlayerNumber.P4: self.main_menu.p4_label
        }
        for player_number, label in player_label_map.items():
            self._set_player_badge(label, label.text(), player_number,
                                   vertical_padding_px=PLAYER_INDICATOR_BADGE_PADDING_PX[0],
                                   horizontal_padding_px=PLAYER_INDICATOR_BADGE_PADDING_PX[1],
                                   font_size_px=PLAYER_BADGE_FONT_SIZE_PX)

    def _set_turn_label(self, player: Player) -> None:
        """Update the turn label for the active player."""
        self._set_player_badge(self.main_menu.turn_label, f"{player.name}'s turn", player.player_number,
                               vertical_padding_px=TURN_LABEL_BADGE_PADDING_PX[0],
                               horizontal_padding_px=TURN_LABEL_BADGE_PADDING_PX[1])

    def _resolve_turn_label_player(self, player: Player, explanation: ActionExplanation | None = None) -> Player:
        """Resolve which player should be shown in the turn label."""
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

    def _set_player_badge(self, label: QLabel, text: str, player_number: PlayerNumber, vertical_padding_px: int,
                          horizontal_padding_px: int, font_size_px: int | None = None) -> None:
        """Apply the styled player badge text to a label."""
        colour = PLAYER_COLORS[player_number].lighter(PLAYER_BADGE_LIGHTER_FACTOR).name()
        label.setStyleSheet(
            player_badge_stylesheet(colour, vertical_padding_px, horizontal_padding_px, font_size_px=font_size_px))
        label.setText(text)

    def find_last_vertical_spacer(self) -> QSpacerItem | None:
        """Find the last vertical spacer in the main menu layout."""
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
        """Collapse the main menu spacer to reclaim vertical space."""
        if getattr(self, "verticalSpacer", None) is None:
            return

        spacer = self.verticalSpacer
        if not hasattr(spacer, "_original_size"):
            spacer._original_size = (spacer.geometry().width(), spacer.geometry().height(),
                                     spacer.sizePolicy().horizontalPolicy(), spacer.sizePolicy().verticalPolicy())

        spacer.changeSize(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        if self.main_menu.frame.layout() is not None:
            self.main_menu.frame.layout().update()

    def restore_spacer(self):
        """Restore the main menu spacer to its original size."""
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
        """Show or hide the main action buttons."""
        for i in range(self.main_menu.action_btn_layout.count()):
            widget: QWidget = self.main_menu.action_btn_layout.itemAt(i).widget()
            if widget:
                if show:
                    widget.show()
                else:
                    widget.hide()

    def set_main_action_btns_enabled(self, enabled: bool):
        """Enable or disable the main action buttons."""
        for i in range(self.main_menu.action_btn_layout.count()):
            widget: QWidget = self.main_menu.action_btn_layout.itemAt(i).widget()
            if widget:
                widget.setEnabled(enabled)

    def _capture_main_action_btn_enabled_states(self) -> List[bool]:
        """Capture the enabled state of the main action buttons."""
        states: List[bool] = []
        for i in range(self.main_menu.action_btn_layout.count()):
            widget: QWidget = self.main_menu.action_btn_layout.itemAt(i).widget()
            if widget:
                states.append(widget.isEnabled())
        return states

    def _restore_main_action_btn_enabled_states(self):
        """Restore the saved enabled state of the main action buttons."""
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
        """Clear the temporary tutor shortcut handlers."""
        self.debug_tutor_shortcut_handler = None
        self.debug_tutor_shortcut_finalizer = None

    def set_debug_tutor_shortcut_handler(self, handler: Optional[Callable[[], object]]):
        """Store the debug tutor shortcut handler."""
        self.debug_tutor_shortcut_handler = handler

    def set_debug_tutor_shortcut_finalizer(self, finalizer: Optional[Callable[[], None]]):
        """Store the debug tutor shortcut finalizer."""
        self.debug_tutor_shortcut_finalizer = finalizer

    def _clear_tutor_shortcut_ui_state(self) -> None:
        """Clear temporary tutor shortcut UI state."""
        if self.tutor_panel.dismiss_tutor_hint_callback is not None:
            self.tutor_panel.dismiss_tutor_hint_callback()
        self.trade_panel.clear_trade_preview()

    def _try_apply_tutor_shortcut(self, handler: Optional[Callable[[], object]]) -> bool:
        """Try to run the active tutor shortcut handler."""
        if handler is None:
            return False

        self._clear_tutor_shortcut_ui_state()
        result = handler()
        if self.debug_tutor_shortcut_finalizer is not None:
            self.debug_tutor_shortcut_finalizer()
        self.debugShortcutResult.emit(result)
        return True

    def _try_apply_tutor_recommended_move(self) -> bool:
        """Try to apply the tutor-recommended move shortcut."""
        return self._try_apply_tutor_shortcut(self.debug_tutor_shortcut_handler)

    def _show_fullscreen_panel(self, panel: QWidget):
        """Show the fullscreen panel."""
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
        """Refresh hover state after the window is resized."""
        super().resizeEvent(event)
        self.endgame_review_panel.reset_hover()

    def leaveEvent(self, event):
        """Clear hover state when the cursor leaves the window."""
        self.endgame_review_panel.reset_hover()
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        """Handle key presses for window-level shortcuts."""
        if event.key() == Qt.Key.Key_F8 and self._try_apply_tutor_recommended_move():
            event.accept()
            return
        super().keyPressEvent(event)

    def _restore_splitter_layout(self):
        """Restore the main splitter layout after fullscreen panels."""
        if self.fullscreen_panel is not None and self.root_layout.indexOf(self.fullscreen_panel) != -1:
            self.root_layout.removeWidget(self.fullscreen_panel)
            self.fullscreen_panel.setParent(None)
        self.fullscreen_panel = None

        if self.root_layout.indexOf(self.splitter_layout) == -1:
            self.root_layout.addWidget(self.splitter_layout)
        self.splitter_layout.show()

    @staticmethod
    def _clear_layout(layout: QLayout):
        """Remove and delete all widgets from a layout."""
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
        """Handle filtered events for endgame review widgets."""
        if self.endgame_review_panel.handle_event_filter(watched, event):
            return True
        return super().eventFilter(watched, event)

    def closeEvent(self, _):
        """Exit the application when the window closes."""
        quit()

    def display_resources(self, controller: BoardDisplaySource):
        """Display the current board and player resource totals."""
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
        stat_suffixes = {
            "name": "",
            "victory_points": "vic_",
            "num_resources": "res_",
            "development_cards": "dev_",
            "army_size": "army_",
            "longest_road": "road_"
        }
        opponent_prefixes: Dict[PlayerNumber, str] = {
            PlayerNumber.P2: "p2",
            PlayerNumber.P3: "p3",
            PlayerNumber.P4: "p4"
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
                    f"Longest Road:\t{player.longest_road_length} {longest_road_crown}")
                self.main_menu.army_size_label.setText(f"Army Size:\t{player.army_size} {army_crown}")
                self.main_menu.victory_points_label.setText(f"Victory Points:\t{visible_vp}{true_vp_str} {lead_status}")
            else:
                labels = opponent_labels[num]
                status = get_player_lead_status(player)
                if status:
                    name_text = f"{player.name} {status}"
                    labels["name"].setToolTip(f"{player.name} is currently in the lead")
                else:
                    name_text = player.name
                    labels["name"].setToolTip(None)
                self._set_player_badge(labels["name"], name_text, player.player_number,
                                       vertical_padding_px=OPPONENT_BADGE_PADDING_PX[0],
                                       horizontal_padding_px=OPPONENT_BADGE_PADDING_PX[1],
                                       font_size_px=PLAYER_BADGE_FONT_SIZE_PX)
                labels["victory_points"].setText(str(player.calc_victory_points()[0]))
                labels["num_resources"].setText(str(sum(player.resources.values())))
                labels["development_cards"].setText(str(len(player.development_cards)))
                labels["army_size"].setText(str(player.army_size))
                labels["longest_road"].setText(str(player.longest_road_length))

    def display_generic_info(self, player: Player, msg: str):
        """Show a generic status message for the current player."""
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
        """Display the main round UI for a player turn."""
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
        self.safe_connect(
            self.main_menu.trade_btn, lambda: self.display_trade_menu(
                controller, player, lambda: self.display_round_info(controller, player, dice_info, played_dev_card)))
        self.safe_connect(
            self.main_menu.dev_btn, lambda: self.development_panel.show_development_menu(
                controller, player, played_dev_card, lambda played: self.display_round_info(
                    controller, player, dice_info, played)))
        self.safe_connect(self.main_menu.end_turn_btn, lambda: self.turnMade.emit(Action(ActionType.END_TURN)))
        self.tutor_panel.set_restore_tutor_menu_callback(
            lambda: self.display_round_info(controller, player, dice_info, played_dev_card),
            controller.game_mode == GameMode.TUTOR and player.is_human)
        self.set_restore_board_state_callback(None)

    def configure_tutor_panel(self, game_mode: GameMode):
        """Configure the tutor panel for the selected game mode."""
        self.tutor_panel.configure_for_game_mode(game_mode)

    def open_tutor_menu(self, open_menu: bool):
        """Toggle the tutor menu visibility."""
        tutor_host = self._panel_host(self.tutor_menu)
        if open_menu:
            # Avoid adding it twice
            if self.splitter_layout.indexOf(tutor_host) == -1:
                self.splitter_layout.insertWidget(0, tutor_host)
            tutor_host.show()
            self.splitter_layout.setSizes([
                int(MAIN_WINDOW_SIDE_PANEL_WIDTH * TUTOR_PANEL_DEFAULT_WIDTH_RATIO),
                MAIN_WINDOW_BOARD_PANEL_DEFAULT_WIDTH, MAIN_WINDOW_SIDE_PANEL_WIDTH
            ])

        else:
            if self.splitter_layout.indexOf(tutor_host) != -1:
                self._remove_panel_host(self.tutor_menu)
            self.splitter_layout.setSizes([MAIN_WINDOW_BOARD_PANEL_DEFAULT_WIDTH, MAIN_WINDOW_SIDE_PANEL_WIDTH])

    def display_tutor_init(self, player: Player, stage: TutorStage, explanation: ActionExplanation):
        """Display the tutor introduction for the current stage."""
        self.tutor_panel.display_tutor_init(player, stage, explanation)

    def display_explanation(self, player: Player, dice_info: Optional[Tuple[int, int, int]],
                            explanation: ActionExplanation):
        """Display the tutor explanation for the current move."""
        self.tutor_panel.display_explanation(player, dice_info, explanation)

    def display_tutor_action_feedback(self, feedback: TutorFeedbackExplanation) -> None:
        """Display tutor feedback for the player action."""
        self.tutor_panel.display_tutor_action_feedback(feedback)

    def display_trade_menu(self, controller: GameController, player: Player, back_action):
        """Display the trade menu workflow."""
        self.trade_panel.display_trade_menu(controller, player, back_action)

    def select_player_to_trade(self, controller: GameController, player: Player, selling: ResourceCount,
                               buying: ResourceCount, willing_players: List[Tuple[Player, ResourceCount | None]]):
        """Display the player-trade selection workflow."""
        self.trade_panel.select_player_to_trade(controller, player, selling, buying, willing_players)

    def display_round_info_ai_start(self, player: Player, dice_info: Optional[Tuple[int, int, int]], msg: str):
        """Display the waiting state while an AI turn begins."""
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

    def show_resource_chooser(self, player, num_resources: int, title: str, resource_caps: ResourceCount | None = None):
        """Display the resource chooser widget."""
        self.trade_panel.show_resource_chooser(player, num_resources, title, resource_caps)

    def display_trade_manager(self, player: Player, selling: ResourceCount, buying: ResourceCount,
                              selling_player: Player):
        """Display the trade manager widget."""
        self.trade_panel.display_trade_manager(player, selling, buying, selling_player)

    def draw_buildables_if_can_build(self, controller, player):
        """Draw buildable board options when the player can build."""

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
        """Display the game results view."""
        self._clear_debug_tutor_shortcut_context()
        if controller.game_mode in {GameMode.PLAY, GameMode.TUTOR}:
            self.endgame_review_panel.display_tutor_endgame_review(controller)
            return
        self.endgame_review_panel.display_results(controller)

    def _set_primary_side_panel(self, panel: QWidget):
        """Show the given widget as the primary side panel."""
        self._restore_splitter_layout()

        for widget in (self.main_menu, self.start_menu, self.results_menu):
            self._remove_panel_host(widget)

        host = self._panel_host(panel)
        host.setMinimumWidth(0)
        host.setMaximumWidth(MAIN_WINDOW_SIDE_PANEL_MAX_WIDTH)
        self.splitter_layout.addWidget(host)
        host.show()
        self.splitter_layout.setSizes([MAIN_WINDOW_BOARD_PANEL_DEFAULT_WIDTH, MAIN_WINDOW_SIDE_PANEL_WIDTH])

    def display_start_screen(self):
        """Render the start screen artwork on the canvas."""
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

        self.safe_connect(self.start_menu.standard_mode_btn, lambda: play(GameMode.SIMULATION
                                                                          if is_lab_mode() else GameMode.PLAY))
        self.safe_connect(self.start_menu.tutor_mode_btn, lambda: play(GameMode.GUIDED
                                                                       if is_lab_mode() else GameMode.TUTOR))
        self.start_menu.lab_mode_btn.toggled.connect(update_lab_mode)
