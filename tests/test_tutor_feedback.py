import unittest
from random import Random
from types import SimpleNamespace

from ai.rule_based_ai.RuleBasedAI import RuleBasedAI
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

        self.assertEqual(assessment.label, "Okay")
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

    def test_matching_city_build_is_never_scored_as_poor(self):
        explanation = self._build_explanation(
            Action(ActionType.BUILD, (Buildable.CITY, None)),
            [Reason(ReasonType.FASTEST_PROGRESS, ReasonLabel.PLAN_CITY_VALUE, 1.0)],
            [],
            move_quality=0.0,
        )

        assessment = self.evaluator._build_assessment(TutorDecisionType.MAIN_TURN, explanation, explanation)

        self.assertEqual(assessment.internal_score, 0.4)
        self.assertEqual(assessment.best_internal_score, 0.4)
        self.assertEqual(assessment.label, "Okay")

    def test_matching_choice_is_at_least_okay(self):
        explanation = self._build_explanation(
            Action(ActionType.BUY_DEV_CARD),
            [Reason(ReasonType.HIDDEN_VALUE, ReasonLabel.HIDDEN_DEV_VALUE, 1.0)],
            [],
            move_quality=0.0,
        )

        assessment = self.evaluator._build_assessment(TutorDecisionType.MAIN_TURN, explanation, explanation)

        self.assertEqual(assessment.internal_score, 0.38)
        self.assertEqual(assessment.best_internal_score, 0.38)
        self.assertEqual(assessment.label, "Okay")

    def test_matching_winning_end_turn_scores_as_excellent(self):
        candidate = CandidateExplanation(
            action=Action(ActionType.END_TURN),
            full_plan=[Action(ActionType.END_TURN)],
            etw_before=0.0,
            etw_after=0.0,
            etw_delta=0.0,
            reasons_for=[],
            reasons_against=[],
        )
        explanation = ActionExplanation(
            chosen_action=Action(ActionType.END_TURN),
            chosen_candidate=candidate,
            move_quality=0.0,
        )

        assessment = self.evaluator._build_assessment(TutorDecisionType.MAIN_TURN, explanation, explanation)

        self.assertEqual(assessment.internal_score, 1.0)
        self.assertEqual(assessment.best_internal_score, 1.0)
        self.assertEqual(assessment.label, "Excellent")

    def test_matching_non_winning_end_turn_is_capped_at_good(self):
        candidate = CandidateExplanation(
            action=Action(ActionType.END_TURN),
            full_plan=[Action(ActionType.END_TURN)],
            etw_before=4.0,
            etw_after=4.0,
            etw_delta=0.0,
            reasons_for=[],
            reasons_against=[],
        )
        explanation = ActionExplanation(
            chosen_action=Action(ActionType.END_TURN),
            chosen_candidate=candidate,
            move_quality=0.95,
        )

        assessment = self.evaluator._build_assessment(TutorDecisionType.MAIN_TURN, explanation, explanation)

        self.assertEqual(assessment.internal_score, 0.62)
        self.assertEqual(assessment.best_internal_score, 0.62)
        self.assertEqual(assessment.label, "Good")

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

    def test_heuristic_feedback_uses_specific_best_plan_action(self):
        actual = self._build_explanation(
            Action(ActionType.BUILD, (Buildable.ROAD, None)),
            [Reason(ReasonType.ENABLES_EXPANSION, ReasonLabel.PLAN_ROAD_VALUE, 1.0)],
            [],
            move_quality=0.4,
        )
        best_candidate = CandidateExplanation(
            action=Action(ActionType.END_TURN),
            full_plan=[Action(ActionType.END_TURN)],
            next_plan=[Action(ActionType.BUILD, (Buildable.SETTLEMENT, None))],
            reasons_for=[Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.QUICK_GENERIC, 1.0)],
            reasons_against=[],
        )
        best = ActionExplanation(
            chosen_action=Action(ActionType.END_TURN),
            chosen_candidate=best_candidate,
            move_quality=0.9,
        )

        assessment = self.evaluator._build_assessment(TutorDecisionType.MAIN_TURN, actual, best)

        self.assertIn(
            "You miss out on saving resources for building a settlement, which is currently the strongest plan.",
            assessment.top_weaknesses,
        )
        self.assertIn("It supports saving resources for building a settlement.", assessment.better_move_reasons)

    def test_detailed_feedback_dedupes_wrapped_reason_variants(self):
        assessment = TutorAssessment(
            decision_type=TutorDecisionType.MAIN_TURN,
            internal_score=0.2,
            best_internal_score=0.8,
            label="Poor",
            judgment_sentence="A stronger line was available.",
            your_move="Build a road.",
            better_move="End the turn.",
            top_strengths=[],
            top_weaknesses=["You miss out because it opens up future expansion."],
            better_move_reasons=["It opens up future expansion."],
            tip="Keep the next plan step in view.",
        )

        detailed_html = assessment.detailed_html()

        self.assertEqual(detailed_html.count("opens up future expansion"), 1)

    def test_assessment_keeps_distinct_positive_and_weakness(self):
        actual = self._build_explanation(
            Action(ActionType.BUILD, (Buildable.ROAD, None)),
            [Reason(ReasonType.ENABLES_EXPANSION, ReasonLabel.PLAN_ROAD_VALUE, 1.0)],
            [],
            move_quality=0.4,
        )
        best_candidate = CandidateExplanation(
            action=Action(ActionType.END_TURN),
            full_plan=[Action(ActionType.END_TURN)],
            next_plan=[Action(ActionType.BUILD, (Buildable.CITY, None))],
            reasons_for=[
                Reason(ReasonType.ENABLES_EXPANSION, ReasonLabel.PLAN_ROAD_VALUE, 1.0),
                Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.QUICK_GENERIC, 1.0),
            ],
            reasons_against=[],
        )
        best = ActionExplanation(
            chosen_action=Action(ActionType.END_TURN),
            chosen_candidate=best_candidate,
            move_quality=0.9,
        )

        assessment = self.evaluator._build_assessment(TutorDecisionType.MAIN_TURN, actual, best)
        detailed_html = assessment.detailed_html()

        self.assertEqual(assessment.top_strengths, ["It opens up future expansion."])
        self.assertEqual(
            assessment.top_weaknesses,
            ["You miss out on saving resources for upgrading to a city, which is currently the strongest plan."],
        )
        self.assertIn("It opens up future expansion", assessment.judgment_sentence)
        self.assertIn("saving resources for upgrading to a city", assessment.judgment_sentence)
        self.assertEqual(detailed_html.count("opens up future expansion"), 1)
        self.assertEqual(detailed_html.count("saving resources for upgrading to a city"), 1)


if __name__ == "__main__":
    unittest.main()
