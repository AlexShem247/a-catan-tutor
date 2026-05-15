import math
from typing import Callable, Optional, Tuple, TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QAbstractScrollArea, QHBoxLayout, QPushButton, QWidget

from ai.tutor.explanations import ActionExplanation
from ai.tutor.feedback import TutorFeedbackExplanation, move_quality_colour
from ai.tutor.tutor import TutorStage, TUTOR_STAGE_CONTENT
from config.view_constants import (
    TUTOR_FEEDBACK_FADE_STEPS,
    TUTOR_FEEDBACK_MAX_DISPLAY_SECONDS,
    TUTOR_FEEDBACK_HISTORY_LIMIT,
    TUTOR_FEEDBACK_MIN_DISPLAY_SECONDS,
    TUTOR_HISTORY_ACTION_HEIGHT_PX,
    TUTOR_HISTORY_NAV_BUTTON_SIZE_PX,
)
from view.View import GameMode
from view.canvas.display_utils import format_counter_offer
from view.rich_text import concise_explanation_html, tutor_focus_html
from view.styles import tutor_feedback_action_stylesheet, tutor_feedback_explanation_stylesheet

if TYPE_CHECKING:
    from view.MainWindow import MainWindow


# noinspection PyProtectedMember,PyUnresolvedReferences
class TutorPanel:
    def __init__(self, window: "MainWindow", widget: QWidget):
        self.window = window
        self.widget = widget
        self.widget.explanation_edit.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.widget.explanation_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.widget.explanation_edit.setLineWrapMode(self.widget.explanation_edit.LineWrapMode.WidgetWidth)

        self.history_nav_widget = QWidget(self.widget)
        self.history_nav_layout = QHBoxLayout(self.history_nav_widget)
        self.history_nav_layout.setContentsMargins(0, 0, 0, 0)
        self.history_prev_btn = QPushButton("<")
        self.history_detail_btn = QPushButton("Show Detailed")
        self.history_next_btn = QPushButton(">")
        self.history_prev_btn.setFixedSize(TUTOR_HISTORY_NAV_BUTTON_SIZE_PX, TUTOR_HISTORY_NAV_BUTTON_SIZE_PX)
        self.history_next_btn.setFixedSize(TUTOR_HISTORY_NAV_BUTTON_SIZE_PX, TUTOR_HISTORY_NAV_BUTTON_SIZE_PX)
        self.history_detail_btn.setFixedHeight(TUTOR_HISTORY_ACTION_HEIGHT_PX)
        self.history_nav_layout.addWidget(self.history_prev_btn)
        self.history_nav_layout.addWidget(self.history_detail_btn)
        self.history_nav_layout.addWidget(self.history_next_btn)
        self.history_exit_btn = QPushButton("Close History")
        self.history_exit_btn.setFixedHeight(TUTOR_HISTORY_ACTION_HEIGHT_PX)
        self.widget.verticalLayout_3.addWidget(self.history_nav_widget)
        self.widget.verticalLayout_3.addWidget(self.history_exit_btn)
        self.history_nav_widget.hide()
        self.history_exit_btn.hide()

        self.tutor_feedback_fade_timer: QTimer | None = None
        self.tutor_feedback_advance_timer: QTimer | None = None
        self.tutor_feedback_history: list[TutorFeedbackExplanation] = []
        self.tutor_feedback_replay_history: list[TutorFeedbackExplanation] = []
        self.history_feedback_index: int | None = None
        self.history_feedback_detailed = False
        self.history_enabled_on_turn = False
        self.history_available_in_mode = False
        self.history_mode_active = False
        self.restore_tutor_menu_callback: Optional[Callable[[], None]] = None
        self.dismiss_tutor_hint_callback: Optional[Callable[[], None]] = None

        self.window.safe_connect(self.widget.previous_feedback_btn, self.show_previous_feedback_history)

    @staticmethod
    def append_feedback_history_state(owner, feedback: TutorFeedbackExplanation) -> None:
        """Append tutor feedback to the shared history state."""
        owner.tutor_feedback_replay_history.append(feedback)
        owner.tutor_feedback_history.append(feedback)
        if len(owner.tutor_feedback_history) > TUTOR_FEEDBACK_HISTORY_LIMIT:
            owner.tutor_feedback_history = owner.tutor_feedback_history[-TUTOR_FEEDBACK_HISTORY_LIMIT:]
        owner._update_previous_feedback_button()

    def hide_history_controls(self) -> None:
        """Hide the tutor feedback history controls."""
        self.history_nav_widget.hide()
        self.history_exit_btn.hide()
        self.update_previous_feedback_button()

    def update_previous_feedback_button(self) -> None:
        """Update the visibility of the previous-feedback button."""
        visible = (
            self.history_available_in_mode
            and self.history_enabled_on_turn
            and bool(self.tutor_feedback_history)
            and not self.history_mode_active
        )
        self.widget.previous_feedback_btn.setVisible(visible)
        self.widget.previous_feedback_btn.setEnabled(visible)

    def set_history_enabled(self, enabled: bool) -> None:
        """Enable or disable tutor feedback history for the turn."""
        self.history_enabled_on_turn = enabled
        self.update_previous_feedback_button()

    def set_restore_tutor_menu_callback(
        self, callback: Optional[Callable[[], None]], allow_history: bool
    ) -> None:
        """Store the callback used to restore the tutor menu."""
        self.restore_tutor_menu_callback = callback
        self.set_history_enabled(allow_history)

    def set_dismiss_tutor_hint_callback(self, callback: Optional[Callable[[], None]]) -> None:
        """Store the callback used to dismiss the active tutor hint."""
        self.dismiss_tutor_hint_callback = callback

    def append_tutor_feedback_history(self, feedback: TutorFeedbackExplanation) -> None:
        """Append a tutor feedback item to the history."""
        self.tutor_feedback_replay_history.append(feedback)
        self.tutor_feedback_history.append(feedback)
        if len(self.tutor_feedback_history) > TUTOR_FEEDBACK_HISTORY_LIMIT:
            self.tutor_feedback_history = self.tutor_feedback_history[-TUTOR_FEEDBACK_HISTORY_LIMIT:]
        self.update_previous_feedback_button()

    def render_feedback_history_item(self) -> None:
        """Render the currently selected tutor feedback history item."""
        if self.history_feedback_index is None:
            return

        feedback = self.tutor_feedback_history[self.history_feedback_index]
        self.window.canvas.display_board(feedback.board_snapshot)
        self.window.canvas.clear_planned_builds()
        if feedback.recommended_visual_plan:
            self.window.canvas.render_planned_builds(feedback.recommended_visual_plan)
        self.window.canvas.render_feedback_builds(feedback.visual_build_plan)
        self.window.display_resources(feedback.board_snapshot)
        item_num = self.history_feedback_index + 1
        total = len(self.tutor_feedback_history)
        self.widget.action_label.setText(f"{feedback.title} ({item_num}/{total})")
        self.widget.explanation_edit.setHtml(feedback.render_html(self.history_feedback_detailed))
        self.history_prev_btn.setEnabled(self.history_feedback_index > 0)
        self.history_next_btn.setEnabled(self.history_feedback_index < total - 1)
        self.history_detail_btn.setText("Show Concise" if self.history_feedback_detailed else "Show Detailed")

    def show_previous_feedback_history(self) -> None:
        """Open the tutor feedback history viewer."""
        if not self.history_enabled_on_turn or not self.tutor_feedback_history:
            return

        self.stop_auto_feedback()
        if self.dismiss_tutor_hint_callback is not None:
            self.dismiss_tutor_hint_callback()
        self.window.main_action_btn_enabled_states = self.window._capture_main_action_btn_enabled_states()
        self.window.set_main_action_btns_enabled(False)
        self.history_mode_active = True
        self.update_previous_feedback_button()
        self.history_feedback_index = len(self.tutor_feedback_history) - 1
        self.history_feedback_detailed = False
        self.widget.explain_btn.hide()
        self.widget.continue_btn.hide()
        self.history_nav_widget.show()
        self.history_exit_btn.show()

        self.window.safe_connect(self.history_prev_btn, self.show_older_feedback)
        self.window.safe_connect(self.history_next_btn, self.show_newer_feedback)
        self.window.safe_connect(self.history_detail_btn, self.toggle_feedback_detail)
        self.window.safe_connect(self.history_exit_btn, self.exit_feedback_history)
        self.render_feedback_history_item()

    def show_older_feedback(self) -> None:
        """Move to the previous tutor feedback history item."""
        if self.history_feedback_index is None or self.history_feedback_index <= 0:
            return
        self.history_feedback_index -= 1
        self.render_feedback_history_item()

    def show_newer_feedback(self) -> None:
        """Move to the next tutor feedback history item."""
        if self.history_feedback_index is None or self.history_feedback_index >= len(self.tutor_feedback_history) - 1:
            return
        self.history_feedback_index += 1
        self.render_feedback_history_item()

    def toggle_feedback_detail(self) -> None:
        """Toggle between concise and detailed feedback history views."""
        self.history_feedback_detailed = not self.history_feedback_detailed
        self.render_feedback_history_item()

    def exit_feedback_history(self) -> None:
        """Exit the tutor feedback history viewer."""
        self.history_mode_active = False
        self.hide_history_controls()
        self.window.canvas.clear_feedback_builds()
        if self.window.restore_board_state_callback is not None:
            self.window.restore_board_state_callback()
        if self.restore_tutor_menu_callback is not None:
            self.restore_tutor_menu_callback()
        elif self.window.live_board_source is not None:
            self.window.canvas.display_board(self.window.live_board_source)
            self.window.display_resources(self.window.live_board_source)
        self.window._restore_main_action_btn_enabled_states()
        self.history_feedback_index = None
        self.history_feedback_detailed = False

    def configure_for_game_mode(self, game_mode: GameMode) -> None:
        """Configure tutor history availability for the game mode."""
        self.history_available_in_mode = game_mode == GameMode.TUTOR
        self.update_previous_feedback_button()
        self.hide_history_controls()

    def stop_feedback_timers(self) -> None:
        """Stop and clear the tutor feedback timers."""
        if self.tutor_feedback_fade_timer is not None:
            self.tutor_feedback_fade_timer.stop()
            self.tutor_feedback_fade_timer.deleteLater()
            self.tutor_feedback_fade_timer = None
        if self.tutor_feedback_advance_timer is not None:
            self.tutor_feedback_advance_timer.stop()
            self.tutor_feedback_advance_timer.deleteLater()
            self.tutor_feedback_advance_timer = None

    def reset_feedback_styles(self) -> None:
        """Reset the tutor feedback text styling."""
        self.widget.action_label.setStyleSheet(tutor_feedback_action_stylesheet("rgba(0, 0, 0, 255)"))
        self.widget.explanation_edit.setStyleSheet(tutor_feedback_explanation_stylesheet("rgba(0, 0, 0, 255)"))

    def start_feedback_fade(self, duration_seconds: float) -> None:
        """Start fading tutor feedback over the given duration."""
        self.stop_feedback_timers()
        self.reset_feedback_styles()

        duration_ms = max(1, int(duration_seconds * 1000))
        interval_ms = max(1, duration_ms // TUTOR_FEEDBACK_FADE_STEPS)
        step_state = {"count": 0}
        fade_timer = QTimer(self.window)

        def update_fade() -> None:
            step_state["count"] += 1
            progress = step_state["count"] / TUTOR_FEEDBACK_FADE_STEPS
            remaining_ratio = max(0.0, 1.0 - math.pow(progress, 3))
            alpha = max(35, int(255 * remaining_ratio))
            faded_colour = f"rgba(0, 0, 0, {alpha})"
            self.widget.action_label.setStyleSheet(tutor_feedback_action_stylesheet(faded_colour))
            self.widget.explanation_edit.setStyleSheet(tutor_feedback_explanation_stylesheet(faded_colour))
            if step_state["count"] >= TUTOR_FEEDBACK_FADE_STEPS:
                fade_timer.stop()

        fade_timer.timeout.connect(update_fade)
        fade_timer.start(interval_ms)
        self.tutor_feedback_fade_timer = fade_timer

        advance_timer = QTimer(self.window)
        advance_timer.setSingleShot(True)
        advance_timer.timeout.connect(self.continue_after_tutor_feedback)
        advance_timer.start(duration_ms)
        self.tutor_feedback_advance_timer = advance_timer

    def stop_auto_feedback(self) -> None:
        """Stop tutor feedback timers and reset their styling."""
        self.stop_feedback_timers()
        self.reset_feedback_styles()

    def continue_after_tutor_feedback(self) -> None:
        """Continue the turn flow after tutor feedback finishes."""
        self.stop_auto_feedback()
        self.window.canvas.clear_planned_builds()
        self.widget.action_label.setText("Wait For Your Turn")
        self.widget.explanation_edit.setText("Opponent is making move")
        self.widget.explain_btn.hide()
        self.widget.continue_btn.hide()
        self.window.turnMade.emit(True)

    @staticmethod
    def move_quality_colour_value(label: str) -> str:
        """Return the colour for a move-quality label."""
        return move_quality_colour(label)

    @staticmethod
    def tutor_feedback_display_seconds(feedback: TutorFeedbackExplanation) -> float:
        """Return how long tutor feedback should stay visible."""
        gap = max(0.0, min(1.0, feedback.assessment.score_gap))
        return TUTOR_FEEDBACK_MIN_DISPLAY_SECONDS + (
            (TUTOR_FEEDBACK_MAX_DISPLAY_SECONDS - TUTOR_FEEDBACK_MIN_DISPLAY_SECONDS) * gap
        )

    def concise_explanation_html(self, explanation: ActionExplanation) -> Tuple[str, str]:
        """Build the concise tutor explanation HTML."""
        concise_title, concise_explanation = explanation.generate_text_concise()
        quality_label = explanation.tutor_move_quality_label
        concise_html = concise_explanation_html(
            concise_explanation,
            quality_label,
            self.move_quality_colour_value(quality_label),
        )
        return concise_title, concise_html

    def reset_for_turn(self) -> None:
        """Reset tutor panel state for a new turn."""
        self.history_mode_active = False
        self.stop_feedback_timers()
        self.reset_feedback_styles()
        self.hide_history_controls()
        self.window.canvas.clear_feedback_builds()

    def display_tutor_init(self, player, stage: TutorStage, explanation: ActionExplanation) -> None:
        """Display the tutor introduction for the current stage."""
        self.reset_for_turn()
        title, focus = TUTOR_STAGE_CONTENT[stage]["title"], TUTOR_STAGE_CONTENT[stage]["focus"]
        self.widget.action_label.setText(title)
        self.window.trade_panel.clear_trade_preview()
        visual_plan = explanation.get_visual_build_plan()
        default_text = tutor_focus_html(focus)
        concise_title, concise_explanation = self.concise_explanation_html(explanation)
        detailed_explanation = explanation.generate_text_detail()

        def show_default() -> None:
            self.window.canvas.clear_planned_builds()
            self.widget.action_label.setText(title)
            self.widget.explanation_edit.setHtml(default_text)
            self.widget.explain_btn.show()
            self.widget.explain_btn.setEnabled(True)
            self.widget.explain_btn.setText("Hint")
            self.widget.continue_btn.hide()
            self.window.safe_connect(self.widget.explain_btn, show_concise)
            self.window.safe_connect(self.widget.continue_btn, show_default)
            self.set_restore_tutor_menu_callback(show_default, player.is_human)
            self.set_dismiss_tutor_hint_callback(show_default)

        def show_concise() -> None:
            self.window.canvas.render_planned_builds(visual_plan)
            self.widget.action_label.setText(concise_title)
            self.widget.explanation_edit.setHtml(concise_explanation)
            self.widget.explain_btn.show()
            self.widget.explain_btn.setEnabled(True)
            self.widget.explain_btn.setText("Explain Further")
            self.widget.continue_btn.show()
            self.widget.continue_btn.setEnabled(True)
            self.widget.continue_btn.setText("Hide Hint")
            self.window.safe_connect(self.widget.explain_btn, show_detailed)
            self.window.safe_connect(self.widget.continue_btn, show_default)
            self.set_restore_tutor_menu_callback(show_concise, player.is_human)
            self.set_dismiss_tutor_hint_callback(show_default)

        def show_detailed() -> None:
            self.window.canvas.render_planned_builds(visual_plan)
            self.widget.action_label.setText(concise_title)
            self.widget.explanation_edit.setText(detailed_explanation)
            self.widget.explain_btn.hide()
            self.widget.continue_btn.show()
            self.widget.continue_btn.setEnabled(True)
            self.widget.continue_btn.setText("Hide Hint")
            self.window.safe_connect(self.widget.continue_btn, show_default)
            self.set_restore_tutor_menu_callback(show_detailed, player.is_human)
            self.set_dismiss_tutor_hint_callback(show_default)

        show_default()

    def display_explanation(self, player, dice_info, explanation: ActionExplanation) -> None:
        """Display the tutor explanation for the current move."""
        self.reset_for_turn()
        self.set_restore_tutor_menu_callback(None, False)
        self.set_dismiss_tutor_hint_callback(None)
        self.window.set_restore_board_state_callback(None)
        action, explanation_html = self.concise_explanation_html(explanation)
        turn_label_player = self.window._resolve_turn_label_player(player, explanation)
        self.window.display_round_info_ai_start(turn_label_player, dice_info, "")
        self.window.toggle_main_action_btns(False)

        self.widget.action_label.setText(action)
        self.widget.explanation_edit.setHtml(explanation_html)
        self.window.main_menu.action_label.setText(f"{player} is thinking")

        self.widget.continue_btn.setEnabled(True)
        self.widget.continue_btn.setText("Continue")
        self.window.safe_connect(self.widget.continue_btn, lambda: self.window.turnMade.emit(True))

        self.widget.explain_btn.setEnabled(True)
        self.widget.explain_btn.setText("Why this move?")
        showing_comparative = False

        def toggle_explanation_detail() -> None:
            nonlocal showing_comparative
            if showing_comparative:
                action_, explanation_html_ = self.concise_explanation_html(explanation)
                self.widget.action_label.setText(action_)
                self.widget.explanation_edit.setHtml(explanation_html_)
                self.widget.explain_btn.setText("Why this move?")
                showing_comparative = False
            else:
                self.widget.explanation_edit.setText(explanation.generate_text_detail())
                self.widget.explain_btn.setText("Show less")
                showing_comparative = True

        self.window.safe_connect(self.widget.explain_btn, toggle_explanation_detail)
        self.window.canvas.render_planned_builds(explanation.get_visual_build_plan())
        self.window.trade_panel.display_trade_preview(explanation)

    def display_tutor_action_feedback(self, feedback: TutorFeedbackExplanation) -> None:
        """Display tutor feedback for the player action."""
        self.history_mode_active = False
        self.window.canvas.clear_planned_builds()
        self.window.canvas.clear_feedback_builds()
        self.window.trade_panel.clear_trade_preview()
        self.window.set_main_action_btns_enabled(False)
        self.hide_history_controls()
        self.set_restore_tutor_menu_callback(None, False)
        self.set_dismiss_tutor_hint_callback(None)
        self.window.set_restore_board_state_callback(None)
        self.append_tutor_feedback_history(feedback)
        self.widget.action_label.setText(feedback.title)
        self.widget.explanation_edit.setHtml(feedback.concise_html)
        self.widget.explain_btn.show()
        self.widget.explain_btn.setEnabled(True)
        self.widget.explain_btn.setText("Explain Further")
        self.widget.continue_btn.hide()
        self.widget.continue_btn.setEnabled(False)
        self.widget.continue_btn.setText("Continue")

        def switch_to_manual_continue() -> None:
            self.stop_auto_feedback()
            self.window.canvas.clear_planned_builds()
            if feedback.recommended_visual_plan:
                self.window.canvas.render_planned_builds(feedback.recommended_visual_plan)
            self.widget.explanation_edit.setHtml(feedback.detailed_html)
            self.widget.explain_btn.hide()
            self.widget.continue_btn.show()
            self.widget.continue_btn.setEnabled(True)
            self.window.safe_connect(self.widget.continue_btn, self.continue_after_tutor_feedback)

        self.window.safe_connect(self.widget.explain_btn, switch_to_manual_continue)
        self.start_feedback_fade(self.tutor_feedback_display_seconds(feedback))

    def prepare_ai_wait_state(self) -> None:
        """Prepare the tutor panel for an AI wait state."""
        self.history_mode_active = False
        self.stop_feedback_timers()
        self.reset_feedback_styles()
        self.hide_history_controls()
        self.window.canvas.clear_feedback_builds()
        self.set_restore_tutor_menu_callback(None, False)
        self.set_dismiss_tutor_hint_callback(None)

    def reset_for_start_screen(self) -> None:
        """Reset tutor panel state for the start screen."""
        self.stop_auto_feedback()
        self.history_enabled_on_turn = False
        self.tutor_feedback_history = []
        self.tutor_feedback_replay_history = []
        self.history_feedback_index = None
        self.history_feedback_detailed = False
        self.history_mode_active = False
        self.set_dismiss_tutor_hint_callback(None)
        self.set_restore_tutor_menu_callback(None, False)
        self.hide_history_controls()
