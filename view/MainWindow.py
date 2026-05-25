from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QIcon, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QScroller,
)

from ai.actions import Action, ActionType
from ai.tutor.explanations import ActionExplanation
from ai.tutor.feedback import TutorFeedbackExplanation
from ai.tutor.tutor import TutorStage
from config.view_constants import (
    APP_ICON,
    APP_WINDOW_TITLE,
    CROWN_SYM,
    MAIN_WINDOW_SIDE_PANEL_MIN_WIDTH,
    MAIN_WINDOW_SIDE_PANEL_WIDTH_RATIO,
    OPPONENT_BADGE_PADDING_PX,
    PLAYER_BADGE_FONT_SIZE_PX,
    PLAYER_BADGE_LIGHTER_FACTOR,
    PLAYER_COLORS,
    PLAYER_INDICATOR_BADGE_PADDING_PX,
    TURN_LABEL_BADGE_PADDING_PX,
    UI_DEVELOPMENT_MANAGER_PATH,
    UI_ENDGAME_REVIEW_PATH,
    UI_MAIN_MENU_PATH,
    UI_SCOREBOARD_PATH,
    UI_RESOURCE_SELECTOR_PATH,
    UI_RESULTS_MENU_PATH,
    UI_RULES_WINDOW_PATH,
    UI_SELECT_TRADE_PATH,
    UI_SETTINGS_WINDOW_PATH,
    UI_START_MENU_PATH,
    UI_TRADE_DESIGNER_PATH,
    UI_TRADE_MANAGER_PATH,
    UI_TUTOR_MENU_PATH,
)
from controllers.GameController import GameController
from game.Edge import Edge
from game.Player import Player, PlayerNumber
from game.PlayerAssets import Buildable
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from view.canvas.board_display_source import BoardDisplaySource
from view.canvas.display_utils import get_player_lead_status
from view.canvas.SquareCanvas import SquareCanvas
from view.panels.development_panel import DevelopmentPanel
from view.panels.endgame_review_panel import EndgameReviewPanel
from view.panels.settings_panel import SettingsPanel
from view.panels.TradePanel import TradePanel
from view.panels.TutorPanel import TutorPanel
from view.qt_compat import disconnect_signal, load_ui
from view.styles import player_badge_stylesheet
from view.View import GameMode


class MainWindow(QMainWindow):
    startGame = Signal(object)
    turnMade = Signal(object)
    debugShortcutResult = Signal(object)
    tradeDecisionMade = Signal(object)
    tradeSelected = Signal(object)
    resourcesPicked = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_WINDOW_TITLE)
        self.setWindowIcon(QIcon(APP_ICON))

        central = QWidget(self)
        self.setCentralWidget(central)
        self.root_layout = QHBoxLayout(central)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        self.current_page_key = "board"
        self.board_menu_key = "start"
        self.page_history: List[str] = []
        self.tutor_available = False
        self.home_confirmation_armed = False

        self.canvas = SquareCanvas()
        self.main_menu = self._load_ui(UI_MAIN_MENU_PATH)
        self.tutor_menu = self._load_ui(UI_TUTOR_MENU_PATH)
        self.resource_selector_widget = self._load_ui(UI_RESOURCE_SELECTOR_PATH)
        self.trade_designer_widget = self._load_ui(UI_TRADE_DESIGNER_PATH)
        self.select_trade_widget = self._load_ui(UI_SELECT_TRADE_PATH)
        self.trade_manager_widget = self._load_ui(UI_TRADE_MANAGER_PATH)
        self.development_manager_widget = self._load_ui(UI_DEVELOPMENT_MANAGER_PATH)
        self.results_menu = self._load_ui(UI_RESULTS_MENU_PATH)
        self.endgame_review_menu = self._load_ui(UI_ENDGAME_REVIEW_PATH)
        self.start_menu = self._load_ui(UI_START_MENU_PATH)
        self.scoreboard_menu = self._load_ui(UI_SCOREBOARD_PATH)
        self.rule_window = self._load_ui(UI_RULES_WINDOW_PATH)
        self.settings_window = self._load_ui(UI_SETTINGS_WINDOW_PATH)

        for widget in (
            self.main_menu,
            self.tutor_menu,
            self.resource_selector_widget,
            self.trade_designer_widget,
            self.select_trade_widget,
            self.trade_manager_widget,
            self.development_manager_widget,
            self.results_menu,
            self.endgame_review_menu,
            self.start_menu,
            self.scoreboard_menu,
            self.rule_window,
            self.settings_window,
        ):
            self._relax_widget_constraints(widget)

        if hasattr(self.rule_window, "statusbar"):
            self.rule_window.statusbar.hide()
        if hasattr(self.settings_window, "statusbar"):
            self.settings_window.statusbar.hide()
        if hasattr(self.settings_window, "title_label"):
            self.settings_window.title_label.hide()

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

        self._build_landscape_shell()

        self.settings_difficulty_group = QButtonGroup(self.settings_window)
        self.settings_difficulty_group.setExclusive(True)
        self.settings_difficulty_group.addButton(self.settings_window.easy_difficulty_radio)
        self.settings_difficulty_group.addButton(self.settings_window.medium_difficulty_radio)
        self.settings_difficulty_group.addButton(self.settings_window.hard_difficulty_radio)

        self.safe_connect(self.start_menu.settings_btn, self.show_settings)
        self.main_menu.frame_2.hide()
        QApplication.instance().installEventFilter(self)

        self._apply_player_colour_indicators()
        self._apply_touch_friendly_button_sizes()
        self._enable_touch_scrolling()
        self.settings_panel.capture_font_baselines()
        self.settings_panel.load_settings_into_ui()
        self.safe_connect(self.settings_window.apply_btn, self.settings_panel.save_settings)
        self.safe_connect(self.settings_window.reset_defaults_btn, self.settings_panel.reset_settings_to_default)
        self.safe_connect(self.settings_window.close_btn, self.go_back)
        self.settings_window.font_size_spinbox.valueChanged.connect(self.settings_panel.preview_font_size)

        self.verticalSpacer = self.find_last_vertical_spacer()
        self.live_board_source: BoardDisplaySource | None = None
        self.debug_tutor_shortcut_handler: Optional[Callable[[], object]] = None
        self.debug_tutor_shortcut_finalizer: Optional[Callable[[], None]] = None
        self.main_action_btn_enabled_states: List[bool] = []
        self.restore_board_state_callback: Optional[Callable[[], None]] = None
        self.return_home_requested = False

        self.safe_connect(self.main_menu.end_turn_btn, lambda: self.turnMade.emit(Action(ActionType.END_TURN)))
        self._show_page("board", remember=False)
        self._show_board_menu("start")

    @staticmethod
    def _load_ui(path: str) -> QWidget:
        return load_ui(path)

    def _relax_widget_constraints(self, widget: QWidget) -> None:
        widget.setMinimumSize(0, 0)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def _create_scroll_page(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _build_landscape_shell(self) -> None:
        shell = QWidget(self)
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(12, 12, 12, 12)
        shell_layout.setSpacing(12)
        self.landscape_shell = shell
        self.landscape_shell_layout = shell_layout

        self.canvas.setMinimumSize(0, 0)
        self.canvas.setMaximumSize(16777215, 16777215)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        shell_layout.addWidget(self.canvas, 1)

        self.side_panel = QFrame(shell)
        self.side_panel.setMinimumWidth(0)
        self.side_panel.setMaximumWidth(16777215)
        self.side_panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        side_layout = QVBoxLayout(self.side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)

        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(6)
        self.side_main_btn = QPushButton("Your Turn", self.side_panel)
        self.side_scoreboard_btn = QPushButton("Standings", self.side_panel)
        self.side_tutor_toggle_btn = QPushButton("Tutor", self.side_panel)
        self.side_rules_btn = QPushButton("Rules", self.side_panel)
        self.side_home_btn = QPushButton("Home", self.side_panel)
        for button in (
            self.side_main_btn,
            self.side_scoreboard_btn,
            self.side_tutor_toggle_btn,
            self.side_rules_btn,
            self.side_home_btn,
        ):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            nav_layout.addWidget(button)
        side_layout.addLayout(nav_layout)

        self.side_stack = QStackedWidget(self.side_panel)
        side_layout.addWidget(self.side_stack, 1)

        self.side_pages = {
            "start": self._create_scroll_page(self.start_menu),
            "main": self._create_scroll_page(self.main_menu),
            "tutor": self._create_scroll_page(self.tutor_menu),
            "scoreboard": self._create_scroll_page(self.scoreboard_menu),
            "rules": self._create_scroll_page(self.rule_window),
            "settings": self._create_scroll_page(self.settings_window),
            "results": self._create_scroll_page(self.results_menu),
            "endgame": self._create_scroll_page(self.endgame_review_menu),
        }
        for key in ("start", "main", "tutor", "scoreboard", "rules", "settings", "results", "endgame"):
            self.side_stack.addWidget(self.side_pages[key])

        shell_layout.addWidget(self.side_panel)
        self.root_layout.addWidget(shell)
        self._update_side_panel_width()

        self.safe_connect(self.side_main_btn, self.show_main_menu)
        self.safe_connect(self.side_scoreboard_btn, self.show_scoreboard)
        self.safe_connect(self.side_tutor_toggle_btn, self.toggle_tutor_panel)
        self.safe_connect(self.side_rules_btn, self.show_rules)
        self.safe_connect(self.side_home_btn, self.request_return_to_start_screen)

    def _current_side_key(self) -> str:
        if self.current_page_key == "board":
            return self.board_menu_key
        return self.current_page_key

    def _refresh_side_stack(self) -> None:
        self.side_stack.setCurrentWidget(self.side_pages[self._current_side_key()])
        self._update_nav_buttons()

    def _show_page(self, key: str, remember: bool = True) -> None:
        current_key = self._current_side_key()
        if remember and current_key != key:
            self.page_history.append(current_key)
        self.current_page_key = key
        self._refresh_side_stack()

    def _show_board_menu(self, key: str) -> None:
        current_key = self._current_side_key()
        if current_key != key:
            self.page_history = [entry for entry in self.page_history if entry != key]
        self.current_page_key = "board"
        self.board_menu_key = key
        self._refresh_side_stack()

    def _update_nav_buttons(self) -> None:
        current_key = self._current_side_key()
        on_start = current_key == "start"
        in_start_flow = self.board_menu_key == "start" and not self.tutor_available
        self.side_main_btn.setVisible(not in_start_flow)
        self.side_main_btn.setEnabled(not in_start_flow and current_key != "main")
        self.side_scoreboard_btn.setVisible(not in_start_flow)
        self.side_tutor_toggle_btn.setVisible(not in_start_flow)
        self.side_rules_btn.setVisible(not in_start_flow)
        self.side_home_btn.setVisible(not in_start_flow)
        self.side_tutor_toggle_btn.setEnabled(self.tutor_available and not in_start_flow and current_key != "tutor")
        self.side_scoreboard_btn.setEnabled(not in_start_flow and current_key != "scoreboard")
        self.side_rules_btn.setEnabled(not in_start_flow and current_key != "rules")
        self.side_home_btn.setEnabled(not in_start_flow)
        self.side_tutor_toggle_btn.setText("Tutor")
        self.side_home_btn.setText("Confirm?" if self.home_confirmation_armed else "Home")

    def _update_side_panel_width(self) -> None:
        if not hasattr(self, "landscape_shell_layout"):
            return
        margins = self.landscape_shell_layout.contentsMargins()
        spacing = self.landscape_shell_layout.spacing()
        available_width = max(0, self.width() - margins.left() - margins.right() - spacing)
        side_width = max(MAIN_WINDOW_SIDE_PANEL_MIN_WIDTH, int(available_width * MAIN_WINDOW_SIDE_PANEL_WIDTH_RATIO))
        side_width = min(side_width, available_width)
        self.side_panel.setFixedWidth(side_width)

    def toggle_tutor_panel(self) -> None:
        self.reset_home_confirmation()
        if not self.tutor_available:
            return
        if self._current_side_key() == "tutor":
            self._show_board_menu("main")
        else:
            self._show_board_menu("tutor")

    def show_main_menu(self) -> None:
        self.reset_home_confirmation()
        self._show_board_menu("main")

    def go_back(self) -> None:
        self.reset_home_confirmation()
        while self.page_history:
            key = self.page_history.pop()
            if key in {"start", "main", "tutor"}:
                self._show_board_menu(key)
                return
            if key in self.side_pages:
                self.current_page_key = key
                self._refresh_side_stack()
                return
        self._show_board_menu("main" if self.board_menu_key != "start" else "start")

    def safe_connect(self, button: QToolButton | QPushButton, slot: Callable):
        disconnect_signal(button.clicked)  # type: ignore[attr-defined]
        button.clicked.connect(slot)  # type: ignore[attr-defined]

    def set_restore_board_state_callback(self, callback: Optional[Callable[[], None]]):
        self.restore_board_state_callback = callback

    def return_to_start_screen(self):
        self.reset_home_confirmation()
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

    def request_return_to_start_screen(self):
        if not self.home_confirmation_armed:
            self.home_confirmation_armed = True
            self._update_nav_buttons()
            return
        self.return_to_start_screen()

    def reset_home_confirmation(self) -> None:
        if not self.home_confirmation_armed:
            return
        self.home_confirmation_armed = False
        self._update_nav_buttons()

    def show_rules(self):
        self.reset_home_confirmation()
        self._show_page("rules")

    def show_settings(self):
        self.reset_home_confirmation()
        self.settings_panel.load_settings_into_ui()
        self._show_page("settings")

    def show_scoreboard(self):
        self.reset_home_confirmation()
        self._show_page("scoreboard")

    def _apply_touch_friendly_button_sizes(self) -> None:
        for button in self.findChildren(QAbstractButton):
            button.setMinimumHeight(max(button.minimumHeight(), 44))
            if isinstance(button, QToolButton):
                button.setMinimumWidth(max(button.minimumWidth(), 44))

    def _enable_touch_scrolling(self) -> None:
        for scroll_area in self.findChildren(QAbstractScrollArea):
            viewport = scroll_area.viewport()
            if viewport is not None:
                QScroller.grabGesture(viewport, QScroller.ScrollerGestureType.TouchGesture)

    def _apply_player_colour_indicators(self) -> None:
        for menu in (self.main_menu, self.scoreboard_menu):
            player_label_map = {
                PlayerNumber.P2: menu.p2_label,
                PlayerNumber.P3: menu.p3_label,
                PlayerNumber.P4: menu.p4_label,
            }
            for player_number, label in player_label_map.items():
                self._set_player_badge(
                    label,
                    label.text(),
                    player_number,
                    vertical_padding_px=PLAYER_INDICATOR_BADGE_PADDING_PX[0],
                    horizontal_padding_px=PLAYER_INDICATOR_BADGE_PADDING_PX[1],
                    font_size_px=PLAYER_BADGE_FONT_SIZE_PX,
                )

    def _set_turn_label(self, player: Player) -> None:
        self._set_player_badge(
            self.main_menu.turn_label,
            f"{player.name}'s turn",
            player.player_number,
            vertical_padding_px=TURN_LABEL_BADGE_PADDING_PX[0],
            horizontal_padding_px=TURN_LABEL_BADGE_PADDING_PX[1],
        )

    def _resolve_turn_label_player(self, player: Player, explanation: ActionExplanation | None = None) -> Player:
        if explanation is None or not isinstance(self.live_board_source, GameController):
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
        colour = PLAYER_COLORS[player_number].lighter(PLAYER_BADGE_LIGHTER_FACTOR).name()
        label.setStyleSheet(
            player_badge_stylesheet(colour, vertical_padding_px, horizontal_padding_px, font_size_px=font_size_px),
        )
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
        if getattr(self, "verticalSpacer", None) is None:
            return
        spacer = self.verticalSpacer
        if not hasattr(spacer, "_original_size"):
            spacer._original_size = (
                spacer.geometry().width(),
                spacer.geometry().height(),
                spacer.sizePolicy().horizontalPolicy(),
                spacer.sizePolicy().verticalPolicy(),
            )
        spacer.changeSize(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        if self.main_menu.frame.layout() is not None:
            self.main_menu.frame.layout().update()

    def restore_spacer(self):
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
                widget.setVisible(show)

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
        if self.home_confirmation_armed and event.type() == QEvent.Type.MouseButtonPress:
            click_target: QObject = watched
            if isinstance(event, QMouseEvent):
                widget_at_pos = QApplication.widgetAt(event.globalPosition().toPoint())
                if widget_at_pos is not None:
                    click_target = widget_at_pos
            if not self._is_home_button_target(click_target):
                self.reset_home_confirmation()
        if self.endgame_review_panel.handle_event_filter(watched, event):
            return True
        return super().eventFilter(watched, event)

    def _is_home_button_target(self, watched: QObject) -> bool:
        if watched is self.side_home_btn:
            return True
        if isinstance(watched, QWidget):
            return self.side_home_btn.isAncestorOf(watched)
        return False

    def closeEvent(self, _):
        quit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_side_panel_width()
        self.endgame_review_panel.reset_hover()

    def leaveEvent(self, event):
        self.endgame_review_panel.reset_hover()
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_F8 and self._try_apply_tutor_recommended_move():
            event.accept()
            return
        super().keyPressEvent(event)

    def display_resources(self, controller: BoardDisplaySource):
        if isinstance(controller, GameController):
            self.live_board_source = controller

        for scoreboard in (self.scoreboard_menu,):
            bank_labels: Dict[Resource, QLabel] = {
                res: getattr(scoreboard, f"bank_{res.name.lower()}_label")
                for res in Resource
            }
            for res, label in bank_labels.items():
                label.setText(str(controller.get_bank_resources()[res]))
            scoreboard.bank_dev_label.setText(str(controller.get_development_deck().size()))

        stat_suffixes = {
            "name": "",
            "victory_points": "vic_",
            "num_resources": "res_",
            "development_cards": "dev_",
            "army_size": "army_",
            "longest_road": "road_",
        }
        opponent_prefixes: Dict[PlayerNumber, str] = {
            PlayerNumber.P2: "p2",
            PlayerNumber.P3: "p3",
            PlayerNumber.P4: "p4",
        }
        opponent_views = {
            menu: {
                pn: {
                    stat: getattr(menu, f"{opponent_prefixes[pn]}_{suffix}label")
                    for stat, suffix in stat_suffixes.items()
                }
                for pn in opponent_prefixes
            }
            for menu in (self.scoreboard_menu,)
        }
        player_labels: Dict[Resource, QLabel] = {
            res: getattr(self.main_menu, f"{res.name.lower()}_label")
            for res in Resource
        }

        for player in controller.get_all_players():
            if player.player_number == PlayerNumber.P1:
                for res, label in player_labels.items():
                    label.setText(str(player.resources[res]))
                visible_vp, true_vp = player.calc_victory_points()
                true_vp_str = f" ({true_vp})" if visible_vp != true_vp else ""
                longest_road_crown = CROWN_SYM if player.has_longest_road else ""
                army_crown = CROWN_SYM if player.has_largest_army else ""
                lead_status = get_player_lead_status(player)
                self.main_menu.longest_road_label.setText(
                    f"Longest Road:\t{player.longest_road_length} {longest_road_crown}",
                )
                self.main_menu.army_size_label.setText(f"Army Size:\t{player.army_size} {army_crown}")
                self.main_menu.victory_points_label.setText(
                    f"Victory Points:\t{visible_vp}{true_vp_str} {lead_status}",
                )
            else:
                for opponent_labels in opponent_views.values():
                    labels = opponent_labels[player.player_number]
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
                        vertical_padding_px=OPPONENT_BADGE_PADDING_PX[0],
                        horizontal_padding_px=OPPONENT_BADGE_PADDING_PX[1],
                        font_size_px=PLAYER_BADGE_FONT_SIZE_PX,
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
        self._show_board_menu("main")

    def display_round_info(
        self,
        controller: GameController,
        player: Player,
        dice_info: Tuple[int, int, int],
        played_dev_card: bool = False,
    ):
        self.tutor_panel.reset_for_turn()
        self.canvas.clear_feedback_builds()
        self.canvas.interactive_shapes.clear()
        self.canvas.disable_interactivity = False
        self.canvas.display_board(controller)
        self.display_resources(controller)
        self._show_board_menu("main")

        if controller.game_mode == GameMode.TUTOR and player.is_human:
            explanation = controller.get_tutor_turn_explanation(player, played_dev_card)
            if explanation is not None:
                self.display_tutor_init(player, TutorStage.TURN_ACTION, explanation)

        d1, d2, total = dice_info
        self._set_turn_label(player)
        self.main_menu.main_label.setText(f"Dice rolled: {d1} + {d2} = {total}\nWhat would you like to do?")
        self.toggle_main_action_btns(True)
        self.set_main_action_btns_enabled(True)

        self.draw_buildables_if_can_build(controller, player)
        can_afford_card = controller.get_buildable_options(player)[Buildable.DEVELOPMENT_CARD]
        self.main_menu.dev_btn.setEnabled(can_afford_card or len(player.development_cards) > 0)
        self.main_menu.trade_btn.setEnabled(sum(player.resources.values()) > 0)
        self.safe_connect(
            self.main_menu.trade_btn,
            lambda: self.display_trade_menu(
                controller,
                player,
                lambda: self.display_round_info(controller, player, dice_info, played_dev_card),
            ),
        )
        self.safe_connect(
            self.main_menu.dev_btn,
            lambda: self.development_panel.show_development_menu(
                controller,
                player,
                played_dev_card,
                lambda played: self.display_round_info(controller, player, dice_info, played),
            ),
        )
        self.safe_connect(self.main_menu.end_turn_btn, lambda: self.turnMade.emit(Action(ActionType.END_TURN)))
        self.tutor_panel.set_restore_tutor_menu_callback(
            lambda: self.display_round_info(controller, player, dice_info, played_dev_card),
            controller.game_mode == GameMode.TUTOR and player.is_human,
        )
        self.set_restore_board_state_callback(None)

    def configure_tutor_panel(self, game_mode: GameMode):
        self.tutor_available = game_mode == GameMode.TUTOR
        self.tutor_panel.configure_for_game_mode(game_mode)
        if not self.tutor_available and self.board_menu_key == "tutor":
            self._show_board_menu("main")
        else:
            self._update_nav_buttons()

    def open_tutor_menu(self, open_menu: bool):
        if open_menu and self.tutor_available:
            self._show_board_menu("tutor")
        else:
            self._show_board_menu("main")

    def display_tutor_init(self, player: Player, stage: TutorStage, explanation: ActionExplanation):
        self.tutor_panel.display_tutor_init(player, stage, explanation)

    def display_explanation(
        self,
        player: Player,
        dice_info: Optional[Tuple[int, int, int]],
        explanation: ActionExplanation,
    ):
        self.tutor_panel.display_explanation(player, dice_info, explanation)

    def display_tutor_action_feedback(self, feedback: TutorFeedbackExplanation) -> None:
        self._show_board_menu("tutor")
        self.tutor_panel.display_tutor_action_feedback(feedback)

    def record_tutor_action_feedback(self, feedback: TutorFeedbackExplanation) -> None:
        self.tutor_panel.record_tutor_feedback(feedback)

    def should_auto_review(self) -> bool:
        return self.tutor_panel.should_auto_review()

    def display_trade_menu(self, controller: GameController, player: Player, back_action):
        self.trade_panel.display_trade_menu(controller, player, back_action)

    def select_player_to_trade(
        self,
        controller: GameController,
        player: Player,
        selling: ResourceCount,
        buying: ResourceCount,
        willing_players: List[Tuple[Player, ResourceCount | None]],
    ):
        self.trade_panel.select_player_to_trade(controller, player, selling, buying, willing_players)

    def display_round_info_ai_start(self, player: Player, dice_info: Optional[Tuple[int, int, int]], msg: str):
        self._clear_debug_tutor_shortcut_context()
        self.tutor_panel.prepare_ai_wait_state()
        self.canvas.clear_feedback_builds()
        self.set_restore_board_state_callback(None)
        self.trade_panel.clear_trade_preview()
        self.canvas.clear_planned_builds()
        self._show_board_menu("main")

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
        self.trade_panel.show_resource_chooser(player, num_resources, title, resource_caps)

    def display_trade_manager(self, player: Player, selling: ResourceCount, buying: ResourceCount, selling_player: Player):
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
            disconnect_signal(self.canvas.selectionMade)
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

    def display_start_screen(self):
        self.return_home_requested = False
        self.reset_home_confirmation()
        self._clear_debug_tutor_shortcut_context()
        self.tutor_available = False
        self.tutor_panel.reset_for_start_screen()
        self.trade_panel.clear_trade_preview()
        self.restore_spacer()
        self.canvas.clear_planned_builds()
        self.canvas.interactive_shapes.clear()
        self.canvas.display_start_screen()
        self._show_board_menu("start")

        def play(game_mode: GameMode):
            self._show_board_menu("main")
            self.startGame.emit(game_mode)

        self.safe_connect(
            self.start_menu.start_game_btn,
            lambda: play(GameMode.TUTOR),
        )
        self.safe_connect(self.start_menu.settings_btn, self.show_settings)
        self._update_nav_buttons()
