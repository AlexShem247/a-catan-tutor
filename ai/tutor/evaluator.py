import re
from typing import Any, List, Optional, Tuple

from ai.RuleBasedAI import RuleBasedAI
from ai.actions import Action, ActionType, Phase
from ai.simulation.SimGame import make_sim_game_for_player
from ai.simulation.board_sim_utils import find_edge_toward_vertex, get_legal_settlement_vertices, moves_toward_vertex
from ai.tutor.explanations import ActionExplanation, ReasonType, RoadExplanationKind
from ai.tutor.feedback import TutorAssessment, TutorDecisionType, TutorFeedbackExplanation
from ai.tutor.move_quality import (
    initial_road_connection_move_quality,
    initial_road_expansion_move_quality,
    initial_road_flexible_move_quality,
)
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex


class TutorEvaluator:
    _TITLE_BY_DECISION = {
        TutorDecisionType.OPENING_SETTLEMENT: "Opening Settlement",
        TutorDecisionType.OPENING_ROAD: "Opening Road",
        TutorDecisionType.ROBBER: "Robber",
        TutorDecisionType.DISCARD: "Discard",
        TutorDecisionType.TRADE_RESPONSE: "Trade Response",
        TutorDecisionType.TRADE_PARTNER: "Trade Partner",
        TutorDecisionType.YEAR_OF_PLENTY: "Year Of Plenty",
        TutorDecisionType.MONOPOLY: "Monopoly",
        TutorDecisionType.MAIN_TURN: "Main Turn",
    }

    _TIP_BY_DECISION = {
        TutorDecisionType.OPENING_SETTLEMENT: "Prioritise production and resource coverage before smaller extras.",
        TutorDecisionType.OPENING_ROAD: "Aim roads at the strongest follow-up settlement line you can keep open.",
        TutorDecisionType.ROBBER: (
            "Block the tile that matters most to the strongest opponent without hurting yourself."
        ),
        TutorDecisionType.DISCARD: "Keep the cards that preserve your next build and throw away surplus first.",
        TutorDecisionType.TRADE_RESPONSE: "Accept trades only when they advance your plan more than your opponent's.",
        TutorDecisionType.TRADE_PARTNER: "Choose the deal that helps your plan while feeding the safest opponent.",
        TutorDecisionType.YEAR_OF_PLENTY: "Use Year of Plenty to complete your next strong action whenever possible.",
        TutorDecisionType.MONOPOLY: "Call the resource opponents are both holding and likely to need next.",
        TutorDecisionType.MAIN_TURN: "Favour the move that advances your best near-term plan, not just a legal action.",
    }

    def __init__(self, tutor_ai: RuleBasedAI):
        self.tutor_ai = tutor_ai

    def evaluate_main_turn_action(
            self,
            player: Player,
            game: Game,
            phase: Phase,
            dev_played: bool,
            action: Action,
            title: Optional[str] = None,
    ) -> Optional[TutorFeedbackExplanation]:
        if phase == Phase.PRE_ROLL and action.type == ActionType.PLAY_DEV_CARD:
            actual_explanation = self.tutor_ai.explain_pre_roll_dev_choice(player, game, action.payload)
        else:
            actual_explanation = self.tutor_ai.explain_action(player, game, phase, dev_played, action)
        _, best_explanation = self.tutor_ai.next_action_with_explanation(player, game, phase, dev_played)
        feedback = self._feedback_from_explanations(
            TutorDecisionType.MAIN_TURN,
            actual_explanation,
            best_explanation,
            game,
            title=title,
        )
        if feedback is not None and action.type == ActionType.BUILD and isinstance(action.payload, tuple):
            buildable, position = action.payload
            feedback.set_visual_build(buildable, position, player.player_number)
        return feedback

    def evaluate_opening_settlement_choice(
            self,
            player: Player,
            game: Game,
            available_vertices: List[Vertex],
            chosen_vertex: Vertex,
            title: Optional[str] = None,
    ) -> Optional[TutorFeedbackExplanation]:
        if chosen_vertex not in available_vertices:
            return None

        best_vertex, best_explanation = self.tutor_ai.select_initial_settlement_location_with_explanation(
            player,
            game,
            available_vertices,
        )
        if best_explanation is None or best_vertex is None:
            return None

        first_settlement = len(player.settlements) == 0
        vertex_scores = {
            vertex: self.tutor_ai.vertex_utility(vertex, player, game, available_vertices, first_settlement)
            for vertex in available_vertices
        }
        max_score = max(vertex_scores.values(), default=0.0)
        actual_explanation = self._build_initial_settlement_explanation(
            player,
            chosen_vertex,
            vertex_scores.get(chosen_vertex, float("-inf")),
            max_score,
        )

        feedback = self._feedback_from_explanations(
            TutorDecisionType.OPENING_SETTLEMENT,
            actual_explanation,
            best_explanation,
            game,
            title=title,
        )
        if feedback is not None:
            feedback.set_visual_build(Buildable.SETTLEMENT, chosen_vertex, player.player_number)
        return feedback

    def evaluate_opening_road_choice(
            self,
            player: Player,
            game: Game,
            available_edges: List[Edge],
            chosen_edge: Edge,
            title: Optional[str] = None,
    ) -> Optional[TutorFeedbackExplanation]:
        if chosen_edge not in available_edges:
            return None

        best_edge, best_explanation = self.tutor_ai.select_initial_road_location_with_explanation(
            player,
            game,
            available_edges,
        )
        if best_edge is None or best_explanation is None:
            return None

        actual_explanation = self._build_initial_road_choice_explanation(player, game, available_edges, chosen_edge)
        feedback = self._feedback_from_explanations(
            TutorDecisionType.OPENING_ROAD,
            actual_explanation,
            best_explanation,
            game,
            title=title,
        )
        if feedback is not None:
            feedback.set_visual_build(Buildable.ROAD, chosen_edge, player.player_number)
        return feedback

    def evaluate_trade_response_choice(
            self,
            player: Player,
            game: Game,
            opponent: Player,
            selling: ResourceCount,
            buying: ResourceCount,
            accepted: bool,
            counter: Optional[ResourceCount],
            title: Optional[str] = None,
    ) -> Optional[TutorFeedbackExplanation]:
        _, _, best_explanation = self.tutor_ai.respond_to_trade_with_explanation(
            player,
            game,
            opponent,
            selling,
            buying,
        )
        actual_explanation = self.tutor_ai.explain_trade_response_choice(
            player,
            game,
            opponent,
            selling,
            buying,
            accepted,
            counter,
        )
        return self._feedback_from_explanations(
            TutorDecisionType.TRADE_RESPONSE,
            actual_explanation,
            best_explanation,
            game,
            title=title,
        )

    def evaluate_trade_partner_choice(
            self,
            player: Player,
            game: Game,
            selling: ResourceCount,
            buying: ResourceCount,
            available_players: List[Tuple[Player, Optional[ResourceCount]]],
            chosen_player: Player,
            counter: Optional[ResourceCount],
            title: Optional[str] = None,
    ) -> Optional[TutorFeedbackExplanation]:
        _, best_explanation = self.tutor_ai.choose_trade_partner_with_explanation(
            player,
            game,
            selling,
            buying,
            available_players,
        )
        actual_explanation = self.tutor_ai.explain_trade_partner_choice(
            player,
            game,
            selling,
            buying,
            available_players,
            chosen_player,
            counter,
        )
        return self._feedback_from_explanations(
            TutorDecisionType.TRADE_PARTNER,
            actual_explanation,
            best_explanation,
            game,
            title=title,
        )

    def evaluate_discard_choice(
            self,
            player: Player,
            game: Game,
            discard: ResourceCount,
            discard_count: int,
            title: Optional[str] = None,
    ) -> Optional[TutorFeedbackExplanation]:
        _, best_explanation = self.tutor_ai.select_discard_resources_with_explanation(player, game, discard_count)
        actual_explanation = self.tutor_ai.explain_discard_choice(player, game, discard)
        return self._feedback_from_explanations(
            TutorDecisionType.DISCARD,
            actual_explanation,
            best_explanation,
            game,
            title=title,
        )

    def evaluate_robber_choice(
            self,
            player: Player,
            game: Game,
            valid_hexes: List[HexTile],
            chosen_hex: HexTile,
            chosen_player: Optional[Player],
            title: Optional[str] = None,
    ) -> Optional[TutorFeedbackExplanation]:
        _, _, best_explanation = self.tutor_ai.select_robber_target_with_explanation(player, game, valid_hexes)
        actual_explanation = self.tutor_ai.explain_robber_choice(player, game, valid_hexes, chosen_hex, chosen_player)
        return self._feedback_from_explanations(
            TutorDecisionType.ROBBER,
            actual_explanation,
            best_explanation,
            game,
            title=title,
        )

    def evaluate_year_of_plenty_choice(
            self,
            player: Player,
            game: Game,
            selected: ResourceCount,
            title: Optional[str] = None,
    ) -> Optional[TutorFeedbackExplanation]:
        _, best_explanation = self.tutor_ai.select_year_of_plenty_resources_with_explanation(player, game)
        actual_explanation = self.tutor_ai.explain_year_of_plenty_choice(player, game, selected)
        return self._feedback_from_explanations(
            TutorDecisionType.YEAR_OF_PLENTY,
            actual_explanation,
            best_explanation,
            game,
            title=title,
        )

    def evaluate_monopoly_choice(
            self,
            player: Player,
            game: Game,
            resource: Resource,
            title: Optional[str] = None,
    ) -> Optional[TutorFeedbackExplanation]:
        _, best_explanation = self.tutor_ai.select_monopoly_resource_with_explanation(player, game)
        actual_explanation = self.tutor_ai.explain_monopoly_choice(player, game, resource)
        return self._feedback_from_explanations(
            TutorDecisionType.MONOPOLY,
            actual_explanation,
            best_explanation,
            game,
            title=title,
        )

    def _feedback_from_explanations(
            self,
            decision_type: TutorDecisionType,
            actual_explanation: Optional[ActionExplanation],
            best_explanation: Optional[ActionExplanation],
            game: Any,
            title: Optional[str] = None,
    ) -> Optional[TutorFeedbackExplanation]:
        if actual_explanation is None or best_explanation is None:
            return None

        assessment = self._build_assessment(decision_type, actual_explanation, best_explanation)
        feedback = TutorFeedbackExplanation.from_assessment(
            title=title or self._TITLE_BY_DECISION[decision_type],
            assessment=assessment,
            game_state=game,
        )
        if actual_explanation.chosen_action != best_explanation.chosen_action:
            recommended_visual_plan = self._recommended_build_visual_plan(best_explanation)
            if recommended_visual_plan:
                feedback.set_recommended_visual_plan(recommended_visual_plan)
        return feedback

    def _build_assessment(
            self,
            decision_type: TutorDecisionType,
            actual_explanation: ActionExplanation,
            best_explanation: ActionExplanation,
    ) -> TutorAssessment:
        same_choice = actual_explanation.chosen_action == best_explanation.chosen_action
        strengths = self._reason_sentences(actual_explanation, actual_explanation.sorted_reasons_for(), limit=2)
        weaknesses = self._weakness_sentences(actual_explanation, best_explanation, limit=2) if not same_choice else []
        better_move_reasons = self._better_move_reason_sentences(
            actual_explanation,
            best_explanation,
            limit=2,
        ) if not same_choice else []

        positive = strengths[0] if strengths else "It fits a reasonable plan."
        weaknesses = self._distinct_reasons_from_seed(weaknesses, [positive], limit=1)
        better_move_reasons = self._distinct_reasons_from_seed(
            better_move_reasons,
            [positive, *weaknesses],
            limit=1,
        )
        if same_choice:
            judgment = f"{self._strip_period(positive)} and it matched the tutor's preferred move."
            better_move = None
        else:
            negative = weaknesses[0] if weaknesses else "A stronger alternative was available."
            judgment = f"{self._strip_period(positive)}, but {self._lowercase_first(self._strip_period(negative))}."
            better_move = self._move_sentence(best_explanation)

        return TutorAssessment(
            decision_type=decision_type,
            internal_score=actual_explanation.move_quality,
            best_internal_score=best_explanation.move_quality,
            label=actual_explanation.move_quality_label,
            judgment_sentence=judgment,
            your_move=self._move_sentence(actual_explanation),
            better_move=better_move,
            top_strengths=strengths,
            top_weaknesses=weaknesses,
            better_move_reasons=better_move_reasons,
            tip=self._TIP_BY_DECISION[decision_type],
        )

    def _distinct_reasons_from_seed(self, candidates: List[str], existing: List[str], limit: int) -> List[str]:
        selected: List[str] = []
        for candidate in candidates:
            if self._contains_equivalent_reason([*existing, *selected], candidate):
                continue
            selected.append(candidate)
            if len(selected) >= limit:
                break
        return selected

    def _build_initial_settlement_explanation(
            self,
            player: Player,
            vertex: Vertex,
            best_score: float,
            max_score: float,
    ) -> ActionExplanation:
        build_explanation = getattr(self.tutor_ai, "_build_initial_settlement_explanation")
        return build_explanation(player, vertex, best_score, max_score)

    def _build_initial_road_explanation(
            self,
            edge: Edge,
            target_vertex: Optional[Vertex],
            explanation_kind: RoadExplanationKind,
            move_quality: float,
    ) -> ActionExplanation:
        build_explanation = getattr(self.tutor_ai, "_build_initial_road_explanation")
        return build_explanation(edge, target_vertex, explanation_kind, move_quality)

    def _build_initial_road_choice_explanation(
            self,
            player: Player,
            game: Game,
            available_edges: List[Edge],
            chosen_edge: Edge,
    ) -> ActionExplanation:
        if len(player.settlements) + len(player.cities) >= 2:
            return self._build_initial_road_explanation(
                chosen_edge,
                target_vertex=None,
                explanation_kind=RoadExplanationKind.FLEXIBLE,
                move_quality=initial_road_flexible_move_quality(),
            )

        current_settlement = player.settlements[-1]
        legal_vertices = get_legal_settlement_vertices(make_sim_game_for_player(game, player))
        vertex_scores = {
            vertex: self.tutor_ai.vertex_utility(vertex, player, game, legal_vertices, first_settlement=False)
            for vertex in legal_vertices
        }
        max_legal_vertex_utility = max(vertex_scores.values(), default=0.0)

        if len(player.settlements) == 1:
            target_vertices = [
                vertex for vertex in legal_vertices
                if find_edge_toward_vertex(current_settlement, vertex, available_edges) == chosen_edge
            ]
            if target_vertices:
                target_vertex = max(target_vertices, key=vertex_scores.get)
                return self._build_initial_road_explanation(
                    chosen_edge,
                    target_vertex=target_vertex,
                    explanation_kind=RoadExplanationKind.EXPANSION,
                    move_quality=initial_road_expansion_move_quality(
                        vertex_scores[target_vertex],
                        max_legal_vertex_utility,
                    ),
                )
            return self._build_initial_road_explanation(
                chosen_edge,
                target_vertex=None,
                explanation_kind=RoadExplanationKind.FLEXIBLE,
                move_quality=initial_road_flexible_move_quality(),
            )

        connection_edges = [
            edge for edge in available_edges
            if moves_toward_vertex(edge.get_other_vertex(current_settlement), player.settlements[0])
        ]
        if chosen_edge in connection_edges:
            return self._build_initial_road_explanation(
                chosen_edge,
                target_vertex=player.settlements[0],
                explanation_kind=RoadExplanationKind.CONNECTION,
                move_quality=initial_road_connection_move_quality(len(connection_edges)),
            )

        target_vertices = [
            vertex for vertex in legal_vertices
            if find_edge_toward_vertex(current_settlement, vertex, available_edges) == chosen_edge
        ]
        if target_vertices:
            target_vertex = max(target_vertices, key=vertex_scores.get)
            return self._build_initial_road_explanation(
                chosen_edge,
                target_vertex=target_vertex,
                explanation_kind=RoadExplanationKind.EXPANSION,
                move_quality=initial_road_expansion_move_quality(
                    vertex_scores[target_vertex],
                    max_legal_vertex_utility,
                ),
            )

        return self._build_initial_road_explanation(
            chosen_edge,
            target_vertex=None,
            explanation_kind=RoadExplanationKind.FLEXIBLE,
            move_quality=initial_road_flexible_move_quality(),
        )

    def _reason_sentences(
            self,
            explanation: ActionExplanation,
            reasons,
            limit: int,
    ) -> List[str]:
        texts: List[str] = []
        seen = set()
        for reason in reasons:
            text = self._sentence(explanation.describe_reason(reason, detail=True))
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            texts.append(text)
            seen.add(key)
            if len(texts) >= limit:
                break
        return texts

    def _weakness_sentences(
            self,
            actual_explanation: ActionExplanation,
            best_explanation: ActionExplanation,
            limit: int,
    ) -> List[str]:
        weaknesses = self._reason_sentences(
            actual_explanation,
            actual_explanation.sorted_reasons_against(),
            limit=limit,
        )
        actual_labels = {reason.label for reason in actual_explanation.sorted_reasons_for()}
        for reason in best_explanation.sorted_reasons_for():
            if len(weaknesses) >= limit:
                break
            if reason.label in actual_labels:
                continue
            weakness = self._missed_reason_sentence(best_explanation, reason)
            if weakness and not self._contains_equivalent_reason(weaknesses, weakness):
                weaknesses.append(weakness)
        return weaknesses

    def _better_move_reason_sentences(
            self,
            actual_explanation: ActionExplanation,
            best_explanation: ActionExplanation,
            limit: int,
    ) -> List[str]:
        actual_labels = {reason.label for reason in actual_explanation.sorted_reasons_for()}
        reasons = []
        for reason in best_explanation.sorted_reasons_for():
            if reason.label in actual_labels:
                continue
            text = self._sentence(best_explanation.describe_reason(reason, detail=True))
            if text and not self._contains_equivalent_reason(reasons, text):
                reasons.append(text)
            if len(reasons) >= limit:
                break
        if not reasons:
            reasons = self._reason_sentences(best_explanation, best_explanation.sorted_reasons_for(), limit=limit)
        return reasons[:limit]

    def _move_sentence(self, explanation: ActionExplanation) -> str:
        template = explanation.metadata.get("template") or explanation.chosen_candidate.metadata.get("template")
        _, sentence = explanation.generate_text_concise()
        if template is not None and sentence:
            return self._sentence(sentence)
        return self._sentence(explanation.describe_action(short=False))

    @staticmethod
    def _recommended_build_visual_plan(explanation: ActionExplanation) -> List[Tuple[Buildable, object]]:
        visual_plan = explanation.get_visual_build_plan()
        allowed_buildables = {Buildable.ROAD, Buildable.SETTLEMENT, Buildable.CITY}
        return [
            (buildable, position)
            for buildable, position in visual_plan
            if buildable in allowed_buildables
        ]

    def _missed_reason_sentence(self, explanation: ActionExplanation, reason) -> str:
        if getattr(reason, "type", None) == ReasonType.HEURISTIC_CHOICE:
            plan_phrase = explanation.strongest_plan_focus_phrase()
            if plan_phrase:
                return f"You miss out on {plan_phrase}, which is currently the strongest plan."
        reason_text = explanation.describe_reason(reason, detail=True)
        text = TutorEvaluator._strip_period(reason_text)
        if not text:
            return ""
        if text.lower().startswith("it "):
            return f"You miss out because {text.lower()}."
        return f"You miss out on a line that {TutorEvaluator._lowercase_first(text)}."

    @classmethod
    def _contains_equivalent_reason(cls, existing_reasons: List[str], candidate: str) -> bool:
        candidate_key = cls._reason_core_text(candidate)
        if not candidate_key:
            return False
        return any(cls._reason_core_text(reason) == candidate_key for reason in existing_reasons)

    @classmethod
    def _reason_core_text(cls, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", "", text)
        text = " ".join(text.split()).strip().lower()
        for prefix in (
                "you miss out because ",
                "you miss out on a line that ",
                "you miss out on ",
        ):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        suffix = ", which is currently the strongest plan"
        if text.endswith(suffix):
            text = text[:-len(suffix)]
        return text.rstrip(".!?")

    @staticmethod
    def _sentence(text: str) -> str:
        text = re.sub(r"<[^>]+>", "", text)
        text = " ".join(text.split()).strip()
        if not text:
            return ""
        if text[-1] not in ".!?":
            text += "."
        return text[0].upper() + text[1:]

    @staticmethod
    def _strip_period(text: str) -> str:
        return text.rstrip().rstrip(".!?")

    @staticmethod
    def _lowercase_first(text: str) -> str:
        if not text:
            return ""
        return text[0].lower() + text[1:]
