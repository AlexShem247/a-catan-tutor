import unittest
from random import Random
from types import SimpleNamespace

from ai.RuleBasedAI import RuleBasedAI
from ai.actions import Action, ActionType
from ai.tutor.evaluator import TutorEvaluator
from ai.tutor.explanations import ActionExplanation, CandidateExplanation, Reason, ReasonLabel, ReasonType
from ai.tutor.feedback import TutorAssessment, TutorDecisionType, TutorFeedbackExplanation
from ai.tutor.move_quality import tutor_move_quality_label
from game.PlayerAssets import Buildable


class TestTutorFeedback(unittest.TestCase):
    def setUp(self):
        self.evaluator = TutorEvaluator(RuleBasedAI(Random(0)))

    @staticmethod
    def _build_explanation(action: Action, reasons_for, reasons_against, move_quality: float) -> ActionExplanation:
        candidate = CandidateExplanation(
            action=action,
            full_plan=[action],
            reasons_for=reasons_for,
            reasons_against=reasons_against,
        )
        return ActionExplanation(
            chosen_action=action,
            chosen_candidate=candidate,
            move_quality=move_quality,
        )

    def test_reason_based_feedback_hides_raw_scores(self):
        actual = self._build_explanation(
            Action(ActionType.BUILD, (Buildable.ROAD, None)),
            [Reason(ReasonType.ENABLES_EXPANSION, ReasonLabel.PLAN_ROAD_VALUE, 3.0)],
            [Reason(ReasonType.AVOIDS_EARLY_ATTENTION, ReasonLabel.EARLY_ATTENTION_RISK, 1.0)],
            move_quality=0.55,
        )
        best = self._build_explanation(
            Action(ActionType.BUILD, (Buildable.SETTLEMENT, None)),
            [
                Reason(ReasonType.ENABLES_EXPANSION, ReasonLabel.PLAN_SETTLEMENT_VALUE, 4.0),
                Reason(ReasonType.QUICK_TO_EXECUTE, ReasonLabel.QUICK_GENERIC, 2.0),
            ],
            [],
            move_quality=0.9,
        )

        assessment = self.evaluator._build_assessment(TutorDecisionType.MAIN_TURN, actual, best)
        feedback = TutorFeedbackExplanation.from_assessment("Main Turn", assessment, SimpleNamespace())

        self.assertEqual(assessment.label, "Good")
        self.assertAlmostEqual(assessment.score_gap, 0.35)
        self.assertIn("build a road", assessment.your_move.lower())
        self.assertIn("build a settlement", (assessment.better_move or "").lower())
        self.assertIn("Better move", feedback.concise_html)
        self.assertIn("Takeaway", feedback.detailed_html)
        self.assertNotRegex(feedback.concise_html, r"\d+\.\d+")
        self.assertNotRegex(feedback.detailed_html, r"\d+\.\d+")

    def test_matching_choice_omits_better_move(self):
        explanation = self._build_explanation(
            Action(ActionType.BUY_DEV_CARD),
            [Reason(ReasonType.HIDDEN_VALUE, ReasonLabel.HIDDEN_DEV_VALUE, 1.0)],
            [],
            move_quality=0.85,
        )

        assessment = self.evaluator._build_assessment(TutorDecisionType.MAIN_TURN, explanation, explanation)

        self.assertIsNone(assessment.better_move)
        self.assertFalse(assessment.top_weaknesses)
        self.assertIn("matched the tutor's preferred move", assessment.judgment_sentence)

    def test_poor_stays_poor_in_feedback_but_maps_to_okay_for_tutor_hints(self):
        actual = self._build_explanation(
            Action(ActionType.END_TURN),
            [],
            [Reason(ReasonType.REQUIRES_TRADE, ReasonLabel.NO_IMMEDIATE_ACTION, 1.0)],
            move_quality=0.1,
        )
        best = self._build_explanation(
            Action(ActionType.BUY_DEV_CARD),
            [Reason(ReasonType.HIDDEN_VALUE, ReasonLabel.HIDDEN_DEV_VALUE, 1.0)],
            [],
            move_quality=0.85,
        )

        assessment = self.evaluator._build_assessment(TutorDecisionType.MAIN_TURN, actual, best)
        feedback = TutorFeedbackExplanation.from_assessment("Main Turn", assessment, SimpleNamespace())

        self.assertEqual(actual.move_quality_label, "Poor")
        self.assertEqual(actual.tutor_move_quality_label, "Okay")
        self.assertEqual(tutor_move_quality_label(0.1), "Okay")
        self.assertEqual(assessment.label, "Poor")
        self.assertIn("#b34700", feedback.concise_html)

    def test_detailed_feedback_removes_duplicate_reasons_and_duplicate_better_move_text(self):
        assessment = TutorAssessment(
            decision_type=TutorDecisionType.OPENING_ROAD,
            internal_score=0.2,
            best_internal_score=0.8,
            label="Poor",
            judgment_sentence="It keeps your road network flexible, but a stronger line was available.",
            your_move="Place your road where it keeps your opening flexible.",
            better_move="Place your road where it keeps your opening flexible.",
            top_strengths=["It keeps your road network flexible."],
            top_weaknesses=["It keeps your road network flexible."],
            better_move_reasons=["It keeps your road network flexible."],
            tip="Aim roads at the strongest follow-up settlement line you can keep open.",
        )

        detailed_html = assessment.detailed_html()

        self.assertEqual(detailed_html.count("It keeps your road network flexible."), 1)
        self.assertEqual(detailed_html.count("Better move:"), 0)

    def test_feedback_stores_recommended_build_visual_plan_for_history_only_when_move_differs(self):
        actual = self._build_explanation(
            Action(ActionType.BUILD, (Buildable.ROAD, "actual-edge")),
            [Reason(ReasonType.ENABLES_EXPANSION, ReasonLabel.PLAN_ROAD_VALUE, 1.0)],
            [],
            move_quality=0.4,
        )
        best = self._build_explanation(
            Action(ActionType.BUILD, (Buildable.SETTLEMENT, "best-vertex")),
            [Reason(ReasonType.ENABLES_EXPANSION, ReasonLabel.PLAN_SETTLEMENT_VALUE, 2.0)],
            [],
            move_quality=0.9,
        )

        feedback = self.evaluator._feedback_from_explanations(
            TutorDecisionType.MAIN_TURN,
            actual,
            best,
            SimpleNamespace(),
            title="Main Turn",
        )

        self.assertIsNotNone(feedback)
        self.assertEqual(feedback.recommended_visual_plan, [(Buildable.SETTLEMENT, "best-vertex")])


if __name__ == "__main__":
    unittest.main()
