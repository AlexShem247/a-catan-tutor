from typing import TYPE_CHECKING, Dict, List, Tuple

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QAbstractScrollArea, QCheckBox, QLabel, QPushButton, QSizePolicy, QSplitter, QVBoxLayout,
                             QWidget)

from ai.tutor.feedback import TutorFeedbackExplanation
from config.view_constants import (ENDGAME_FEEDBACK_CARD_LAYOUT_SPACING_PX, ENDGAME_REPLAY_MIN_PANEL_WIDTH,
                                   ENDGAME_REPLAY_SPLITTER_HANDLE_WIDTH_PX, ENDGAME_REVIEW_BREAKDOWN_PANEL_WIDTH,
                                   ENDGAME_REVIEW_TROPHY_SIZE, TROPHY_ICON)
from controllers.GameController import GameController, PlayerScoreSnapshot
from game.Player import Player, PlayerNumber
from game.PlayerAssets import DevelopmentCardType
from view.canvas.SquareCanvas import SquareCanvas
from view.panels.endgame_plot import (HoverTooltip, build_endgame_plot_tooltips, create_victory_points_plot,
                                      handle_plot_hover, populate_tutor_endgame_performance, reset_hover_state)
from view.panels.endgame_summary import (
    build_biggest_swing_label, build_closest_moment_label, build_lead_change_label, compact_feedback_action,
    describe_round_vp_events, endgame_feedback_filter_state_from_owner, feedback_card_title, format_endgame_players,
    format_player_breakdown_html, format_player_breakdown_text, format_player_ranking_summary,
    format_replay_feedback_details, get_player_victory_breakdown, join_reasons, outcome_performance_score,
    outcome_strength_line, outcome_weakness_line, overall_performance_summary, performance_category, performance_line,
    replay_feedback_player_name, score_swing_reasons, strip_html, summarise_endgame_review_labels)
from view.rich_text import winner_title_html
from view.styles import (endgame_badge_stylesheet, endgame_feedback_body_stylesheet, endgame_feedback_card_stylesheet,
                         endgame_feedback_empty_stylesheet, endgame_feedback_score_stylesheet,
                         endgame_feedback_title_stylesheet, endgame_rank_card_stylesheet)

if TYPE_CHECKING:
    from view.MainWindow import MainWindow


# noinspection PyProtectedMember,PyUnresolvedReferences
class EndgameReviewPanel:

    def __init__(self, window: "MainWindow", results_menu: QWidget, widget: QWidget):
        self.window = window
        self.results_menu = results_menu
        self.widget = widget

        self.winner_trophy_label = QLabel(self.widget)
        self.winner_trophy_label.setObjectName("winnerTrophyLabel")
        self.winner_trophy_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.winner_trophy_label.setFixedSize(ENDGAME_REVIEW_TROPHY_SIZE)
        self.winner_trophy_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.widget.globalHeaderLayout.insertWidget(0, self.winner_trophy_label)

        self.replay_canvas = SquareCanvas()
        self.replay_canvas.setMinimumSize(0, 0)
        self.replay_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.replay_canvas.disable_interactivity = True
        self.widget.replayMainLayout.removeWidget(self.widget.selectedMomentScrollArea)
        self.replay_splitter = QSplitter(Qt.Orientation.Horizontal, self.widget.replayTab)
        self.replay_splitter.setChildrenCollapsible(False)
        self.replay_splitter.setHandleWidth(ENDGAME_REPLAY_SPLITTER_HANDLE_WIDTH_PX)
        self.replay_splitter.addWidget(self.replay_canvas)
        self.replay_splitter.addWidget(self.widget.selectedMomentScrollArea)
        self.replay_splitter.setStretchFactor(0, 1)
        self.replay_splitter.setStretchFactor(1, 1)
        self.replay_splitter.splitterMoved.connect(self.mark_replay_splitter_adjusted)
        self.widget.replayMainLayout.replaceWidget(self.widget.boardPlaceholder, self.replay_splitter)
        self.widget.boardPlaceholder.setParent(None)
        self.widget.boardPlaceholder.deleteLater()
        self.widget.replayTab.installEventFilter(self.window)
        self.widget.selectedMomentScrollArea.installEventFilter(self.window)

        self.victory_points_plot = create_victory_points_plot()
        self.victory_points_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.widget.performanceLayout.replaceWidget(self.widget.graphPlaceholder, self.victory_points_plot)
        self.widget.graphPlaceholder.setParent(None)
        self.widget.graphPlaceholder.deleteLater()

        self.plot_points: List[Tuple[int, float, float]] = []
        self.plot_tooltips: Dict[int, str] = {}
        self.active_tooltip_round: int | None = None
        self.last_tooltip_text: str | None = None
        self.hover_tooltip = HoverTooltip(self.window)
        self.replay_feedback: List[TutorFeedbackExplanation] = []
        self.replay_index: int | None = None
        self.total_turns = 0
        self.replay_splitter_user_adjusted = False
        self.replay_splitter_initialised = False
        self.feedback_filter_checkboxes: Dict[str, QCheckBox] = {}
        self.rank_cards: List[QPushButton] = []
        self.selected_rank_card: QPushButton | None = None
        self.final_board_source = None
        self.human_final_snapshot: PlayerScoreSnapshot | None = None
        self.final_leader_vp: int | None = None

        scene = self.victory_points_plot.scene()
        if scene is not None and hasattr(scene, "sigMouseMoved"):
            scene.sigMouseMoved.connect(self.handle_plot_hover)

        self.configure_endgame_feedback_filters()

    def reset_hover(self) -> None:
        """Reset the active endgame plot hover state."""
        reset_hover_state(self)

    def handle_plot_hover(self, scene_pos) -> None:
        """Handle hover updates for the endgame plot."""
        handle_plot_hover(self, scene_pos)

    @staticmethod
    def get_player_victory_breakdown(player: Player) -> Dict[str, int]:
        """Return the player victory-point breakdown."""
        return get_player_victory_breakdown(player)

    @classmethod
    def format_player_breakdown_text(cls, player: Player) -> str:
        """Format a player breakdown as plain text."""
        return format_player_breakdown_text(player)

    @classmethod
    def format_player_breakdown_html(cls, player: Player) -> str:
        """Format a player breakdown as HTML."""
        return format_player_breakdown_html(player)

    @classmethod
    def format_player_ranking_summary(cls, player: Player) -> str:
        """Format the summary text for a ranked player."""
        return format_player_ranking_summary(player)

    @staticmethod
    def endgame_rank_card_stylesheet(selected: bool) -> str:
        """Return the stylesheet for an endgame ranking card."""
        return endgame_rank_card_stylesheet(selected)

    def set_endgame_winner_header(self, winner_name: str, winner_total_vp: int) -> None:
        """Populate the endgame winner header."""
        trophy_pixmap = QPixmap(TROPHY_ICON)
        if trophy_pixmap.isNull():
            self.winner_trophy_label.hide()
        else:
            scaled_trophy = trophy_pixmap.scaled(
                self.winner_trophy_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.winner_trophy_label.setPixmap(scaled_trophy)
            self.winner_trophy_label.show()
        self.widget.titleWinnerLabel.setText(winner_title_html(winner_name, winner_total_vp))

    def select_endgame_rank_card(self, card_btn: QPushButton, player: Player) -> None:
        """Select an endgame ranking card and show its breakdown."""
        if self.selected_rank_card is not None:
            self.selected_rank_card.setStyleSheet(self.endgame_rank_card_stylesheet(False))
        self.selected_rank_card = card_btn
        card_btn.setStyleSheet(self.endgame_rank_card_stylesheet(True))
        self.widget.selectedBreakdownBox.setHtml(self.format_player_breakdown_html(player))

    def configure_tutor_endgame_layout(self) -> None:
        """Configure the tutor endgame review layout."""
        self.widget.setMinimumSize(0, 0)
        self.widget.titleWinnerLabel.setMinimumWidth(0)
        self.widget.reviewTabs.setMinimumWidth(0)
        self.widget.selectedBreakdownBox.setMinimumSize(ENDGAME_REVIEW_BREAKDOWN_PANEL_WIDTH, 0)
        self.widget.selectedBreakdownBox.setMinimumWidth(ENDGAME_REVIEW_BREAKDOWN_PANEL_WIDTH)
        self.widget.selectedBreakdownBox.setMaximumWidth(ENDGAME_REVIEW_BREAKDOWN_PANEL_WIDTH)
        self.widget.selectedBreakdownBox.setMinimumHeight(0)
        self.widget.selectedBreakdownBox.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.widget.selectedBreakdownBox.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.widget.selectedBreakdownBox.setLineWrapMode(self.widget.selectedBreakdownBox.LineWrapMode.WidgetWidth)
        self.victory_points_plot.setMinimumSize(0, 0)
        self.replay_canvas.setMinimumSize(0, 0)
        self.replay_canvas.setMinimumWidth(ENDGAME_REPLAY_MIN_PANEL_WIDTH)
        self.widget.selectedMomentScrollArea.setMinimumSize(0, 0)
        self.widget.selectedMomentScrollArea.setMinimumWidth(ENDGAME_REPLAY_MIN_PANEL_WIDTH)
        self.widget.selectedBreakdownBox.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.widget.titleWinnerLabel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.widget.selectedBreakdownBox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.widget.selectedMomentScrollArea.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.replay_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.widget.replayMainLayout.setStretch(0, 1)
        self.widget.main_menu_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        self.widget.quit_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)

    def configure_endgame_feedback_filters(self) -> None:
        """Connect the endgame feedback filter checkboxes."""
        checkboxes = self.widget.feedbackTab.findChildren(QCheckBox)
        for checkbox in checkboxes:
            label = checkbox.text().strip().lower()
            self.feedback_filter_checkboxes[label] = checkbox
            checkbox.toggled.connect(self.refresh_endgame_feedback_list)

    @staticmethod
    def strip_html(text: str) -> str:
        """Strip HTML markup from the given text."""
        return strip_html(text)

    @staticmethod
    def compact_feedback_action(action_text: str) -> str:
        """Shorten an endgame feedback action label."""
        return compact_feedback_action(action_text)

    @classmethod
    def feedback_card_title(cls, feedback: TutorFeedbackExplanation) -> str:
        """Build the title text for an endgame feedback card."""
        return feedback_card_title(feedback)

    @staticmethod
    def endgame_feedback_filter_state_from_owner(owner) -> Dict[str, bool]:
        """Read the endgame feedback filter state from an owner."""
        return endgame_feedback_filter_state_from_owner(owner)

    def endgame_feedback_filter_state(self) -> Dict[str, bool]:
        """Read the current endgame feedback filter state."""
        return self.endgame_feedback_filter_state_from_owner(self)

    @classmethod
    def feedback_matches_filter_from_owner(cls, owner, feedback: TutorFeedbackExplanation) -> bool:
        """Check whether feedback matches the owner filter state."""
        filter_state = cls.endgame_feedback_filter_state_from_owner(owner)
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

    def feedback_matches_filter(self, feedback: TutorFeedbackExplanation) -> bool:
        """Check whether feedback matches the active filters."""
        return self.feedback_matches_filter_from_owner(self, feedback)

    def jump_to_endgame_feedback(self, index: int) -> None:
        """Jump to a specific endgame feedback item."""
        self.widget.reviewTabs.setCurrentIndex(0)
        self.render_endgame_replay_feedback(index)

    def build_endgame_feedback_card(self, feedback: TutorFeedbackExplanation, index: int) -> QPushButton:
        """Build a clickable card for an endgame feedback item."""
        card_btn = QPushButton()
        card_btn.setObjectName("endgameFeedbackCard")
        card_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        card_btn.setStyleSheet(endgame_feedback_card_stylesheet())
        card_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(card_btn)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ENDGAME_FEEDBACK_CARD_LAYOUT_SPACING_PX)

        title_label = QLabel(self.feedback_card_title(feedback), card_btn)
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

        card_btn.clicked.connect(lambda _checked=False, replay_index=index: self.jump_to_endgame_feedback(replay_index))
        return card_btn

    def refresh_endgame_feedback_list(self) -> None:
        """Rebuild the filtered endgame feedback list."""
        layout = self.widget.feedbackListLayout
        self.window._clear_layout(layout)

        visible_feedback = [(index, feedback) for index, feedback in enumerate(self.replay_feedback)
                            if self.feedback_matches_filter(feedback)]

        if not visible_feedback:
            empty_label = QLabel("No feedback items match the selected filters.")
            empty_label.setStyleSheet(endgame_feedback_empty_stylesheet())
            empty_label.setWordWrap(True)
            layout.addWidget(empty_label)
        else:
            for index, feedback in visible_feedback:
                layout.addWidget(self.build_endgame_feedback_card(feedback, index))

        layout.addStretch(1)

    @classmethod
    def replay_feedback_player_name(cls, feedback: TutorFeedbackExplanation) -> str:
        """Return the player name for a replay feedback item."""
        return replay_feedback_player_name(feedback)

    @classmethod
    def format_replay_feedback_details(cls, feedback: TutorFeedbackExplanation, total_turns: int) -> Dict[str, str]:
        """Format the detail fields for replay feedback."""
        return format_replay_feedback_details(feedback, total_turns)

    @staticmethod
    def overall_performance_summary(
        feedback_items: List[TutorFeedbackExplanation],
        final_snapshot: PlayerScoreSnapshot | None = None,
        leader_vp: int | None = None,
    ) -> Dict[str, str]:
        """Summarise the overall endgame performance."""
        return overall_performance_summary(feedback_items, final_snapshot, leader_vp)

    @staticmethod
    def outcome_performance_score(final_snapshot: PlayerScoreSnapshot | None) -> float | None:
        """Return the final outcome performance score."""
        return outcome_performance_score(final_snapshot)

    @staticmethod
    def outcome_strength_line(final_snapshot: PlayerScoreSnapshot | None) -> str | None:
        """Return the outcome strength summary line."""
        return outcome_strength_line(final_snapshot)

    @staticmethod
    def outcome_weakness_line(final_snapshot: PlayerScoreSnapshot | None, leader_vp: int | None) -> str | None:
        """Return the outcome weakness summary line."""
        return outcome_weakness_line(final_snapshot, leader_vp)

    @staticmethod
    def performance_category(feedback: TutorFeedbackExplanation) -> str:
        """Return the performance category for feedback."""
        return performance_category(feedback)

    @staticmethod
    def performance_line(category: str, score: float, positive: bool) -> str:
        """Format a single performance summary line."""
        return performance_line(category, score, positive)

    def render_endgame_replay_feedback(self, index: int) -> None:
        """Render the selected endgame replay feedback item."""
        if not self.replay_feedback and self.final_board_source is None:
            return

        max_index = len(self.replay_feedback)
        index = max(0, min(index, max_index))
        self.replay_index = index
        is_summary = index == len(self.replay_feedback)
        if is_summary:
            details = self.overall_performance_summary(
                self.replay_feedback,
                self.human_final_snapshot,
                self.final_leader_vp,
            )
            self.replay_canvas.display_board(self.final_board_source)
            self.replay_canvas.clear_planned_builds()
            self.replay_canvas.clear_feedback_builds()
        else:
            feedback = self.replay_feedback[index]
            details = self.format_replay_feedback_details(feedback, self.total_turns)
            self.replay_canvas.display_board(feedback.board_snapshot)
            self.replay_canvas.clear_planned_builds()
            self.replay_canvas.clear_feedback_builds()
            if feedback.recommended_visual_plan:
                self.replay_canvas.render_planned_builds(feedback.recommended_visual_plan)
            if feedback.visual_build_plan:
                self.replay_canvas.render_feedback_builds(feedback.visual_build_plan)

        self.widget.sectionTitle.setText("Game Summary" if is_summary else "Selected Moment")
        self.widget.turnAndPlayer.setText(details["turn_and_player"])
        self.widget.actionLabel.setText(details["action"])
        self.widget.selectedMomentBadge.setText(details["badge"])
        self.widget.selectedMomentBadge.setStyleSheet(endgame_badge_stylesheet(details["badge"]))
        self.widget.scoreLabel.setText(details["score"])
        self.widget.tutorFeedback.setText(details["tutor_feedback"])
        self.widget.adviceLabel.setText(details["advice"])
        self.widget.turnLabel.setText(details["turn_label"])

        slider = self.widget.timelineSlider
        was_blocked = slider.blockSignals(True)
        slider.setValue(index)
        slider.blockSignals(was_blocked)
        self.widget.prevTurn.setEnabled(index > 0)
        self.widget.nextTurn.setEnabled(index < len(self.replay_feedback))
        self.sync_replay_layout()

    def show_previous_endgame_replay_feedback(self) -> None:
        """Show the previous endgame replay feedback item."""
        if self.replay_index is None:
            return
        self.render_endgame_replay_feedback(self.replay_index - 1)

    def show_next_endgame_replay_feedback(self) -> None:
        """Show the next endgame replay feedback item."""
        if self.replay_index is None:
            return
        self.render_endgame_replay_feedback(self.replay_index + 1)

    def mark_replay_splitter_adjusted(self) -> None:
        """Mark the replay splitter as user-adjusted."""
        if self.replay_splitter_initialised:
            self.replay_splitter_user_adjusted = True

    def set_replay_splitter_sizes(self, prefer_equal: bool = False) -> None:
        """Set the replay splitter panel sizes."""
        total_width = max(0, self.replay_splitter.width())
        if total_width <= 0:
            return
        if prefer_equal or not self.replay_splitter_user_adjusted:
            left_width = max(self.replay_canvas.minimumWidth(), total_width // 2)
            right_width = max(self.widget.selectedMomentScrollArea.minimumWidth(), total_width - left_width)
            if left_width + right_width > total_width:
                left_width = max(self.replay_canvas.minimumWidth(), total_width - right_width)
            self.replay_splitter.setSizes([left_width, right_width])
            self.replay_splitter_initialised = True

    def sync_replay_layout(self) -> None:
        """Synchronise the replay tab layout sizing."""
        if not self.widget.replayTab.isVisible():
            return
        self.set_replay_splitter_sizes(prefer_equal=not self.replay_splitter_initialised)

    def handle_event_filter(self, watched: QObject, event: QEvent) -> bool:
        """Handle replay layout events from watched widgets."""
        if watched in {self.widget.replayTab, self.widget.selectedMomentScrollArea} and event.type() in {
                QEvent.Type.Resize,
                QEvent.Type.Show,
        }:
            QTimer.singleShot(0, self.sync_replay_layout)
            return False
        return False

    def populate_tutor_endgame_performance(self, controller: GameController) -> None:
        """Populate the tutor endgame performance chart."""
        populate_tutor_endgame_performance(self, controller)

    @classmethod
    def build_endgame_plot_tooltips(
        cls,
        history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
        players: List[Player],
    ) -> Dict[int, str]:
        """Build tooltip text for the endgame performance plot."""
        return build_endgame_plot_tooltips(history, players)

    @classmethod
    def describe_round_vp_events(
        cls,
        previous_snapshot: Dict[PlayerNumber, PlayerScoreSnapshot] | None,
        current_snapshot: Dict[PlayerNumber, PlayerScoreSnapshot],
        player_names: Dict[PlayerNumber, str],
    ) -> List[str]:
        """Describe victory-point changes for a review round."""
        return describe_round_vp_events(previous_snapshot, current_snapshot, player_names)

    @staticmethod
    def format_endgame_players(names: List[str]) -> str:
        """Format a list of endgame player names."""
        return format_endgame_players(names)

    @classmethod
    def summarise_endgame_review_labels(
        cls,
        history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
        players: List[Player],
    ) -> Tuple[str, str, str]:
        """Build the headline summary labels for endgame review."""
        return summarise_endgame_review_labels(history, players)

    @classmethod
    def build_lead_change_label(cls, history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
                                player_names: Dict[PlayerNumber, str]) -> str:
        """Build the lead-change summary label."""
        return build_lead_change_label(history, player_names)

    @classmethod
    def build_biggest_swing_label(cls, history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
                                  player_names: Dict[PlayerNumber, str]) -> str:
        """Build the biggest-swing summary label."""
        return build_biggest_swing_label(history, player_names)

    @staticmethod
    def join_reasons(reasons: List[str]) -> str:
        """Join endgame reason strings into readable text."""
        return join_reasons(reasons)

    @staticmethod
    def score_swing_reasons(previous: PlayerScoreSnapshot, current: PlayerScoreSnapshot) -> List[str]:
        """Describe the reasons for a score swing."""
        return score_swing_reasons(previous, current)

    @classmethod
    def build_closest_moment_label(cls, history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
                                   player_names: Dict[PlayerNumber, str]) -> str:
        """Build the closest-moment summary label."""
        return build_closest_moment_label(history, player_names)

    def populate_tutor_endgame_review(self, controller: GameController) -> None:
        """Populate the tutor endgame review view."""
        self.configure_tutor_endgame_layout()
        sorted_players = sorted(controller.get_all_players(), key=lambda p: p.calc_victory_points()[1], reverse=True)
        winner = sorted_players[0]
        winner_total_vp = winner.calc_victory_points()[1]
        self.set_endgame_winner_header(winner.name, winner_total_vp)

        ranking_layout = self.widget.rankingCardsLayout
        self.window._clear_layout(ranking_layout)
        self.rank_cards = []
        self.selected_rank_card = None

        for rank, player in enumerate(sorted_players, start=1):
            total_vp = player.calc_victory_points()[1]
            ranking_summary = self.format_player_ranking_summary(player)
            card_text = f"{rank}. {player.name} - {total_vp} VP"
            if ranking_summary:
                card_text += f"\n{ranking_summary}"
            card_btn = QPushButton(card_text)
            card_btn.setObjectName("rankCard")
            card_btn.setCheckable(False)
            card_btn.setStyleSheet(self.endgame_rank_card_stylesheet(False))
            card_btn.setMinimumWidth(0)
            card_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            card_btn.clicked.connect(lambda _checked=False, selected_player=player, selected_btn=card_btn: self.
                                     select_endgame_rank_card(selected_btn, selected_player))
            ranking_layout.addWidget(card_btn)
            self.rank_cards.append(card_btn)

        if self.rank_cards:
            self.select_endgame_rank_card(self.rank_cards[0], winner)

        self.populate_tutor_endgame_performance(controller)
        self.replay_feedback = list(controller.get_tutor_feedback_history())
        self.refresh_endgame_feedback_list()
        self.final_board_source = controller
        self.human_final_snapshot = None
        self.final_leader_vp = None
        self.replay_splitter_user_adjusted = False
        self.replay_splitter_initialised = False

        history = controller.get_victory_point_history()
        review_history = controller.get_endgame_review_history()
        if review_history:
            final_snapshot = review_history[-1][1]
            human_player = next((player for player in controller.get_all_players() if player.is_human), None)
            if human_player is not None:
                self.human_final_snapshot = final_snapshot.get(human_player.player_number)
            if final_snapshot:
                self.final_leader_vp = max(player.total_vp for player in final_snapshot.values())

        self.total_turns = max((round_num for round_num, _ in history), default=0)
        replay_slider = self.widget.timelineSlider
        replay_slider.setMinimum(0)
        replay_slider.setMaximum(max(0, len(self.replay_feedback)))
        replay_slider.setEnabled(bool(self.replay_feedback))
        self.window.safe_connect(self.widget.prevTurn, self.show_previous_endgame_replay_feedback)
        self.window.safe_connect(self.widget.nextTurn, self.show_next_endgame_replay_feedback)
        try:
            replay_slider.valueChanged.disconnect()
        except TypeError:
            pass
        replay_slider.valueChanged.connect(self.render_endgame_replay_feedback)

        if self.replay_feedback:
            self.render_endgame_replay_feedback(len(self.replay_feedback))
        else:
            self.replay_canvas.clear_shapes()
            self.widget.turnAndPlayer.setText("No replay moments recorded")
            self.widget.actionLabel.setText("Action: None")
            self.widget.selectedMomentBadge.setText("N/A")
            self.widget.selectedMomentBadge.setStyleSheet(endgame_badge_stylesheet(""))
            self.widget.scoreLabel.setText("Score: N/A")
            self.widget.tutorFeedback.setText("Tutor feedback: No tutor feedback history was recorded.")
            self.widget.adviceLabel.setText("No advice available.")
            self.widget.turnLabel.setText("Turn 0 / 0")
            self.widget.prevTurn.setEnabled(False)
            self.widget.nextTurn.setEnabled(False)

        lead_change_label, biggest_swing_label, closest_moment_label = self.summarise_endgame_review_labels(
            controller.get_endgame_review_history(),
            controller.get_all_players(),
        )
        self.widget.leadChangeLabel.setText(lead_change_label)
        self.widget.biggestSwingLabel.setText(biggest_swing_label)
        self.widget.closestMomentLabel.setText(closest_moment_label)

    def display_tutor_endgame_review(self, controller: GameController) -> None:
        """Display the tutor endgame review screen."""

        def return_to_main_menu() -> None:
            self.window._restore_splitter_layout()
            controller.start_game()

        self.window.open_tutor_menu(False)
        self.populate_tutor_endgame_review(controller)
        self.widget.reviewTabs.setCurrentIndex(0)
        self.window.safe_connect(self.widget.main_menu_btn, return_to_main_menu)
        self.window.safe_connect(self.widget.quit_btn, self.window.close)
        self.window._show_fullscreen_panel(self.widget)
        QTimer.singleShot(0, self.sync_replay_layout)

    def display_results(self, controller: GameController) -> None:
        """Display the game results view."""
        self.window._restore_splitter_layout()
        self.window.open_tutor_menu(False)
        self.window.canvas.clear_planned_builds()
        self.window.canvas.interactive_shapes.clear()
        self.window.canvas.display_board(controller)
        self.window.display_resources(controller)

        sizes = self.window.splitter_layout.sizes()
        self.window.main_menu.setParent(None)
        self.window.splitter_layout.addWidget(self.results_menu)
        self.window.splitter_layout.setSizes([sizes[0], sizes[1]])

        all_labels = {}
        for i in range(1, 5):
            all_labels[i] = {
                "score": getattr(self.results_menu, f"score_{i}"),
                "player": getattr(self.results_menu, f"player_label_{i}"),
                "settlements": getattr(self.results_menu, f"settlements_{i}"),
                "cities": getattr(self.results_menu, f"cities_{i}"),
                "longest_road": getattr(self.results_menu, f"longest_road_{i}"),
                "largest_army": getattr(self.results_menu, f"largest_army_{i}"),
                "victory_cards": getattr(self.results_menu, f"victory_cards_{i}"),
            }
            for label in all_labels[i].values():
                label.setText("")
                label.hide()

        sorted_players = sorted(controller.get_all_players(), key=lambda p: p.calc_victory_points()[1], reverse=True)
        self.results_menu.winner_label.setText(sorted_players[0].name + "!")

        for rank, player in enumerate(sorted_players, start=1):
            labels = all_labels[rank]
            labels["score"].setText(f"{rank}. {player.name}: {player.calc_victory_points()[1]} pts")
            labels["score"].show()
            labels["player"].setText(f"{player.name}: {player.calc_victory_points()[1]} pts")
            labels["player"].show()

            if player.settlements:
                labels["settlements"].setText(f"Settlements: {len(player.settlements)}")
                labels["settlements"].show()
            if player.cities:
                labels["cities"].setText(f"Cities: {len(player.cities)}")
                labels["cities"].show()
            if player.has_longest_road:
                labels["longest_road"].setText(f"Longest Road: {player.longest_road_length}")
                labels["longest_road"].show()
            if player.has_largest_army:
                labels["largest_army"].setText(f"Largest Army: {player.army_size}")
                labels["largest_army"].show()

            num_vp_cards = len(
                [c for c in player.development_cards if c.card_type == DevelopmentCardType.VICTORY_POINT])
            if num_vp_cards > 0:
                labels["victory_cards"].setText(f"Victory Card Points: {num_vp_cards}")
                labels["victory_cards"].show()

        def return_to_main_menu() -> None:
            layout_sizes = self.window.splitter_layout.sizes()
            self.results_menu.setParent(None)
            self.window.splitter_layout.addWidget(self.window.main_menu)
            self.window.splitter_layout.setSizes(layout_sizes)
            self.window.main_menu.show()
            controller.start_game()

        self.window.safe_connect(self.results_menu.main_menu_btn, return_to_main_menu)
        self.window.safe_connect(self.results_menu.quit_btn, self.window.close)
