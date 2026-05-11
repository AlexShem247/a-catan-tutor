from itertools import groupby
import math
import re
from typing import Dict, Tuple, List, Callable, Optional, Any

from PyQt6 import uic
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QPoint, QPointF, QEvent, QObject, QSize
from PyQt6.QtGui import QBrush, QCloseEvent, QColor, QCursor, QIcon, QKeyEvent, QPainter, QPen, QPixmap
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter, QLabel, QToolButton, QSpacerItem,
    QSizePolicy, QPushButton, QAbstractScrollArea, QListWidgetItem, QLayout, QFrame, QVBoxLayout, QCheckBox,
    QButtonGroup
)

from GameController import GameController, PlayerScoreSnapshot
from ai.actions import Action, ActionType
from ai.tutor.explanations import ActionExplanation, ExplanationTemplate
from ai.tutor.feedback import TutorDecisionType, TutorFeedbackExplanation, move_quality_colour
from ai.tutor.move_quality import move_quality_label
from ai.tutor.tutor import TutorStage, TUTOR_STAGE_CONTENT
from game.Edge import Edge
from game.Player import PlayerNumber, Player
from game.PlayerAssets import Buildable, DevelopmentCardType, DevelopmentCard
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from view.board_display_source import BoardDisplaySource
from view.SquareCanvas import SquareCanvas
from config.view_constants import (
    APP_ICON,
    CROWN_SYM,
    ENDGAME_PLOT_BACKGROUND_COLOR,
    TUTOR_FEEDBACK_FADE_STEPS,
    TUTOR_FEEDBACK_MAX_DISPLAY_SECONDS,
    TUTOR_FEEDBACK_MIN_DISPLAY_SECONDS,
    endgame_rank_card_stylesheet,
    HOME_ICON,
    PLAYER_COLORS,
    RULES_ICON,
    SETTINGS_ICON,
    TOOLTIP_BACKGROUND_COLOR,
    TOOLTIP_BORDER_COLOR,
    TOOLTIP_TEXT_COLOR,
)
from config.settings import (load_default_settings, load_effective_settings, save_applied_settings,
                             reset_applied_settings)
from view.rich_text import (
    TROPHY_ICON_PATH,
    concise_explanation_html,
    player_breakdown_html,
    strip_html_to_plain_text,
    tutor_focus_html,
    tutor_window_title_html,
    winner_title_html,
)
from view.styles import (
    endgame_badge_stylesheet,
    endgame_feedback_body_stylesheet,
    endgame_feedback_card_stylesheet,
    endgame_feedback_empty_stylesheet,
    endgame_feedback_score_stylesheet,
    endgame_feedback_title_stylesheet,
    player_badge_stylesheet,
    tutor_feedback_action_stylesheet,
    tutor_feedback_explanation_stylesheet,
)
from view.View import GameMode
from view.display_utils import format_counter_offer, get_player_lead_status


class IntegerAxisItem(pg.AxisItem):
    def tickSpacing(self, minVal: float, maxVal: float, size: float) -> List[Tuple[float, float]]:
        value_range = abs(maxVal - minVal)
        if value_range <= 0 or size <= 0:
            return [(1.0, 0.0)]

        target_tick_count = max(2, int(size / 80))
        raw_spacing = max(1.0, value_range / target_tick_count)
        magnitude = 10 ** math.floor(math.log10(raw_spacing))

        for multiplier in (1, 2, 5, 10):
            spacing = magnitude * multiplier
            if spacing >= raw_spacing:
                spacing = max(1.0, round(spacing))
                return [(float(spacing), 0.0)]

        spacing = max(1.0, round(magnitude * 10))
        return [(float(spacing), 0.0)]

    def tickStrings(self, values: List[float], scale: float, spacing: float) -> List[str]:
        return [str(int(round(value))) for value in values]


class HoverTooltip(QFrame):
    BORDER_RADIUS = 8

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        self.setObjectName("hoverTooltip")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(False)
        label_palette = self.label.palette()
        label_palette.setColor(self.label.foregroundRole(), TOOLTIP_TEXT_COLOR)
        self.label.setPalette(label_palette)
        layout.addWidget(self.label)
        self.hide()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(TOOLTIP_BORDER_COLOR, 1))
        painter.setBrush(QBrush(TOOLTIP_BACKGROUND_COLOR))
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.drawRoundedRect(rect, self.BORDER_RADIUS, self.BORDER_RADIUS)
        super().paintEvent(event)

    def show_text(self, text: str, global_pos) -> None:
        self.label.setText(text)
        self.adjustSize()
        if not isinstance(global_pos, QPoint):
            global_pos = QPoint(int(global_pos.x()), int(global_pos.y()))

        x_pos = global_pos.x() + 16
        y_pos = global_pos.y() + 16

        screen = self.parentWidget().screen() if self.parentWidget() is not None else self.screen()
        if screen is not None:
            screen_rect = screen.availableGeometry()
            if x_pos + self.width() > screen_rect.right():
                x_pos = max(screen_rect.left(), global_pos.x() - self.width() - 16)
            if y_pos + self.height() > screen_rect.bottom():
                y_pos = max(screen_rect.top(), global_pos.y() - self.height() - 16)

        self.move(x_pos, y_pos)
        self.show()
        self.raise_()


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
        self.tutor_menu.explanation_edit.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.tutor_menu.explanation_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tutor_menu.explanation_edit.setLineWrapMode(self.tutor_menu.explanation_edit.LineWrapMode.WidgetWidth)

        self.resource_selector_widget = uic.loadUi("view/ui/resource_selector.ui")
        self.trade_designer_widget = uic.loadUi("view/ui/trade_designer.ui")
        self.select_trade_widget = uic.loadUi("view/ui/select_trade.ui")
        self.trade_manager_widget = uic.loadUi("view/ui/trade_manager.ui")
        self.development_manager_widget = uic.loadUi("view/ui/development_manager.ui")
        self.development_manager_widget = uic.loadUi("view/ui/development_manager.ui")
        self.results_menu = uic.loadUi("view/ui/results_menu.ui")
        self.endgame_review_menu = uic.loadUi("view/ui/endgame_review.ui")
        self.start_menu = uic.loadUi("view/ui/start_menu.ui")
        self.endgame_winner_trophy_label = QLabel(self.endgame_review_menu)
        self.endgame_winner_trophy_label.setObjectName("winnerTrophyLabel")
        self.endgame_winner_trophy_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.endgame_winner_trophy_label.setFixedSize(QSize(80, 80))
        self.endgame_winner_trophy_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.endgame_review_menu.globalHeaderLayout.insertWidget(0, self.endgame_winner_trophy_label)
        self.endgame_replay_canvas = SquareCanvas()
        self.endgame_replay_canvas.setMinimumSize(0, 0)
        self.endgame_replay_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.endgame_replay_canvas.disable_interactivity = True
        self.endgame_review_menu.replayMainLayout.removeWidget(self.endgame_review_menu.selectedMomentScrollArea)
        self.endgame_replay_splitter = QSplitter(Qt.Orientation.Horizontal, self.endgame_review_menu.replayTab)
        self.endgame_replay_splitter.setChildrenCollapsible(False)
        self.endgame_replay_splitter.setHandleWidth(8)
        self.endgame_replay_splitter.addWidget(self.endgame_replay_canvas)
        self.endgame_replay_splitter.addWidget(self.endgame_review_menu.selectedMomentScrollArea)
        self.endgame_replay_splitter.setStretchFactor(0, 1)
        self.endgame_replay_splitter.setStretchFactor(1, 1)
        self.endgame_replay_splitter.splitterMoved.connect(self._mark_endgame_replay_splitter_adjusted)
        self.endgame_review_menu.replayMainLayout.replaceWidget(
            self.endgame_review_menu.boardPlaceholder, self.endgame_replay_splitter
        )
        self.endgame_review_menu.boardPlaceholder.setParent(None)
        self.endgame_review_menu.boardPlaceholder.deleteLater()
        self.endgame_review_menu.replayTab.installEventFilter(self)
        self.endgame_review_menu.selectedMomentScrollArea.installEventFilter(self)
        self.victory_points_plot = pg.PlotWidget(
            axisItems={
                "bottom": IntegerAxisItem(orientation="bottom"),
                "left": IntegerAxisItem(orientation="left"),
            }
        )
        self.victory_points_plot.setObjectName("victoryPointsPlot")
        self.victory_points_plot.setBackground(ENDGAME_PLOT_BACKGROUND_COLOR)
        self.victory_points_plot.setMinimumSize(0, 0)
        self.victory_points_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.endgame_review_menu.performanceLayout.replaceWidget(
            self.endgame_review_menu.graphPlaceholder, self.victory_points_plot
        )
        self.endgame_review_menu.graphPlaceholder.setParent(None)
        self.endgame_review_menu.graphPlaceholder.deleteLater()
        self.endgame_plot_points: List[Tuple[int, float, float]] = []
        self.endgame_plot_tooltips: Dict[int, str] = {}
        self.active_endgame_tooltip_round: int | None = None
        self.last_endgame_tooltip_text: str | None = None
        self.hover_tooltip = HoverTooltip(self)
        self.endgame_replay_feedback: List[TutorFeedbackExplanation] = []
        self.endgame_replay_index: int | None = None
        self.endgame_total_turns = 0
        self.endgame_replay_splitter_user_adjusted = False
        self.endgame_replay_splitter_initialised = False
        self.endgame_feedback_filter_checkboxes: Dict[str, QCheckBox] = {}
        scene = self.victory_points_plot.scene()
        if scene is not None and hasattr(scene, "sigMouseMoved"):
            scene.sigMouseMoved.connect(self._handle_endgame_plot_hover)

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
        self._configure_endgame_feedback_filters()
        self._capture_font_baselines()
        self._load_settings_into_ui()
        self.safe_connect(self.settings_window.apply_btn, self.save_settings)
        self.safe_connect(self.settings_window.reset_defaults_btn, self.reset_settings_to_default)
        self.safe_connect(self.settings_window.close_btn, self.close_settings_window)
        self.settings_window.font_size_spinbox.valueChanged.connect(self.preview_font_size)

        self.history_nav_widget = QWidget(self.tutor_menu)
        self.history_nav_layout = QHBoxLayout(self.history_nav_widget)
        self.history_nav_layout.setContentsMargins(0, 0, 0, 0)
        self.history_prev_btn = QPushButton("<")
        self.history_detail_btn = QPushButton("Show Detailed")
        self.history_next_btn = QPushButton(">")
        self.history_prev_btn.setFixedSize(40, 40)
        self.history_next_btn.setFixedSize(40, 40)
        self.history_detail_btn.setFixedHeight(40)
        self.history_nav_layout.addWidget(self.history_prev_btn)
        self.history_nav_layout.addWidget(self.history_detail_btn)
        self.history_nav_layout.addWidget(self.history_next_btn)
        self.history_exit_btn = QPushButton("Close History")
        self.history_exit_btn.setFixedHeight(40)
        self.tutor_menu.verticalLayout_3.addWidget(self.history_nav_widget)
        self.tutor_menu.verticalLayout_3.addWidget(self.history_exit_btn)
        self.history_nav_widget.hide()
        self.history_exit_btn.hide()

        self.verticalSpacer = self.find_last_vertical_spacer()
        self.active_trade_preview_widget: QWidget | None = None
        self.tutor_feedback_fade_timer: QTimer | None = None
        self.tutor_feedback_advance_timer: QTimer | None = None
        self.live_board_source: BoardDisplaySource | None = None
        self.tutor_feedback_history: List[TutorFeedbackExplanation] = []
        self.tutor_feedback_replay_history: List[TutorFeedbackExplanation] = []
        self.history_feedback_index: int | None = None
        self.history_feedback_detailed = False
        self.history_enabled_on_turn = False
        self.history_available_in_mode = False
        self.history_mode_active = False
        self.endgame_rank_cards: List[QPushButton] = []
        self.selected_endgame_rank_card: QPushButton | None = None
        self.fullscreen_panel: Optional[QWidget] = None
        self.debug_tutor_shortcut_handler: Optional[Callable[[], object]] = None
        self.debug_tutor_shortcut_finalizer: Optional[Callable[[], None]] = None
        self.main_action_btn_enabled_states: List[bool] = []
        self.restore_tutor_menu_callback: Optional[Callable[[], None]] = None
        self.dismiss_tutor_hint_callback: Optional[Callable[[], None]] = None
        self.restore_board_state_callback: Optional[Callable[[], None]] = None
        self.return_home_requested = False
        self.safe_connect(self.main_menu.end_turn_btn, lambda: self.turnMade.emit(Action(ActionType.END_TURN)))
        self.safe_connect(self.main_menu.home_btn, self.return_to_start_screen)
        self.safe_connect(self.tutor_menu.previous_feedback_btn, self.show_previous_feedback_history)

    def safe_connect(self, button: QToolButton | QPushButton, slot: Callable):
        try:
            button.clicked.disconnect()  # type: ignore[attr-defined]
        except TypeError:
            pass
        button.clicked.connect(slot)

    def _hide_history_controls(self):
        self.history_nav_widget.hide()
        self.history_exit_btn.hide()
        self._update_previous_feedback_button()

    def _update_previous_feedback_button(self):
        visible = (
                self.history_available_in_mode
                and self.history_enabled_on_turn
                and bool(self.tutor_feedback_history)
                and not self.history_mode_active
        )
        self.tutor_menu.previous_feedback_btn.setVisible(visible)
        self.tutor_menu.previous_feedback_btn.setEnabled(visible)

    def _set_history_enabled(self, enabled: bool):
        self.history_enabled_on_turn = enabled
        self._update_previous_feedback_button()

    def _set_restore_tutor_menu_callback(self, callback: Optional[Callable[[], None]], allow_history: bool):
        self.restore_tutor_menu_callback = callback
        self._set_history_enabled(allow_history)

    def _set_dismiss_tutor_hint_callback(self, callback: Optional[Callable[[], None]]):
        self.dismiss_tutor_hint_callback = callback

    def set_restore_board_state_callback(self, callback: Optional[Callable[[], None]]):
        self.restore_board_state_callback = callback

    def _append_tutor_feedback_history(self, feedback: TutorFeedbackExplanation):
        self.tutor_feedback_replay_history.append(feedback)
        self.tutor_feedback_history.append(feedback)
        if len(self.tutor_feedback_history) > 100:
            self.tutor_feedback_history = self.tutor_feedback_history[-100:]
        self._update_previous_feedback_button()

    def _render_feedback_history_item(self):
        if self.history_feedback_index is None:
            return

        feedback = self.tutor_feedback_history[self.history_feedback_index]
        self.canvas.display_board(feedback.board_snapshot)
        self.canvas.clear_planned_builds()
        if feedback.recommended_visual_plan:
            self.canvas.render_planned_builds(feedback.recommended_visual_plan)
        self.canvas.render_feedback_builds(feedback.visual_build_plan)
        self.display_resources(feedback.board_snapshot)
        item_num = self.history_feedback_index + 1
        total = len(self.tutor_feedback_history)
        self.tutor_menu.action_label.setText(f"{feedback.title} ({item_num}/{total})")
        self.tutor_menu.explanation_edit.setHtml(feedback.render_html(self.history_feedback_detailed))
        self.history_prev_btn.setEnabled(self.history_feedback_index > 0)
        self.history_next_btn.setEnabled(self.history_feedback_index < total - 1)
        self.history_detail_btn.setText("Show Concise" if self.history_feedback_detailed else "Show Detailed")

    def show_previous_feedback_history(self):
        if not self.history_enabled_on_turn or not self.tutor_feedback_history:
            return

        self._stop_auto_tutor_feedback()
        if self.dismiss_tutor_hint_callback is not None:
            self.dismiss_tutor_hint_callback()
        self.main_action_btn_enabled_states = self._capture_main_action_btn_enabled_states()
        self.set_main_action_btns_enabled(False)
        self.history_mode_active = True
        self._update_previous_feedback_button()
        self.history_feedback_index = len(self.tutor_feedback_history) - 1
        self.history_feedback_detailed = False
        self.tutor_menu.explain_btn.hide()
        self.tutor_menu.continue_btn.hide()
        self.history_nav_widget.show()
        self.history_exit_btn.show()

        self.safe_connect(self.history_prev_btn, self._show_older_feedback)
        self.safe_connect(self.history_next_btn, self._show_newer_feedback)
        self.safe_connect(self.history_detail_btn, self._toggle_feedback_detail)
        self.safe_connect(self.history_exit_btn, self._exit_feedback_history)
        self._render_feedback_history_item()

    def _show_older_feedback(self):
        if self.history_feedback_index is None or self.history_feedback_index <= 0:
            return
        self.history_feedback_index -= 1
        self._render_feedback_history_item()

    def _show_newer_feedback(self):
        if self.history_feedback_index is None or self.history_feedback_index >= len(self.tutor_feedback_history) - 1:
            return
        self.history_feedback_index += 1
        self._render_feedback_history_item()

    def _toggle_feedback_detail(self):
        self.history_feedback_detailed = not self.history_feedback_detailed
        self._render_feedback_history_item()

    def _exit_feedback_history(self):
        self.history_mode_active = False
        self._hide_history_controls()
        self.canvas.clear_feedback_builds()
        if self.restore_board_state_callback is not None:
            self.restore_board_state_callback()
        if self.restore_tutor_menu_callback is not None:
            self.restore_tutor_menu_callback()
        elif self.live_board_source is not None:
            self.canvas.display_board(self.live_board_source)
            self.display_resources(self.live_board_source)
        self._restore_main_action_btn_enabled_states()
        self.history_feedback_index = None
        self.history_feedback_detailed = False

    def return_to_start_screen(self):
        self._stop_auto_tutor_feedback()
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
        self._load_settings_into_ui()
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _current_settings_from_ui(self) -> Dict[str, Any]:
        difficulty = "medium"
        if self.settings_window.easy_difficulty_radio.isChecked():
            difficulty = "easy"
        elif self.settings_window.hard_difficulty_radio.isChecked():
            difficulty = "hard"

        return {
            "font_size": self.settings_window.font_size_spinbox.value(),
            "ai_difficulty": difficulty,
        }

    def _load_settings_into_ui(self) -> None:
        settings = load_effective_settings()
        self.settings_window.font_size_spinbox.blockSignals(True)
        self.settings_window.font_size_spinbox.setValue(int(settings["font_size"]))
        self.settings_window.font_size_spinbox.blockSignals(False)
        self._update_font_size_label()
        self._preview_font_size_label(int(settings["font_size"]))
        self._apply_font_size(int(settings["font_size"]))

        difficulty_buttons = {
            "easy": self.settings_window.easy_difficulty_radio,
            "medium": self.settings_window.medium_difficulty_radio,
            "hard": self.settings_window.hard_difficulty_radio,
        }
        difficulty_buttons.get(settings["ai_difficulty"], self.settings_window.medium_difficulty_radio).setChecked(True)

    def save_settings(self) -> None:
        settings = self._current_settings_from_ui()
        save_applied_settings(settings)
        self._apply_font_size(int(settings["font_size"]))

    def reset_settings_to_default(self) -> None:
        reset_applied_settings()
        defaults = load_default_settings()
        self.settings_window.font_size_spinbox.setValue(int(defaults["font_size"]))
        difficulty_buttons = {
            "easy": self.settings_window.easy_difficulty_radio,
            "medium": self.settings_window.medium_difficulty_radio,
            "hard": self.settings_window.hard_difficulty_radio,
        }
        difficulty_buttons.get(defaults["ai_difficulty"], self.settings_window.medium_difficulty_radio).setChecked(True)
        self._update_font_size_label()
        self._preview_font_size_label(int(defaults["font_size"]))
        self._apply_font_size(int(defaults["font_size"]))

    def preview_font_size(self, value: int) -> None:
        self._update_font_size_label()
        self._preview_font_size_label(value)

    def close_settings_window(self) -> None:
        self.settings_window.close()

    def _capture_font_baselines(self) -> None:
        roots = [
            self,
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
            self.rule_window,
            self.settings_window,
        ]
        for root in roots:
            for widget in [root, *root.findChildren(QWidget)]:
                font = widget.font()
                point_size = font.pointSize()
                if point_size > 0 and widget.property("basePointSize") is None:
                    widget.setProperty("basePointSize", point_size)
                if widget.property("baseMinimumHeight") is None:
                    widget.setProperty("baseMinimumHeight", widget.minimumHeight())
                if widget.property("baseMaximumHeight") is None:
                    widget.setProperty("baseMaximumHeight", widget.maximumHeight())
        self._capture_static_rich_text_baselines()

    def _capture_static_rich_text_baselines(self) -> None:
        for widget in (self.start_menu.textEdit, self.rule_window.textEdit):
            if widget.property("baseHtml") is None:
                widget.setProperty("baseHtml", widget.toHtml())

    def _apply_font_size(self, value: int) -> None:
        delta = value - 10
        roots = [
            self,
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
            self.rule_window,
            self.settings_window,
        ]
        for root in roots:
            for widget in [root, *root.findChildren(QWidget)]:
                base_point_size = widget.property("basePointSize")
                if base_point_size is None:
                    continue
                font = widget.font()
                font.setPointSize(max(1, int(base_point_size) + delta))
                widget.setFont(font)
        self._adjust_widget_heights()
        self._apply_static_rich_text_font_size(delta)

    def _apply_static_rich_text_font_size(self, delta: int) -> None:
        for widget in (self.start_menu.textEdit, self.rule_window.textEdit):
            base_html = widget.property("baseHtml")
            if not base_html:
                continue
            adjusted_html = re.sub(
                r"font-size:([0-9]+)pt",
                lambda match: f"font-size:{max(1, int(match.group(1)) + delta)}pt",
                str(base_html),
            )
            cursor = widget.textCursor()
            widget.setHtml(adjusted_html)
            widget.setTextCursor(cursor)

    def _adjust_widget_heights(self) -> None:
        roots = [
            self,
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
            self.rule_window,
            self.settings_window,
        ]
        unrestricted_max_height = 16777215
        for root in roots:
            for widget in [root, *root.findChildren(QWidget)]:
                base_min_height = widget.property("baseMinimumHeight")
                if base_min_height is not None and int(base_min_height) > 0:
                    widget.setMinimumHeight(max(int(base_min_height), widget.sizeHint().height()))

                base_max_height = widget.property("baseMaximumHeight")
                if (
                    base_max_height is not None
                    and 0 < int(base_max_height) < unrestricted_max_height
                ):
                    widget.setMaximumHeight(max(int(base_max_height), widget.sizeHint().height()))

    def _update_font_size_label(self) -> None:
        self.settings_window.font_size_label.setText("Font Size")

    def _preview_font_size_label(self, value: int) -> None:
        base_point_size = self.settings_window.font_size_label.property("basePointSize")
        if base_point_size is None:
            return
        font = self.settings_window.font_size_label.font()
        font.setPointSize(max(1, int(base_point_size) + (value - 10)))
        self.settings_window.font_size_label.setFont(font)

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
        if self.dismiss_tutor_hint_callback is not None:
            self.dismiss_tutor_hint_callback()
        self.clear_trade_preview()

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

    def _handle_endgame_plot_hover(self, scene_pos: QPointF):
        if not self.endgame_plot_points or self.fullscreen_panel is not self.endgame_review_menu:
            self.active_endgame_tooltip_round = None
            self.last_endgame_tooltip_text = None
            self.hover_tooltip.hide()
            return

        plot_item = self.victory_points_plot.getPlotItem()
        view_box = plot_item.vb
        if not self.victory_points_plot.sceneBoundingRect().contains(scene_pos):
            self.active_endgame_tooltip_round = None
            self.last_endgame_tooltip_text = None
            self.hover_tooltip.hide()
            return

        nearest_round: int | None = None
        nearest_distance: float | None = None
        for round_num, x_value, y_value in self.endgame_plot_points:
            point_scene = view_box.mapViewToScene(QPointF(x_value, y_value))
            distance = (point_scene.x() - scene_pos.x()) ** 2 + (point_scene.y() - scene_pos.y()) ** 2
            if nearest_distance is None or distance < nearest_distance:
                nearest_round = round_num
                nearest_distance = distance

        if nearest_round is None or nearest_distance is None or nearest_distance > 100:
            self.active_endgame_tooltip_round = None
            self.last_endgame_tooltip_text = None
            self.hover_tooltip.hide()
            return

        tooltip = self.endgame_plot_tooltips.get(nearest_round)
        if not tooltip:
            self.active_endgame_tooltip_round = None
            self.last_endgame_tooltip_text = None
            self.hover_tooltip.hide()
            return

        global_pos = QCursor.pos()
        if self.active_endgame_tooltip_round == nearest_round and self.last_endgame_tooltip_text == tooltip:
            self.hover_tooltip.show_text(tooltip, global_pos)
            return

        self.active_endgame_tooltip_round = nearest_round
        self.last_endgame_tooltip_text = tooltip
        self.hover_tooltip.show_text(tooltip, global_pos)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.active_endgame_tooltip_round = None
        self.last_endgame_tooltip_text = None
        self.hover_tooltip.hide()

    def leaveEvent(self, event):
        self.active_endgame_tooltip_round = None
        self.last_endgame_tooltip_text = None
        self.hover_tooltip.hide()
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

    @staticmethod
    def _get_player_victory_breakdown(player: Player) -> Dict[str, int]:
        return {
            "settlements": len(player.settlements),
            "cities": len(player.cities) * 2,
            "longest_road": 2 if player.has_longest_road else 0,
            "largest_army": 2 if player.has_largest_army else 0,
            "victory_cards": len(
                [card for card in player.development_cards if card.card_type == DevelopmentCardType.VICTORY_POINT]
            ),
        }

    @classmethod
    def _format_player_breakdown_text(cls, player: Player) -> str:
        breakdown = cls._get_player_victory_breakdown(player)
        total_vp = player.calc_victory_points()[1]
        return (
            f"{player.name} – {total_vp} VP\n\n"
            f"Cities: {breakdown['cities']} pts\n"
            f"Settlements: {breakdown['settlements']} pts\n"
            f"Longest Road: {breakdown['longest_road']} pts\n"
            f"Largest Army: {breakdown['largest_army']} pts\n"
            f"Victory Card Points: {breakdown['victory_cards']} pts"
        )

    @classmethod
    def _format_player_breakdown_html(cls, player: Player) -> str:
        breakdown = cls._get_player_victory_breakdown(player)
        return player_breakdown_html(player.name, breakdown)

    @classmethod
    def _format_player_ranking_summary(cls, player: Player) -> str:
        summary_parts: List[str] = []
        city_count = len(player.cities)
        if city_count:
            summary_parts.append(f"C:{city_count}")

        settlement_count = len(player.settlements)
        if settlement_count:
            summary_parts.append(f"S:{settlement_count}")

        if player.has_longest_road:
            summary_parts.append("LR✓")
        if player.has_largest_army:
            summary_parts.append("LA✓")

        vp_card_count = cls._get_player_victory_breakdown(player)["victory_cards"]
        if vp_card_count:
            summary_parts.append(f"VC:{vp_card_count}")

        return " ".join(summary_parts)

    @staticmethod
    def _endgame_rank_card_stylesheet(selected: bool) -> str:
        return endgame_rank_card_stylesheet(selected)

    def _set_endgame_winner_header(self, winner_name: str, winner_total_vp: int) -> None:
        trophy_pixmap = QPixmap(TROPHY_ICON_PATH)
        if trophy_pixmap.isNull():
            self.endgame_winner_trophy_label.hide()
        else:
            scaled_trophy = trophy_pixmap.scaled(
                self.endgame_winner_trophy_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.endgame_winner_trophy_label.setPixmap(scaled_trophy)
            self.endgame_winner_trophy_label.show()
        self.endgame_review_menu.titleWinnerLabel.setText(
            winner_title_html(winner_name, winner_total_vp)
        )

    def _select_endgame_rank_card(self, card_btn: QPushButton, player: Player):
        if self.selected_endgame_rank_card is not None:
            self.selected_endgame_rank_card.setStyleSheet(self._endgame_rank_card_stylesheet(False))

        self.selected_endgame_rank_card = card_btn
        card_btn.setStyleSheet(self._endgame_rank_card_stylesheet(True))
        self.endgame_review_menu.selectedBreakdownBox.setHtml(self._format_player_breakdown_html(player))

    def _configure_tutor_endgame_layout(self):
        self.endgame_review_menu.setMinimumSize(0, 0)
        self.endgame_review_menu.titleWinnerLabel.setMinimumWidth(0)
        self.endgame_review_menu.reviewTabs.setMinimumWidth(0)
        self.endgame_review_menu.selectedBreakdownBox.setMinimumSize(200, 0)
        self.endgame_review_menu.selectedBreakdownBox.setMinimumWidth(200)
        self.endgame_review_menu.selectedBreakdownBox.setMaximumWidth(200)
        self.endgame_review_menu.selectedBreakdownBox.setMinimumHeight(0)
        self.endgame_review_menu.selectedBreakdownBox.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored
        )
        self.endgame_review_menu.selectedBreakdownBox.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.endgame_review_menu.selectedBreakdownBox.setLineWrapMode(
            self.endgame_review_menu.selectedBreakdownBox.LineWrapMode.WidgetWidth
        )
        self.victory_points_plot.setMinimumSize(0, 0)
        self.endgame_replay_canvas.setMinimumSize(0, 0)
        self.endgame_replay_canvas.setMinimumWidth(280)
        self.endgame_review_menu.selectedMomentScrollArea.setMinimumSize(0, 0)
        self.endgame_review_menu.selectedMomentScrollArea.setMinimumWidth(280)
        self.endgame_review_menu.selectedBreakdownBox.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.endgame_review_menu.titleWinnerLabel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.endgame_review_menu.selectedBreakdownBox.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
        )
        self.endgame_review_menu.selectedMomentScrollArea.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.endgame_replay_splitter.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.endgame_review_menu.replayMainLayout.setStretch(0, 1)
        self.endgame_review_menu.main_menu_btn.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
        )
        self.endgame_review_menu.quit_btn.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
        )

    def _configure_endgame_feedback_filters(self) -> None:
        checkboxes = self.endgame_review_menu.feedbackTab.findChildren(QCheckBox)
        for checkbox in checkboxes:
            label = checkbox.text().strip().lower()
            self.endgame_feedback_filter_checkboxes[label] = checkbox
            checkbox.toggled.connect(self._refresh_endgame_feedback_list)

    @staticmethod
    def _strip_html(text: str) -> str:
        return strip_html_to_plain_text(text)

    @staticmethod
    def _compact_feedback_action(action_text: str) -> str:
        cleaned = " ".join((action_text or "").split()).strip()
        if not cleaned:
            return "Move"

        replacements = {
            "ending the turn": "End Turn",
            "building a road": "Built Road",
            "building a settlement": "Built Settlement",
            "upgrading to a city": "Built City",
            "buying a development card": "Bought Development Card",
            "playing a development card": "Played Development Card",
            "making a bank trade": "Bank Trade",
            "making a player trade": "Player Trade",
            "move the robber": "Robber Placement",
            "discard resources": "Discarded Resources",
        }
        lowered = cleaned.lower()
        if lowered in replacements:
            return replacements[lowered]
        return cleaned.title()

    @classmethod
    def _feedback_card_title(cls, feedback: TutorFeedbackExplanation) -> str:
        turn_num = getattr(feedback.board_snapshot.game_state, "round_num", 0)
        action_text = cls._compact_feedback_action(feedback.assessment.your_move or feedback.title)
        return f"Turn {turn_num} - {action_text}"

    def _endgame_feedback_filter_state(self) -> Dict[str, bool]:
        def is_checked(label: str) -> bool:
            checkbox = self.endgame_feedback_filter_checkboxes.get(label)
            return checkbox.isChecked() if checkbox is not None else False

        return {
            "poor": is_checked("biggest mistakes"),
            "okay": is_checked("okay moves"),
            "good": is_checked("good moves"),
            "excellent": is_checked("excellent moves"),
        }

    def _feedback_matches_filter(self, feedback: TutorFeedbackExplanation) -> bool:
        filter_state = self._endgame_feedback_filter_state()
        label = feedback.label.strip().lower()
        if label == "poor":
            return filter_state["poor"]
        if label == "okay":
            return filter_state["okay"]
        if label == "good":
            return filter_state["good"]
        if label == "excellent":
            return filter_state["excellent"]
        return True

    def _jump_to_endgame_feedback(self, index: int) -> None:
        self.endgame_review_menu.reviewTabs.setCurrentIndex(0)
        self._render_endgame_replay_feedback(index)

    def _build_endgame_feedback_card(self, feedback: TutorFeedbackExplanation, index: int) -> QPushButton:
        card_btn = QPushButton()
        card_btn.setObjectName("endgameFeedbackCard")
        card_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        card_btn.setStyleSheet(endgame_feedback_card_stylesheet())
        card_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(card_btn)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title_label = QLabel(self._feedback_card_title(feedback), card_btn)
        title_label.setStyleSheet(endgame_feedback_title_stylesheet())
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        score_label = QLabel(
            f"Score: {feedback.assessment.internal_score:.2f} . Gap: +{feedback.assessment.score_gap:.2f}",
            card_btn,
        )
        score_label.setStyleSheet(endgame_feedback_score_stylesheet())
        score_label.setWordWrap(True)
        layout.addWidget(score_label)

        body_label = QLabel(feedback.assessment.judgment_sentence.strip(), card_btn)
        body_label.setStyleSheet(endgame_feedback_body_stylesheet())
        body_label.setWordWrap(True)
        layout.addWidget(body_label)

        badge_label = QLabel(feedback.label, card_btn)
        badge_label.setStyleSheet(endgame_badge_stylesheet(feedback.label))
        badge_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(badge_label, alignment=Qt.AlignmentFlag.AlignLeft)

        card_btn.clicked.connect(
            lambda _checked=False, replay_index=index: self._jump_to_endgame_feedback(replay_index)
        )
        return card_btn

    def _refresh_endgame_feedback_list(self) -> None:
        layout = self.endgame_review_menu.feedbackListLayout
        self._clear_layout(layout)

        visible_feedback = [
            (index, feedback)
            for index, feedback in enumerate(self.endgame_replay_feedback)
            if self._feedback_matches_filter(feedback)
        ]

        if not visible_feedback:
            empty_label = QLabel("No feedback items match the selected filters.")
            empty_label.setStyleSheet(endgame_feedback_empty_stylesheet())
            empty_label.setWordWrap(True)
            layout.addWidget(empty_label)
        else:
            for index, feedback in visible_feedback:
                layout.addWidget(self._build_endgame_feedback_card(feedback, index))

        layout.addStretch(1)

    @classmethod
    def _replay_feedback_player_name(cls, feedback: TutorFeedbackExplanation) -> str:
        human_player = next((player for player in feedback.board_snapshot.get_all_players() if player.is_human), None)
        if human_player is not None:
            return human_player.name
        players = feedback.board_snapshot.get_all_players()
        return players[0].name if players else "Player"

    @classmethod
    def _format_replay_feedback_details(
            cls,
            feedback: TutorFeedbackExplanation,
            total_turns: int,
    ) -> Dict[str, str]:
        turn_num = getattr(feedback.board_snapshot.game_state, "round_num", 0)
        player_name = cls._replay_feedback_player_name(feedback)
        action_text = feedback.assessment.your_move or feedback.title
        move_context = getattr(feedback.assessment, "move_context", "")
        if move_context:
            action_text += f"\n{move_context}"
        score_text = (
            f"Score: {feedback.assessment.internal_score:.2f} · "
            f"Gap: +{feedback.assessment.score_gap:.2f}"
        )
        tutor_feedback = feedback.assessment.judgment_sentence.strip()

        if feedback.assessment.better_move and (
                feedback.assessment.better_move.strip().lower() != action_text.strip().lower()
        ):
            advice_text = f"Better move: {feedback.assessment.better_move}"
            better_move_context = getattr(feedback.assessment, "better_move_context", "")
            if better_move_context:
                advice_text += f"\n{better_move_context}"
            if feedback.assessment.tip:
                advice_text += f"\nTakeaway: {feedback.assessment.tip}"
        elif feedback.assessment.tip:
            advice_text = feedback.assessment.tip
        else:
            advice_text = cls._strip_html(feedback.history_summary)

        return {
            "turn_and_player": f"Turn {turn_num} - {player_name}",
            "action": f"Action: {action_text}",
            "badge": feedback.label,
            "score": score_text,
            "tutor_feedback": f"Tutor feedback: {tutor_feedback}",
            "advice": advice_text,
            "turn_label": f"Turn {turn_num} / {max(total_turns, turn_num)}",
        }

    @staticmethod
    def _overall_performance_summary(
            feedback_items: List[TutorFeedbackExplanation],
            final_snapshot: PlayerScoreSnapshot | None = None,
            leader_vp: int | None = None,
    ) -> Dict[str, str]:
        if not feedback_items:
            return {
                "turn_and_player": "",
                "action": "Your Performance",
                "badge": "N/A",
                "score": "Overall: N/A",
                "tutor_feedback": "Strengths:\n- No tutor feedback history was recorded.",
                "advice": "Weaknesses:\n- No tutor feedback history was recorded.",
                "turn_label": "Game Summary",
            }

        weighted_quality = sum(item.assessment.internal_score for item in feedback_items) / len(feedback_items)
        vp_score = None if final_snapshot is None else max(0.0, min(float(final_snapshot.total_vp) / 10.0, 1.0))
        win_bonus = None if final_snapshot is None else (1 if final_snapshot.total_vp >= 10 else 0.0)
        overall_score = weighted_quality
        if vp_score is not None and win_bonus is not None:
            overall_score = max(0.0, min(1.0, 0.3 * weighted_quality + 0.6 * vp_score + 0.1 * win_bonus))
        overall_label = move_quality_label(overall_score)
        category_scores: Dict[str, List[float]] = {}
        for feedback in feedback_items:
            category = MainWindow._performance_category(feedback)
            category_scores.setdefault(category, []).append(feedback.assessment.internal_score)

        ranked_categories = sorted(
            (
                (category, sum(scores) / len(scores), len(scores))
                for category, scores in category_scores.items()
            ),
            key=lambda item: (item[1], item[2]),
            reverse=True,
        )

        strengths = [
            MainWindow._performance_line(category, score, True)
            for category, score, _count in ranked_categories
            if score >= 0.6
        ][:2]
        weaknesses = [
            MainWindow._performance_line(category, score, False)
            for category, score, _count in sorted(ranked_categories, key=lambda item: (item[1], -item[2]))
            if score < 0.55
        ][:2]

        if not strengths:
            strengths = [
                MainWindow._performance_line(category, score, True)
                for category, score, _count in ranked_categories[:2]
            ]
        if not weaknesses:
            fallback = sorted(ranked_categories, key=lambda item: (item[1], -item[2]))
            weaknesses = [
                MainWindow._performance_line(category, score, False)
                for category, score, _count in fallback[:2]
            ]

        outcome_strength = MainWindow._outcome_strength_line(final_snapshot)
        if outcome_strength and outcome_strength not in strengths:
            strengths = [outcome_strength, *strengths][:2]

        outcome_weakness = MainWindow._outcome_weakness_line(final_snapshot, leader_vp)
        if outcome_weakness and outcome_weakness not in weaknesses:
            weaknesses = [outcome_weakness, *weaknesses][:2]

        score_text = f"Overall: {overall_label} ({overall_score:.2f})"
        if final_snapshot is not None:
            score_text = (
                f"Overall: {overall_label} ({overall_score:.2f})"
                f" | Moves {weighted_quality:.2f}"
                f" | VP {final_snapshot.total_vp}"
            )

        return {
            "turn_and_player": "",
            "action": "Your Performance",
            "badge": overall_label,
            "score": score_text,
            "tutor_feedback": "Strengths:\n" + "\n".join(f"- {line}" for line in strengths),
            "advice": "Weaknesses:\n" + "\n".join(f"- {line}" for line in weaknesses),
            "turn_label": "Game Summary",
        }

    @staticmethod
    def _outcome_performance_score(
            final_snapshot: PlayerScoreSnapshot | None
    ) -> float | None:
        if final_snapshot is None:
            return None

        final_vp = max(0, final_snapshot.total_vp)
        return max(0.0, min(float(final_vp) / 10.0, 1.0))

    @staticmethod
    def _outcome_strength_line(
            final_snapshot: PlayerScoreSnapshot | None
    ) -> str | None:
        outcome_score = MainWindow._outcome_performance_score(final_snapshot)
        if outcome_score is None or final_snapshot is None:
            return None
        if final_snapshot.total_vp >= 10:
            return f"Game result (converted decisions into {final_snapshot.total_vp} VP)"
        return None

    @staticmethod
    def _outcome_weakness_line(
            final_snapshot: PlayerScoreSnapshot | None,
            leader_vp: int | None,
    ) -> str | None:
        outcome_score = MainWindow._outcome_performance_score(final_snapshot)
        if outcome_score is None or final_snapshot is None:
            return None
        if final_snapshot.total_vp <= 4:
            return f"Game result (finished on only {final_snapshot.total_vp} VP)"
        if leader_vp is not None and final_snapshot.total_vp <= leader_vp - 3:
            return "Game result (fell too far behind the leader)"
        return None

    @staticmethod
    def _performance_category(feedback: TutorFeedbackExplanation) -> str:
        decision_type = feedback.assessment.decision_type
        move_text = (feedback.assessment.your_move or "").lower()
        if decision_type == TutorDecisionType.ROBBER:
            return "robber"
        if decision_type == TutorDecisionType.DISCARD:
            return "discard"
        if decision_type in {TutorDecisionType.TRADE_PARTNER, TutorDecisionType.TRADE_RESPONSE}:
            return "trade"
        if decision_type in {TutorDecisionType.YEAR_OF_PLENTY, TutorDecisionType.MONOPOLY}:
            return "dev_cards"
        if decision_type in {TutorDecisionType.OPENING_SETTLEMENT, TutorDecisionType.OPENING_ROAD}:
            return "opening"
        if "ending the turn" in move_text:
            return "turn_timing"
        if any(text in move_text for text in ("building a settlement", "building a road", "upgrading to a city")):
            return "builds"
        return "planning"

    @staticmethod
    def _performance_line(category: str, score: float, positive: bool) -> str:
        if positive:
            lines = {
                "robber": "Robber placement (consistent high-quality choices)",
                "discard": "Discard decisions (protected key resources well)",
                "trade": "Trade decisions (found efficient exchanges)",
                "dev_cards": "Development card usage (timed card value well)",
                "opening": "Opening placements (set up a stable start)",
                "turn_timing": "Turn timing (rarely wasted turns)",
                "builds": "Build choices (kept city and settlement timing on track)",
                "planning": "Main-turn planning (kept useful lines open)",
            }
            return lines.get(category, "General play (steady decisions)")

        lines = {
            "robber": "Robber placement (missed stronger blocks or steals)",
            "discard": "Discard decisions (lost key resources multiple times)",
            "trade": "Trade decisions (gave up too much value)",
            "dev_cards": "Development card usage (left card value on the table)",
            "opening": "Opening placements (gave up some early efficiency)",
            "turn_timing": "Turn timing (ended turns with stronger lines still available)",
            "builds": "Missed builds (delayed cities or settlements)",
            "planning": "Main-turn planning (stronger follow-up lines were available)",
        }
        default_line = "General play (several decisions could be tightened)"
        if score < 0.25 and category == "turn_timing":
            return "Turn timing (gave away full turns of tempo)"
        return lines.get(category, default_line)

    def _render_endgame_replay_feedback(self, index: int) -> None:
        if not self.endgame_replay_feedback and not hasattr(self, "endgame_final_board_source"):
            return

        max_index = len(self.endgame_replay_feedback)
        index = max(0, min(index, max_index))
        self.endgame_replay_index = index
        is_summary = index == len(self.endgame_replay_feedback)
        if index == len(self.endgame_replay_feedback):
            details = self._overall_performance_summary(
                self.endgame_replay_feedback,
                getattr(self, "endgame_human_final_snapshot", None),
                getattr(self, "endgame_final_leader_vp", None),
            )
            self.endgame_replay_canvas.display_board(self.endgame_final_board_source)
            self.endgame_replay_canvas.clear_planned_builds()
            self.endgame_replay_canvas.clear_feedback_builds()
        else:
            feedback = self.endgame_replay_feedback[index]
            details = self._format_replay_feedback_details(feedback, self.endgame_total_turns)

            self.endgame_replay_canvas.display_board(feedback.board_snapshot)
            self.endgame_replay_canvas.clear_planned_builds()
            self.endgame_replay_canvas.clear_feedback_builds()
            if feedback.recommended_visual_plan:
                self.endgame_replay_canvas.render_planned_builds(feedback.recommended_visual_plan)
            if feedback.visual_build_plan:
                self.endgame_replay_canvas.render_feedback_builds(feedback.visual_build_plan)

        self.endgame_review_menu.sectionTitle.setText("Game Summary" if is_summary else "Selected Moment")
        self.endgame_review_menu.turnAndPlayer.setText(details["turn_and_player"])
        self.endgame_review_menu.actionLabel.setText(details["action"])
        self.endgame_review_menu.selectedMomentBadge.setText(details["badge"])
        self.endgame_review_menu.selectedMomentBadge.setStyleSheet(endgame_badge_stylesheet(details["badge"]))
        self.endgame_review_menu.scoreLabel.setText(details["score"])
        self.endgame_review_menu.tutorFeedback.setText(details["tutor_feedback"])
        self.endgame_review_menu.adviceLabel.setText(details["advice"])
        self.endgame_review_menu.turnLabel.setText(details["turn_label"])

        slider = self.endgame_review_menu.timelineSlider
        was_blocked = slider.blockSignals(True)
        slider.setValue(index)
        slider.blockSignals(was_blocked)
        self.endgame_review_menu.prevTurn.setEnabled(index > 0)
        self.endgame_review_menu.nextTurn.setEnabled(index < len(self.endgame_replay_feedback))
        self._sync_endgame_replay_layout()

    def _show_previous_endgame_replay_feedback(self) -> None:
        if self.endgame_replay_index is None:
            return
        self._render_endgame_replay_feedback(self.endgame_replay_index - 1)

    def _show_next_endgame_replay_feedback(self) -> None:
        if self.endgame_replay_index is None:
            return
        self._render_endgame_replay_feedback(self.endgame_replay_index + 1)

    def _mark_endgame_replay_splitter_adjusted(self) -> None:
        if self.endgame_replay_splitter_initialised:
            self.endgame_replay_splitter_user_adjusted = True

    def _set_endgame_replay_splitter_sizes(self, prefer_equal: bool = False) -> None:
        splitter = self.endgame_replay_splitter
        if splitter is None:
            return

        total_width = max(0, splitter.width())
        if total_width <= 0:
            return

        if prefer_equal or not self.endgame_replay_splitter_user_adjusted:
            left_width = max(self.endgame_replay_canvas.minimumWidth(), total_width // 2)
            right_width = max(
                self.endgame_review_menu.selectedMomentScrollArea.minimumWidth(),
                total_width - left_width,
            )
            if left_width + right_width > total_width:
                left_width = max(self.endgame_replay_canvas.minimumWidth(), total_width - right_width)
            splitter.setSizes([left_width, right_width])
            self.endgame_replay_splitter_initialised = True

    def _sync_endgame_replay_layout(self) -> None:
        replay_tab = self.endgame_review_menu.replayTab
        if not replay_tab.isVisible():
            return

        self._set_endgame_replay_splitter_sizes(prefer_equal=not self.endgame_replay_splitter_initialised)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in {
            self.endgame_review_menu.replayTab,
            self.endgame_review_menu.selectedMomentScrollArea,
        } and event.type() in {QEvent.Type.Resize, QEvent.Type.Show}:
            QTimer.singleShot(0, self._sync_endgame_replay_layout)
        return super().eventFilter(watched, event)

    def _populate_tutor_endgame_performance(self, controller: GameController):
        plot_item = self.victory_points_plot.getPlotItem()
        plot_item.clear()
        self.endgame_plot_points = []
        self.endgame_plot_tooltips = {}
        if plot_item.legend is None:
            plot_item.addLegend(offset=(10, 10))
        else:
            plot_item.legend.clear()

        history = controller.get_victory_point_history()
        review_history = controller.get_endgame_review_history()
        if not history:
            return

        round_values = [round_num for round_num, _ in history]
        max_round = max(round_values)
        max_victory_points = 0

        plot_item.setTitle("Victory Points Over Time")
        plot_item.setLabel("bottom", "Round Number")
        plot_item.setLabel("left", "Victory Points")
        plot_item.showGrid(x=True, y=True, alpha=0.2)
        target_line = pg.InfiniteLine(
            pos=10,
            angle=0,
            pen=pg.mkPen(color=(156, 163, 175), width=2, style=Qt.PenStyle.DashLine),
        )
        target_line.setZValue(-10)
        plot_item.addItem(target_line)

        self.endgame_plot_tooltips = self._build_endgame_plot_tooltips(
            review_history,
            controller.get_all_players(),
        )

        for player in controller.get_all_players():
            player_rounds: List[int] = []
            player_points: List[int] = []
            for round_num, snapshot in history:
                player_rounds.append(round_num)
                y_value = snapshot.get(player.player_number, 0) + 0.075 - 0.05 * player.player_number.value
                player_points.append(y_value)
                self.endgame_plot_points.append((round_num, float(round_num), float(y_value)))

            max_victory_points = max(max_victory_points, max(player_points, default=0))
            colour = PLAYER_COLORS[player.player_number]
            pen = pg.mkPen((colour.red(), colour.green(), colour.blue()), width=3)
            curve = plot_item.plot(
                player_rounds,
                player_points,
                pen=pen,
                name=player.name,
                symbol="o",
                symbolSize=5,
                symbolBrush=(colour.red(), colour.green(), colour.blue()),
                symbolPen=pen,
            )
            curve.setZValue(100 - player.player_number.value)

        self.victory_points_plot.setXRange(1, max_round)
        self.victory_points_plot.setYRange(2, max(10, max_victory_points))

    @classmethod
    def _build_endgame_plot_tooltips(
            cls,
            history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
            players: List[Player],
    ) -> Dict[int, str]:
        player_names = {player.player_number: player.name for player in players}
        tooltips: Dict[int, str] = {}
        previous_snapshot: Dict[PlayerNumber, PlayerScoreSnapshot] | None = None

        for round_num, snapshot in history:
            ranked_players = sorted(snapshot.items(), key=lambda item: item[0].value)
            top_score = max(player_snapshot.total_vp for player_snapshot in snapshot.values())
            leaders = [
                player_names[player_number]
                for player_number, player_snapshot in ranked_players
                if player_snapshot.total_vp == top_score
            ]
            leader_text = cls._format_endgame_players(leaders)
            if len(leaders) > 1:
                leader_text += " (tied)"

            events = cls._describe_round_vp_events(previous_snapshot, snapshot, player_names)
            lines = [f"Turn {round_num}", ""]
            for player_number, player_snapshot in ranked_players:
                lines.append(f"{player_names[player_number]}: {player_snapshot.total_vp} VP")
            lines.extend(["", f"Leader: {leader_text}"])
            if events:
                lines.append("Event:")
                lines.extend(events)
            else:
                lines.append("Event: None")

            tooltips[round_num] = "\n".join(lines)
            previous_snapshot = snapshot

        return tooltips

    @classmethod
    def _describe_round_vp_events(
            cls,
            previous_snapshot: Dict[PlayerNumber, PlayerScoreSnapshot] | None,
            current_snapshot: Dict[PlayerNumber, PlayerScoreSnapshot],
            player_names: Dict[PlayerNumber, str],
    ) -> List[str]:
        if previous_snapshot is None:
            return []

        events: List[str] = []
        for player_number in sorted(current_snapshot.keys(), key=lambda number: number.value):
            previous = previous_snapshot[player_number]
            current = current_snapshot[player_number]
            player_name = player_names[player_number]

            city_gain = current.cities - previous.cities
            if city_gain > 0:
                if city_gain == 1:
                    events.append(f"- {player_name} built a city")
                else:
                    events.append(f"- {player_name} built {city_gain} cities")

            settlement_gain = current.settlements - previous.settlements
            if settlement_gain > 0:
                if settlement_gain == 1:
                    events.append(f"- {player_name} built a settlement")
                else:
                    events.append(f"- {player_name} built {settlement_gain} settlements")

            hidden_vp_gain = current.hidden_vp_cards - previous.hidden_vp_cards
            if hidden_vp_gain > 0:
                if hidden_vp_gain == 1:
                    events.append(f"- {player_name} bought a Victory Point card")
                else:
                    events.append(f"- {player_name} bought {hidden_vp_gain} Victory Point cards")

            if not previous.has_longest_road and current.has_longest_road:
                events.append(f"- {player_name} gained Longest Road")
            elif previous.has_longest_road and not current.has_longest_road:
                events.append(f"- {player_name} lost Longest Road")

            if not previous.has_largest_army and current.has_largest_army:
                events.append(f"- {player_name} gained Largest Army")
            elif previous.has_largest_army and not current.has_largest_army:
                events.append(f"- {player_name} lost Largest Army")

        return events

    @staticmethod
    def _format_endgame_players(names: List[str]) -> str:
        if not names:
            return "No one"
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} and {names[1]}"
        return f"{', '.join(names[:-1])}, and {names[-1]}"

    @classmethod
    def _summarise_endgame_review_labels(
            cls,
            history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
            players: List[Player],
    ) -> Tuple[str, str, str]:
        if not history:
            fallback = "No round history recorded."
            return fallback, fallback, fallback

        player_names = {player.player_number: player.name for player in players}
        lead_change_label = cls._build_lead_change_label(history, player_names)
        biggest_swing_label = cls._build_biggest_swing_label(history, player_names)
        closest_moment_label = cls._build_closest_moment_label(history, player_names)
        return lead_change_label, biggest_swing_label, closest_moment_label

    @classmethod
    def _build_lead_change_label(
            cls,
            history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
            player_names: Dict[PlayerNumber, str],
    ) -> str:
        leaders_by_round: List[Tuple[int, List[PlayerNumber], int]] = []
        for round_num, snapshot in history:
            top_score = max(player.total_vp for player in snapshot.values())
            leaders = sorted(
                [player_number for player_number, player in snapshot.items() if player.total_vp == top_score],
                key=lambda player_number: player_number.value,
            )
            leaders_by_round.append((round_num, leaders, top_score))

        final_round, final_leaders, _ = leaders_by_round[-1]
        first_round, first_leaders, _ = leaders_by_round[0]
        if len(final_leaders) == 1:
            final_leader = final_leaders[0]
            sole_lead_round = next(
                round_num
                for round_num, leaders, _ in reversed(leaders_by_round)
                if leaders != [final_leader]
            ) if any(leaders != [final_leader] for _, leaders, _ in leaders_by_round[:-1]) else None
            if sole_lead_round is None:
                return f"{player_names[final_leader]} led from Round {first_round} to the finish."

            held_from_round = sole_lead_round + 1
            return f"{player_names[final_leader]} took the lead in Round {held_from_round} and held it through Round {
                      final_round}."

        final_names = [player_names[player_number] for player_number in final_leaders]
        return f"The game finished level at the top in Round {final_round} with {cls._format_endgame_players(
            final_names)} sharing the lead."

    @classmethod
    def _build_biggest_swing_label(
            cls,
            history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
            player_names: Dict[PlayerNumber, str],
    ) -> str:
        best_round: int | None = None
        best_player: PlayerNumber | None = None
        best_delta = 0
        best_reasons: List[str] = []

        for index in range(1, len(history)):
            round_num, current_snapshot = history[index]
            _, previous_snapshot = history[index - 1]
            for player_number, current in current_snapshot.items():
                previous = previous_snapshot[player_number]
                delta = current.total_vp - previous.total_vp
                if delta <= 0:
                    continue
                reasons = cls._score_swing_reasons(previous, current)
                if delta > best_delta:
                    best_round = round_num
                    best_player = player_number
                    best_delta = delta
                    best_reasons = reasons

        if best_round is None or best_player is None:
            return "No player gained victory points between recorded rounds."

        if best_reasons:
            return (
                f"Round {best_round}: {player_names[best_player]} "
                f"{cls._join_reasons(best_reasons)} and jumped by {best_delta} VP."
            )
        return f"Round {best_round}: {player_names[best_player]} made the biggest move, gaining {best_delta} VP."

    @staticmethod
    def _join_reasons(reasons: List[str]) -> str:
        if len(reasons) == 1:
            return reasons[0]
        if len(reasons) == 2:
            return f"{reasons[0]} and {reasons[1]}"
        return f"{', '.join(reasons[:-1])}, and {reasons[-1]}"

    @staticmethod
    def _score_swing_reasons(previous: PlayerScoreSnapshot, current: PlayerScoreSnapshot) -> List[str]:
        reasons: List[str] = []
        if not previous.has_longest_road and current.has_longest_road:
            reasons.append("gained Longest Road")
        if not previous.has_largest_army and current.has_largest_army:
            reasons.append("gained Largest Army")
        if current.cities > previous.cities:
            reasons.append("upgraded to a city")
        elif current.settlements > previous.settlements:
            reasons.append("built a settlement")
        hidden_vp_delta = current.hidden_vp_cards - previous.hidden_vp_cards
        if hidden_vp_delta > 0:
            reasons.append(f"picked up {hidden_vp_delta} hidden VP")
        return reasons

    @classmethod
    def _build_closest_moment_label(
            cls,
            history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
            player_names: Dict[PlayerNumber, str],
    ) -> str:
        best_round = history[0][0]
        best_gap = math.inf
        best_top_score = -1
        best_leaders: List[PlayerNumber] = []
        best_runner_up: PlayerNumber | None = None
        best_runner_up_score = -1

        for round_num, snapshot in history:
            ranked = sorted(
                snapshot.items(),
                key=lambda item: (item[1].total_vp, -item[0].value),
                reverse=True,
            )
            top_score = ranked[0][1].total_vp
            leaders = [player_number for player_number, player in ranked if player.total_vp == top_score]
            if len(leaders) > 1:
                second_score = top_score
                gap = 0
            else:
                second_score = ranked[1][1].total_vp if len(ranked) > 1 else top_score
                gap = top_score - second_score
            runner_up = ranked[len(leaders)][0] if len(leaders) < len(ranked) else None
            if (
                    gap < best_gap
                    or (gap == best_gap and top_score > best_top_score)
                    or (gap == best_gap and top_score == best_top_score and round_num > best_round)
            ):
                best_round = round_num
                best_gap = gap
                best_top_score = top_score
                best_leaders = leaders
                best_runner_up = runner_up
                best_runner_up_score = second_score

        if best_gap == 0:
            leader_names = [player_names[player_number] for player_number in best_leaders]
            return (
                f"Round {best_round}: {cls._format_endgame_players(leader_names)} "
                f"were tied at {best_top_score} VP."
            )

        if best_runner_up is None:
            return f"Round {best_round}: {player_names[best_leaders[0]]} stood alone at {best_top_score} VP."

        return (
            f"Round {best_round}: {player_names[best_leaders[0]]} led "
            f"{player_names[best_runner_up]} {best_top_score}-{best_runner_up_score}."
        )

    def _populate_tutor_endgame_review(self, controller: GameController):
        self._configure_tutor_endgame_layout()
        sorted_players = sorted(controller.get_all_players(), key=lambda p: p.calc_victory_points()[1], reverse=True)
        winner = sorted_players[0]
        winner_total_vp = winner.calc_victory_points()[1]

        self._set_endgame_winner_header(winner.name, winner_total_vp)

        ranking_layout = self.endgame_review_menu.rankingCardsLayout
        self._clear_layout(ranking_layout)
        self.endgame_rank_cards = []
        self.selected_endgame_rank_card = None

        for rank, player in enumerate(sorted_players, start=1):
            total_vp = player.calc_victory_points()[1]
            ranking_summary = self._format_player_ranking_summary(player)
            card_text = f"{rank}. {player.name} – {total_vp} VP"
            if ranking_summary:
                card_text += f"\n{ranking_summary}"

            card_btn = QPushButton(card_text)
            card_btn.setObjectName("rankCard")
            card_btn.setCheckable(False)
            card_btn.setStyleSheet(self._endgame_rank_card_stylesheet(False))
            card_btn.setMinimumWidth(0)
            card_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            card_btn.clicked.connect(
                lambda _checked=False, selected_player=player, selected_btn=card_btn:
                self._select_endgame_rank_card(selected_btn, selected_player)
            )
            ranking_layout.addWidget(card_btn)
            self.endgame_rank_cards.append(card_btn)

        if self.endgame_rank_cards:
            self._select_endgame_rank_card(self.endgame_rank_cards[0], winner)
        self._populate_tutor_endgame_performance(controller)
        self.endgame_replay_feedback = list(controller.get_tutor_feedback_history())
        self._refresh_endgame_feedback_list()
        self.endgame_final_board_source = controller
        self.endgame_human_final_snapshot = None
        self.endgame_final_leader_vp = None
        self.endgame_replay_splitter_user_adjusted = False
        self.endgame_replay_splitter_initialised = False
        history = controller.get_victory_point_history()
        review_history = controller.get_endgame_review_history()
        if review_history:
            final_snapshot = review_history[-1][1]
            human_player = next((player for player in controller.get_all_players() if player.is_human), None)
            if human_player is not None:
                self.endgame_human_final_snapshot = final_snapshot.get(human_player.player_number)
            if final_snapshot:
                self.endgame_final_leader_vp = max(player.total_vp for player in final_snapshot.values())
        self.endgame_total_turns = max((round_num for round_num, _ in history), default=0)
        replay_slider = self.endgame_review_menu.timelineSlider
        replay_slider.setMinimum(0)
        replay_slider.setMaximum(max(0, len(self.endgame_replay_feedback)))
        replay_slider.setEnabled(bool(self.endgame_replay_feedback))
        self.safe_connect(self.endgame_review_menu.prevTurn, self._show_previous_endgame_replay_feedback)
        self.safe_connect(self.endgame_review_menu.nextTurn, self._show_next_endgame_replay_feedback)
        try:
            replay_slider.valueChanged.disconnect()
        except TypeError:
            pass
        replay_slider.valueChanged.connect(self._render_endgame_replay_feedback)
        if self.endgame_replay_feedback:
            self._render_endgame_replay_feedback(len(self.endgame_replay_feedback))
        else:
            self.endgame_replay_canvas.clear_shapes()
            self.endgame_review_menu.turnAndPlayer.setText("No replay moments recorded")
            self.endgame_review_menu.actionLabel.setText("Action: None")
            self.endgame_review_menu.selectedMomentBadge.setText("N/A")
            self.endgame_review_menu.selectedMomentBadge.setStyleSheet(endgame_badge_stylesheet(""))
            self.endgame_review_menu.scoreLabel.setText("Score: N/A")
            self.endgame_review_menu.tutorFeedback.setText("Tutor feedback: No tutor feedback history was recorded.")
            self.endgame_review_menu.adviceLabel.setText("No advice available.")
            self.endgame_review_menu.turnLabel.setText("Turn 0 / 0")
            self.endgame_review_menu.prevTurn.setEnabled(False)
            self.endgame_review_menu.nextTurn.setEnabled(False)
        lead_change_label, biggest_swing_label, closest_moment_label = self._summarise_endgame_review_labels(
            controller.get_endgame_review_history(),
            controller.get_all_players(),
        )
        self.endgame_review_menu.leadChangeLabel.setText(lead_change_label)
        self.endgame_review_menu.biggestSwingLabel.setText(biggest_swing_label)
        self.endgame_review_menu.closestMomentLabel.setText(closest_moment_label)

    def _display_tutor_endgame_review(self, controller: GameController):
        def return_to_main_menu():
            self._restore_splitter_layout()
            controller.start_game()

        self.open_tutor_menu(False)
        self._populate_tutor_endgame_review(controller)
        self.endgame_review_menu.reviewTabs.setCurrentIndex(0)
        self.safe_connect(self.endgame_review_menu.main_menu_btn, return_to_main_menu)
        self.safe_connect(self.endgame_review_menu.quit_btn, self.close)
        self._show_fullscreen_panel(self.endgame_review_menu)
        QTimer.singleShot(0, self._sync_endgame_replay_layout)

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
        self.history_mode_active = False
        self._hide_history_controls()
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
        self.safe_connect(self.main_menu.dev_btn, lambda: self.show_development_menu(
            controller, player, played_dev_card,
            lambda played: self.display_round_info(controller, player, dice_info, played)))
        self.safe_connect(self.main_menu.end_turn_btn, lambda: self.turnMade.emit(Action(ActionType.END_TURN)))
        self._set_restore_tutor_menu_callback(
            lambda: self.display_round_info(controller, player, dice_info, played_dev_card),
            controller.game_mode == GameMode.TUTOR and player.is_human,
        )
        self.set_restore_board_state_callback(None)

    def configure_tutor_panel(self, game_mode: GameMode):
        self.history_available_in_mode = game_mode == GameMode.TUTOR
        self._update_previous_feedback_button()
        self._hide_history_controls()

    def _stop_tutor_feedback_timers(self):
        if self.tutor_feedback_fade_timer is not None:
            self.tutor_feedback_fade_timer.stop()
            self.tutor_feedback_fade_timer.deleteLater()
            self.tutor_feedback_fade_timer = None
        if self.tutor_feedback_advance_timer is not None:
            self.tutor_feedback_advance_timer.stop()
            self.tutor_feedback_advance_timer.deleteLater()
            self.tutor_feedback_advance_timer = None

    def _reset_tutor_feedback_styles(self):
        self.tutor_menu.action_label.setStyleSheet(
            tutor_feedback_action_stylesheet("rgba(0, 0, 0, 255)")
        )
        self.tutor_menu.explanation_edit.setStyleSheet(
            tutor_feedback_explanation_stylesheet("rgba(0, 0, 0, 255)")
        )

    def _start_tutor_feedback_fade(self, duration_seconds: float):
        self._stop_tutor_feedback_timers()
        self._reset_tutor_feedback_styles()

        duration_ms = max(1, int(duration_seconds * 1000))
        interval_ms = max(1, duration_ms // TUTOR_FEEDBACK_FADE_STEPS)
        step_state = {"count": 0}

        fade_timer = QTimer(self)

        def update_fade():
            step_state["count"] += 1
            progress = step_state["count"] / TUTOR_FEEDBACK_FADE_STEPS
            remaining_ratio = max(0.0, 1.0 - math.pow(progress, 3))
            alpha = max(35, int(255 * remaining_ratio))
            faded_colour = f"rgba(0, 0, 0, {alpha})"
            self.tutor_menu.action_label.setStyleSheet(
                tutor_feedback_action_stylesheet(faded_colour)
            )
            self.tutor_menu.explanation_edit.setStyleSheet(
                tutor_feedback_explanation_stylesheet(faded_colour)
            )

            if step_state["count"] >= TUTOR_FEEDBACK_FADE_STEPS:
                fade_timer.stop()

        fade_timer.timeout.connect(update_fade)
        fade_timer.start(interval_ms)
        self.tutor_feedback_fade_timer = fade_timer

        advance_timer = QTimer(self)
        advance_timer.setSingleShot(True)
        advance_timer.timeout.connect(self._continue_after_tutor_feedback)
        advance_timer.start(duration_ms)
        self.tutor_feedback_advance_timer = advance_timer

    def _stop_auto_tutor_feedback(self):
        self._stop_tutor_feedback_timers()
        self._reset_tutor_feedback_styles()

    def _continue_after_tutor_feedback(self):
        self._stop_auto_tutor_feedback()
        self.canvas.clear_planned_builds()
        self.tutor_menu.action_label.setText("Wait For Your Turn")
        self.tutor_menu.explanation_edit.setText("Opponent is making move")
        self.tutor_menu.explain_btn.hide()
        self.tutor_menu.continue_btn.hide()
        self.turnMade.emit(True)

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

    @staticmethod
    def _move_quality_colour(label: str) -> str:
        return move_quality_colour(label)

    @staticmethod
    def _tutor_feedback_display_seconds(feedback: TutorFeedbackExplanation) -> float:
        gap = max(0.0, min(1.0, feedback.assessment.score_gap))
        return TUTOR_FEEDBACK_MIN_DISPLAY_SECONDS + (
                (TUTOR_FEEDBACK_MAX_DISPLAY_SECONDS - TUTOR_FEEDBACK_MIN_DISPLAY_SECONDS) * gap
        )

    def _concise_explanation_html(self, explanation: ActionExplanation) -> Tuple[str, str]:
        concise_title, concise_explanation = explanation.generate_text_concise()
        quality_label = explanation.tutor_move_quality_label
        move_quality_colour_value = self._move_quality_colour(quality_label)
        concise_html = concise_explanation_html(
            concise_explanation,
            quality_label,
            move_quality_colour_value,
        )
        return concise_title, concise_html

    def display_tutor_init(self, player: Player, stage: TutorStage, explanation: ActionExplanation):
        self.history_mode_active = False
        self._stop_tutor_feedback_timers()
        self._reset_tutor_feedback_styles()
        self._hide_history_controls()
        self.canvas.clear_feedback_builds()
        title, focus = TUTOR_STAGE_CONTENT[stage]["title"], TUTOR_STAGE_CONTENT[stage]["focus"]
        self.tutor_menu.action_label.setText(title)
        self.clear_trade_preview()
        visual_plan = explanation.get_visual_build_plan()

        default_text = tutor_focus_html(focus)

        concise_title, concise_explanation = self._concise_explanation_html(explanation)
        detailed_explanation = explanation.generate_text_detail()

        def show_default():
            self.canvas.clear_planned_builds()
            self.tutor_menu.action_label.setText(title)
            self.tutor_menu.explanation_edit.setHtml(default_text)
            self.tutor_menu.explain_btn.show()
            self.tutor_menu.explain_btn.setEnabled(True)
            self.tutor_menu.explain_btn.setText("Hint")
            self.tutor_menu.continue_btn.hide()
            self.safe_connect(self.tutor_menu.explain_btn, show_concise)
            self.safe_connect(self.tutor_menu.continue_btn, show_default)
            self._set_restore_tutor_menu_callback(show_default, player.is_human)
            self._set_dismiss_tutor_hint_callback(show_default)

        def show_concise():
            self.canvas.render_planned_builds(visual_plan)
            self.tutor_menu.action_label.setText(concise_title)
            self.tutor_menu.explanation_edit.setHtml(concise_explanation)
            self.tutor_menu.explain_btn.show()
            self.tutor_menu.explain_btn.setEnabled(True)
            self.tutor_menu.explain_btn.setText("Explain Further")
            self.tutor_menu.continue_btn.show()
            self.tutor_menu.continue_btn.setEnabled(True)
            self.tutor_menu.continue_btn.setText("Hide Hint")
            self.safe_connect(self.tutor_menu.explain_btn, show_detailed)
            self.safe_connect(self.tutor_menu.continue_btn, show_default)
            self._set_restore_tutor_menu_callback(show_concise, player.is_human)
            self._set_dismiss_tutor_hint_callback(show_default)

        def show_detailed():
            self.canvas.render_planned_builds(visual_plan)
            self.tutor_menu.action_label.setText(concise_title)
            self.tutor_menu.explanation_edit.setText(detailed_explanation)
            self.tutor_menu.explain_btn.hide()
            self.tutor_menu.continue_btn.show()
            self.tutor_menu.continue_btn.setEnabled(True)
            self.tutor_menu.continue_btn.setText("Hide Hint")
            self.safe_connect(self.tutor_menu.continue_btn, show_default)
            self._set_restore_tutor_menu_callback(show_detailed, player.is_human)
            self._set_dismiss_tutor_hint_callback(show_default)

        show_default()

    def display_explanation(self, player: Player, dice_info: Optional[Tuple[int, int, int]],
                            explanation: ActionExplanation):
        self.history_mode_active = False
        self._stop_tutor_feedback_timers()
        self._reset_tutor_feedback_styles()
        self._hide_history_controls()
        self.canvas.clear_feedback_builds()
        self._set_restore_tutor_menu_callback(None, False)
        self._set_dismiss_tutor_hint_callback(None)
        self.set_restore_board_state_callback(None)
        action, explanation_html = self._concise_explanation_html(explanation)
        turn_label_player = self._resolve_turn_label_player(player, explanation)
        self.display_round_info_ai_start(turn_label_player, dice_info, "")
        self.toggle_main_action_btns(False)

        self.tutor_menu.action_label.setText(action)
        self.tutor_menu.explanation_edit.setHtml(explanation_html)
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
                action_, explanation_html_ = self._concise_explanation_html(explanation)
                self.tutor_menu.action_label.setText(action_)
                self.tutor_menu.explanation_edit.setHtml(explanation_html_)
                self.tutor_menu.explain_btn.setText("Why this move?")
                showing_comparative = False
            else:
                self.tutor_menu.explanation_edit.setText(explanation.generate_text_detail())
                self.tutor_menu.explain_btn.setText("Show less")
                showing_comparative = True

        self.safe_connect(self.tutor_menu.explain_btn, toggle_explanation_detail)

        self.canvas.render_planned_builds(explanation.get_visual_build_plan())
        self.display_trade_preview(explanation)

    def display_tutor_action_feedback(self, feedback: TutorFeedbackExplanation) -> None:
        self.history_mode_active = False
        self.canvas.clear_planned_builds()
        self.canvas.clear_feedback_builds()
        self.clear_trade_preview()
        self.set_main_action_btns_enabled(False)
        self._hide_history_controls()
        self._set_restore_tutor_menu_callback(None, False)
        self._set_dismiss_tutor_hint_callback(None)
        self.set_restore_board_state_callback(None)
        self._append_tutor_feedback_history(feedback)
        self.tutor_menu.action_label.setText(feedback.title)
        self.tutor_menu.explanation_edit.setHtml(feedback.concise_html)
        self.tutor_menu.explain_btn.show()
        self.tutor_menu.explain_btn.setEnabled(True)
        self.tutor_menu.explain_btn.setText("Explain Further")
        self.tutor_menu.continue_btn.hide()
        self.tutor_menu.continue_btn.setEnabled(False)
        self.tutor_menu.continue_btn.setText("Continue")

        def switch_to_manual_continue():
            self._stop_auto_tutor_feedback()
            self.canvas.clear_planned_builds()
            if feedback.recommended_visual_plan:
                self.canvas.render_planned_builds(feedback.recommended_visual_plan)
            self.tutor_menu.explanation_edit.setHtml(feedback.detailed_html)
            self.tutor_menu.explain_btn.hide()
            self.tutor_menu.continue_btn.show()
            self.tutor_menu.continue_btn.setEnabled(True)
            self.safe_connect(self.tutor_menu.continue_btn, self._continue_after_tutor_feedback)

        self.safe_connect(self.tutor_menu.explain_btn, switch_to_manual_continue)
        display_seconds = self._tutor_feedback_display_seconds(feedback)
        self._start_tutor_feedback_fade(display_seconds)

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
        elif template == ExplanationTemplate.YEAR_OF_PLENTY_RESOURCES:
            self._display_year_of_plenty_preview(explanation)
        elif template == ExplanationTemplate.MONOPOLY_RESOURCE:
            self._display_monopoly_preview(explanation)

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

    def _display_year_of_plenty_preview(self, explanation: ActionExplanation):
        selected = explanation.chosen_candidate.metadata.get("selected_resources", {})
        self._display_resource_choice_preview(
            "Year Of Plenty",
            "Take the highlighted resources from the bank.",
            selected,
        )

    def _display_monopoly_preview(self, explanation: ActionExplanation):
        selected = explanation.chosen_candidate.metadata.get("selected_resources", {})
        self._display_resource_choice_preview(
            "Monopoly",
            "Choose the highlighted resource to claim from the other players.",
            selected,
        )

    def _display_resource_choice_preview(self, title: str, action_text: str, selected: ResourceCount):
        chooser = self.resource_selector_widget
        chooser.setParent(self.main_menu)
        self.minimise_spacer()
        self.main_menu.action_btn_layout.addWidget(chooser)
        self.active_trade_preview_widget = chooser

        self.main_menu.main_label.setText(title)
        self.main_menu.action_label.setText(action_text)

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
            self.set_debug_tutor_shortcut_finalizer(None)
            back_action()

        def trade_with_bank():
            self.restore_spacer()
            self.main_menu.action_btn_layout.removeWidget(trade_designer)
            trade_designer.setParent(None)
            self.main_menu.main_label.show()
            self.main_menu.action_label.show()
            self.set_debug_tutor_shortcut_finalizer(None)
            self.turnMade.emit(Action(ActionType.TRADE_WITH_BANK, (selling.copy(), buying.copy())))

        def trade_with_players():
            self.restore_spacer()
            self.main_menu.action_btn_layout.removeWidget(trade_designer)
            trade_designer.setParent(None)
            self.main_menu.main_label.show()
            self.main_menu.action_label.show()
            self.set_debug_tutor_shortcut_finalizer(None)
            self.turnMade.emit(Action(ActionType.TRADE_WITH_PLAYER, (selling.copy(), buying.copy())))

        def cleanup_trade_designer() -> None:
            self.restore_spacer()
            self.main_menu.action_btn_layout.removeWidget(trade_designer)
            trade_designer.setParent(None)
            self.main_menu.main_label.show()
            self.main_menu.action_label.show()
            self.set_debug_tutor_shortcut_finalizer(None)

        self.set_debug_tutor_shortcut_finalizer(cleanup_trade_designer)
        self.safe_connect(trade_designer.terminate_btn, terminate_trade)
        self.safe_connect(trade_designer.bank_trade_btn, trade_with_bank)
        self.safe_connect(trade_designer.player_trade_btn, trade_with_players)

    def select_player_to_trade(self, controller: GameController, player: Player, selling: ResourceCount,
                               buying: ResourceCount, willing_players: List[Tuple[Player, ResourceCount | None]]):
        self.display_resources(controller)
        self.clear_trade_preview()
        self.main_menu.action_label.show()

        # Case 1: no players are willing to trade
        if not willing_players:
            self.main_menu.action_label.setText("No players are willing to trade with you right now.")
            self.set_debug_tutor_shortcut_finalizer(None)
            QTimer.singleShot(0, lambda: self.tradeSelected.emit(None))
            return

        select_trade = self.select_trade_widget
        select_trade.setParent(self.main_menu)

        # Replace the normal turn actions with the trade selector.
        self.toggle_main_action_btns(False)
        self.minimise_spacer()
        self.main_menu.action_btn_layout.addWidget(select_trade)
        self.active_trade_preview_widget = select_trade
        select_trade.trade_list.clear()
        select_trade.trade_list.setEnabled(True)

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
            deal = trade.data(Qt.ItemDataRole.UserRole)
            if not deal:
                return

            self.clear_trade_preview()
            self.set_debug_tutor_shortcut_finalizer(None)
            self.tradeSelected.emit(deal)

        try:
            select_trade.trade_list.itemDoubleClicked.disconnect()
        except TypeError:
            pass
        select_trade.trade_list.itemDoubleClicked.connect(accept_trade)

        # Cancel and return to the previous action
        def cancel():
            self.clear_trade_preview()
            self.set_debug_tutor_shortcut_finalizer(None)
            self.tradeSelected.emit(None)

        def cleanup_select_trade() -> None:
            self.clear_trade_preview()
            self.set_debug_tutor_shortcut_finalizer(None)

        self.set_debug_tutor_shortcut_finalizer(cleanup_select_trade)
        self.safe_connect(select_trade.submit_btn, cancel)

    def display_round_info_ai_start(self, player: Player, dice_info: Optional[Tuple[int, int, int]], msg: str):
        self._clear_debug_tutor_shortcut_context()
        self.history_mode_active = False
        self._stop_tutor_feedback_timers()
        self._reset_tutor_feedback_styles()
        self._hide_history_controls()
        self.canvas.clear_feedback_builds()
        self._set_restore_tutor_menu_callback(None, False)
        self._set_dismiss_tutor_hint_callback(None)
        self.set_restore_board_state_callback(None)
        self.clear_trade_preview()
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

        self._set_turn_label(player)
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
            self.main_menu.action_btn_layout.removeWidget(selection_widget)
            selection_widget.setParent(None)
            self.set_debug_tutor_shortcut_finalizer(None)
            self.resourcesPicked.emit(chosen)

        def cleanup_selection_widget() -> None:
            self.main_menu.action_btn_layout.removeWidget(selection_widget)
            selection_widget.setParent(None)
            self.set_debug_tutor_shortcut_finalizer(None)

        self.set_debug_tutor_shortcut_finalizer(cleanup_selection_widget)
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
        self.active_trade_preview_widget = trade_manager
        self._set_turn_label(selling_player)
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
            self.clear_trade_preview()
            self.set_debug_tutor_shortcut_finalizer(None)
            self.tradeDecisionMade.emit((True, counter_offer if modified else None))

        def decline():
            self.clear_trade_preview()
            self.set_debug_tutor_shortcut_finalizer(None)
            self.tradeDecisionMade.emit((False, None))

        def cleanup_trade_manager() -> None:
            self.clear_trade_preview()
            self.set_debug_tutor_shortcut_finalizer(None)

        self.set_debug_tutor_shortcut_finalizer(cleanup_trade_manager)
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
        self._set_turn_label(player)

        def clean_up():
            self.main_menu.action_btn_layout.removeWidget(development_manager)
            development_manager.setParent(None)
            self.restore_spacer()
            self.main_menu.main_label.show()
            self.set_debug_tutor_shortcut_finalizer(None)

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
                self.turnMade.emit(Action(ActionType.PLAY_DEV_CARD, selected_card.card_type))
                clean_up()

        def buy_card():
            clean_up()
            self.turnMade.emit(Action(ActionType.BUY_DEV_CARD))

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

        self.set_debug_tutor_shortcut_finalizer(clean_up)
        self.safe_connect(development_manager.back_btn, back)
        development_manager.buy_btn.setEnabled(can_afford_card)
        self.safe_connect(development_manager.buy_btn, buy_card)

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
            self._display_tutor_endgame_review(controller)
            return

        self._restore_splitter_layout()

        # Close tutor menu
        self.open_tutor_menu(False)

        self.canvas.clear_planned_builds()
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
        self._stop_auto_tutor_feedback()
        self.history_enabled_on_turn = False
        self.tutor_feedback_history = []
        self.tutor_feedback_replay_history = []
        self._set_dismiss_tutor_hint_callback(None)
        self.open_tutor_menu(False)
        self.clear_trade_preview()
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
