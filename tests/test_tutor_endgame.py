import unittest
from types import SimpleNamespace
from typing import cast

from PyQt6.QtWidgets import QCheckBox
from test_helpers import GameTestMixin, ReplayMarker

from ai.tutor.feedback import TutorDecisionType, TutorFeedbackExplanation
from controllers.GameController import PlayerScoreSnapshot
from game.Player import PlayerNumber
from view.panels.endgame_review_panel import EndgameReviewPanel
from view.panels.TutorPanel import TutorPanel


class TestTutorEndgame(GameTestMixin, unittest.TestCase):

    def test_endgame_review_labels_use_round_history(self):
        p1 = PlayerNumber.P1
        p2 = PlayerNumber.P2
        p3 = PlayerNumber.P3
        p4 = PlayerNumber.P4
        history = [
            (1, {
                p1: PlayerScoreSnapshot(2, 2, 2, 0, 0, 2, 0, False, False),
                p2: PlayerScoreSnapshot(2, 2, 2, 0, 0, 2, 0, False, False),
                p3: PlayerScoreSnapshot(1, 1, 1, 0, 0, 1, 0, False, False),
                p4: PlayerScoreSnapshot(2, 2, 1, 0, 0, 1, 0, False, False),
            }),
            (2, {
                p1: PlayerScoreSnapshot(4, 4, 2, 0, 0, 5, 0, True, False),
                p2: PlayerScoreSnapshot(3, 3, 3, 0, 0, 2, 0, False, False),
                p3: PlayerScoreSnapshot(2, 2, 2, 0, 0, 1, 0, False, False),
                p4: PlayerScoreSnapshot(4, 4, 2, 1, 0, 1, 0, False, False),
            }),
            (3, {
                p1: PlayerScoreSnapshot(6, 6, 2, 1, 0, 6, 0, True, False),
                p2: PlayerScoreSnapshot(4, 4, 2, 1, 0, 2, 0, False, False),
                p3: PlayerScoreSnapshot(3, 3, 3, 0, 0, 2, 0, False, False),
                p4: PlayerScoreSnapshot(5, 5, 1, 2, 0, 1, 0, False, False),
            }),
        ]
        players = [
            self.fake_player(p1, "P1"),
            self.fake_player(p2, "P2"),
            self.fake_player(p3, "P3"),
            self.fake_player(p4, "P4"),
        ]

        lead, swing, closest = EndgameReviewPanel.summarise_endgame_review_labels(history, players)

        self.assertEqual(lead, "P1 took the lead in Round 3 and held it through Round 3.")
        self.assertEqual(swing, "Round 2: P1 gained Longest Road and jumped by 2 VP.")
        self.assertEqual(closest, "Round 2: P1 and P4 were tied at 4 VP.")

    def test_endgame_plot_tooltip_lists_scores_leader_and_multiple_events(self):
        p1 = PlayerNumber.P1
        p2 = PlayerNumber.P2
        p3 = PlayerNumber.P3
        p4 = PlayerNumber.P4
        history = [
            (17, {
                p1: PlayerScoreSnapshot(5, 5, 3, 1, 0, 4, 0, False, False),
                p2: PlayerScoreSnapshot(4, 4, 2, 1, 0, 4, 0, False, False),
                p3: PlayerScoreSnapshot(5, 5, 3, 1, 0, 4, 0, False, False),
                p4: PlayerScoreSnapshot(7, 7, 3, 2, 0, 5, 0, True, False),
            }),
            (18, {
                p1: PlayerScoreSnapshot(6, 6, 2, 2, 0, 4, 0, False, False),
                p2: PlayerScoreSnapshot(4, 4, 2, 1, 0, 4, 0, False, False),
                p3: PlayerScoreSnapshot(5, 5, 3, 1, 0, 4, 0, False, False),
                p4: PlayerScoreSnapshot(5, 5, 3, 2, 0, 4, 0, False, False),
            }),
        ]
        players = [
            self.fake_player(p1, "P1"),
            self.fake_player(p2, "P2"),
            self.fake_player(p3, "P3"),
            self.fake_player(p4, "P4"),
        ]

        tooltips = EndgameReviewPanel.build_endgame_plot_tooltips(history, players)

        self.assertEqual(
            tooltips[18], "\n".join([
                "Turn 18",
                "",
                "P1: 6 VP",
                "P2: 4 VP",
                "P3: 5 VP",
                "P4: 5 VP",
                "",
                "Leader: P1",
                "Event:",
                "- P1 built a city",
                "- P4 lost Longest Road",
            ]))

    def test_endgame_plot_tooltip_marks_tied_leader(self):
        p1 = PlayerNumber.P1
        p2 = PlayerNumber.P2
        history = [
            (18, {
                p1: PlayerScoreSnapshot(6, 6, 2, 2, 0, 4, 0, False, False),
                p2: PlayerScoreSnapshot(6, 6, 2, 2, 0, 4, 0, False, False),
            }),
        ]
        players = [
            self.fake_player(p1, "P1"),
            self.fake_player(p2, "P2"),
        ]

        tooltips = EndgameReviewPanel.build_endgame_plot_tooltips(history, players)

        self.assertIn("Leader: P1 and P2 (tied)", tooltips[18])

    def test_replay_feedback_details_include_turn_action_and_advice(self):
        assessment = self.fake_assessment(
            your_move="Build a road",
            internal_score=0.53,
            score_gap=0.35,
            judgment_sentence="This road was playable, but it delayed a stronger city plan.",
            better_move="End the turn",
            tip="Preserve resources for the city upgrade.",
        )
        feedback = self.fake_feedback(
            board_snapshot=SimpleNamespace(
                game_state=SimpleNamespace(round_num=18),
                get_all_players=lambda: [self.fake_player(PlayerNumber.P1, "P1", is_human=True)],
            ),
            assessment=assessment,
            label="Okay",
            title="Main Turn",
            history_summary="[Okay] This road was playable.",
        )

        details = EndgameReviewPanel.format_replay_feedback_details(feedback, 42)

        self.assertEqual(details["turn_and_player"], "Turn 18 - P1")
        self.assertEqual(details["action"], "Action: Build a road")
        self.assertEqual(details["badge"], "Okay")
        self.assertIn("Score: 0.53", details["score"])
        self.assertIn("Gap: +0.35", details["score"])
        self.assertEqual(
            details["tutor_feedback"],
            "Tutor feedback: This road was playable, but it delayed a stronger city plan.",
        )
        self.assertEqual(
            details["advice"],
            "Better move: End the turn\nTakeaway: Preserve resources for the city upgrade.",
        )
        self.assertEqual(details["turn_label"], "Turn 18 / 42")

    def test_replay_feedback_details_include_resource_context_for_trade_feedback(self):
        assessment = self.fake_assessment(
            your_move="Offer 2 Wood in exchange for 1 Brick.",
            move_context="Exchange: give 2 Wood for 1 Brick",
            internal_score=0.41,
            score_gap=0.22,
            judgment_sentence="The trade was legal, but it paid too much.",
            better_move="Offer 1 Wood in exchange for 1 Brick.",
            better_move_context="Exchange: give 1 Wood for 1 Brick",
            tip="Keep more flexibility for the build after the trade.",
        )
        feedback = self.fake_feedback(
            board_snapshot=SimpleNamespace(
                game_state=SimpleNamespace(round_num=7),
                get_all_players=lambda: [self.fake_player(PlayerNumber.P1, "P1", is_human=True)],
            ),
            assessment=assessment,
            label="Okay",
            title="Trade",
            history_summary="[Okay] The trade was legal.",
        )

        details = EndgameReviewPanel.format_replay_feedback_details(feedback, 20)

        self.assertEqual(
            details["action"],
            "Action: Offer 2 Wood in exchange for 1 Brick.\nExchange: give 2 Wood for 1 Brick",
        )
        self.assertEqual(
            details["advice"],
            "Better move: Offer 1 Wood in exchange for 1 Brick.\n"
            "Exchange: give 1 Wood for 1 Brick\n"
            "Takeaway: Keep more flexibility for the build after the trade.",
        )

    def test_feedback_card_title_uses_turn_and_compact_action(self):
        feedback = self.fake_feedback(
            board_snapshot=SimpleNamespace(game_state=SimpleNamespace(round_num=18)),
            assessment=self.fake_assessment(your_move="building a road"),
            title="Main Turn",
        )

        title = EndgameReviewPanel.feedback_card_title(feedback)

        self.assertEqual(title, "Turn 18 - Built Road")

    def test_feedback_filter_maps_labels_to_requested_groups(self):
        owner = SimpleNamespace(feedback_filter_checkboxes=cast(
            dict[str, QCheckBox], {
                "biggest mistakes": self.fake_checkbox(True),
                "okay moves": self.fake_checkbox(False),
                "good moves": self.fake_checkbox(True),
                "excellent moves": self.fake_checkbox(False),
            }))

        self.assertTrue(EndgameReviewPanel.feedback_matches_filter_from_owner(owner, self.fake_feedback(label="Poor")))
        self.assertFalse(
            EndgameReviewPanel.feedback_matches_filter_from_owner(
                owner,
                self.fake_feedback(label="Okay"),
            ))
        self.assertTrue(EndgameReviewPanel.feedback_matches_filter_from_owner(owner, self.fake_feedback(label="Good")))
        self.assertFalse(
            EndgameReviewPanel.feedback_matches_filter_from_owner(
                owner,
                self.fake_feedback(label="Excellent"),
            ))

    def test_feedback_filter_maps_poor_okay_good_and_excellent(self):
        owner = SimpleNamespace(feedback_filter_checkboxes=cast(
            dict[str, QCheckBox], {
                "biggest mistakes": self.fake_checkbox(True),
                "okay moves": self.fake_checkbox(False),
                "good moves": self.fake_checkbox(True),
                "excellent moves": self.fake_checkbox(False),
            }))

        poor_feedback = self.fake_feedback(label="Poor")
        okay_feedback = self.fake_feedback(label="Okay")
        good_feedback = self.fake_feedback(label="Good")
        excellent_feedback = self.fake_feedback(label="Excellent")

        self.assertTrue(EndgameReviewPanel.feedback_matches_filter_from_owner(owner, poor_feedback))
        self.assertFalse(EndgameReviewPanel.feedback_matches_filter_from_owner(owner, okay_feedback))
        self.assertTrue(EndgameReviewPanel.feedback_matches_filter_from_owner(owner, good_feedback))
        self.assertFalse(EndgameReviewPanel.feedback_matches_filter_from_owner(owner, excellent_feedback))

    def test_overall_performance_summary_uses_final_summary_format(self):
        feedbacks = cast(list[TutorFeedbackExplanation], [
            self.fake_feedback(assessment=self.fake_assessment(decision_type=TutorDecisionType.ROBBER,
                                                               your_move="Move the robber", internal_score=0.9)),
            self.fake_feedback(assessment=self.fake_assessment(decision_type=TutorDecisionType.MAIN_TURN,
                                                               your_move="Ending the turn", internal_score=0.75)),
            self.fake_feedback(assessment=self.fake_assessment(decision_type=TutorDecisionType.DISCARD,
                                                               your_move="Discard resources", internal_score=0.2)),
            self.fake_feedback(assessment=self.fake_assessment(decision_type=TutorDecisionType.MAIN_TURN,
                                                               your_move="Upgrading to a city", internal_score=0.3)),
        ])

        final_snapshot = PlayerScoreSnapshot(3, 3, 3, 0, 0, 3, 0, False, False)
        summary = EndgameReviewPanel.overall_performance_summary(feedbacks, final_snapshot, leader_vp=10)

        self.assertEqual(summary["turn_and_player"], "")
        self.assertEqual(summary["action"], "Your Performance")
        self.assertEqual(summary["badge"], "Poor")
        self.assertEqual(summary["score"], "Overall: Poor (0.34) | Moves 0.54 | VP 0.30 | Win 0.00")
        self.assertIn("Robber placement", summary["tutor_feedback"])
        self.assertIn("finished on only 3 VP", summary["advice"])
        self.assertIn("Discard decisions", summary["advice"])

    def test_overall_performance_summary_does_not_rate_two_vp_finish_as_good(self):
        feedbacks = cast(list[TutorFeedbackExplanation], [
            self.fake_feedback(assessment=self.fake_assessment(
                decision_type=TutorDecisionType.MAIN_TURN,
                your_move="Building a road",
                internal_score=0.8,
            )),
        ])

        summary = EndgameReviewPanel.overall_performance_summary(
            feedbacks,
            PlayerScoreSnapshot(2, 2, 2, 0, 0, 2, 0, False, False),
            leader_vp=10,
        )

        self.assertEqual(summary["badge"], "Poor")

    def test_tutor_replay_history_is_not_trimmed_with_sidebar_history(self):
        owner = SimpleNamespace(
            tutor_feedback_history=[],
            tutor_feedback_replay_history=[],
            _update_previous_feedback_button=lambda: None,
        )

        feedbacks = [ReplayMarker(index=i) for i in range(105)]
        for feedback in feedbacks:
            TutorPanel.append_feedback_history_state(owner, cast(TutorFeedbackExplanation, feedback))

        self.assertEqual(len(owner.tutor_feedback_history), 100)
        self.assertEqual(len(owner.tutor_feedback_replay_history), 105)
        self.assertEqual(cast(ReplayMarker, owner.tutor_feedback_replay_history[0]).index, 0)
        self.assertEqual(cast(ReplayMarker, owner.tutor_feedback_history[0]).index, 5)
