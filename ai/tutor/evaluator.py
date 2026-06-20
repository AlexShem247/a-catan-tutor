import re
from typing import Any, Callable, TypeVar

from ai.actions import Action, ActionType, Phase, actions_equivalent
from ai.rule_based_ai.RuleBasedAI import RuleBasedAI
from ai.simulation.board_sim_utils import find_edge_toward_vertex, get_legal_settlement_vertices, moves_toward_vertex
from ai.simulation.SimGame import make_sim_game_for_player
from ai.tutor.explanations import ActionExplanation, ExplanationTemplate, ReasonLabel, ReasonType, RoadExplanationKind
from ai.tutor.feedback import TutorAssessment, TutorDecisionType, TutorFeedbackExplanation
from ai.tutor.move_quality import (clamp_move_quality, initial_road_connection_move_quality,
                                   initial_road_expansion_move_quality, initial_road_flexible_move_quality,
                                   move_quality_label)
from config.move_quality_constants import MOVE_QUALITY_GOOD_THRESHOLD, MOVE_QUALITY_OKAY_THRESHOLD
from config.performance_constants import EPSILON
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex

T = TypeVar("T")


class TutorEvaluator:
    _DEV_CARD_STRATEGIC_LABELS = {
        ReasonLabel.HIDDEN_DEV_VALUE,
        ReasonLabel.DEV_KNIGHT_PRESSURE,
        ReasonLabel.DEV_PROGRESS_FLEXIBILITY,
    }
    _GENERIC_QUICK_LABELS = {
        ReasonLabel.QUICK_GENERIC,
        ReasonLabel.QUICK_PLANNED_DEV_BUY,
        ReasonLabel.QUICK_PLANNED_FOLLOW_UP,
    }

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
            "Block the tile that matters most to the strongest opponent without hurting yourself."),
        TutorDecisionType.DISCARD: "Keep the cards that preserve your next build and throw away surplus first.",
        TutorDecisionType.TRADE_RESPONSE: "Accept trades only when they advance your plan more than your opponent's.",
        TutorDecisionType.TRADE_PARTNER: "Choose the deal that helps your plan while feeding the safest opponent.",
        TutorDecisionType.YEAR_OF_PLENTY: "Use Year of Plenty to complete your next strong action whenever possible.",
        TutorDecisionType.MONOPOLY: "Call the resource opponents are both holding and likely to need next.",
        TutorDecisionType.MAIN_TURN: "Favour the move that advances your best near-term plan, not just a legal action.",
    }

    def __init__(
        self,
        tutor_ai: RuleBasedAI,
        live_rng_state_getter: Callable[[], tuple[Any, ...]] | None = None,
    ):
        self.tutor_ai = tutor_ai
        self.live_rng_state_getter = live_rng_state_getter

    def _run_tutor_preview(self, callback: Callable[[], T]) -> T:
        """Run a tutor preview without mutating tutor state."""
        snapshot = self.tutor_ai.snapshot_state()
        try:
            if self.live_rng_state_getter is not None:
                self.tutor_ai.rng.setstate(self.live_rng_state_getter())
            return callback()
        finally:
            self.tutor_ai.restore_state(snapshot)

    def _best_explanation_without_mutating_trade_state(
        self,
        player: Player,
        game: Game,
        phase: Phase,
        dev_played: bool,
    ) -> ActionExplanation:
        """Get the tutor's preferred explanation without mutating trade state."""
        return self._run_tutor_preview(
            lambda: self.tutor_ai.next_action_with_explanation(player, game, phase, dev_played)[1])

    def evaluate_main_turn_action(
        self,
        player: Player,
        game: Game,
        phase: Phase,
        dev_played: bool,
        action: Action,
        title: str | None = None,
    ) -> TutorFeedbackExplanation | None:
        """Evaluate a main-turn action against the tutor's recommendation."""
        if phase == Phase.PRE_ROLL and action.type == ActionType.PLAY_DEV_CARD:
            actual_explanation = self.tutor_ai.explain_pre_roll_dev_choice(player, game, action.payload)
        else:
            actual_explanation = self.tutor_ai.explain_action(player, game, phase, dev_played, action)
        best_explanation = self._best_explanation_without_mutating_trade_state(
            player,
            game,
            phase,
            dev_played,
        )
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
        available_vertices: list[Vertex],
        chosen_vertex: Vertex,
        title: str | None = None,
    ) -> TutorFeedbackExplanation | None:
        """Evaluate an opening settlement choice against the tutor's recommendation."""
        if chosen_vertex not in available_vertices:
            return None

        best_vertex, best_explanation = self._run_tutor_preview(
            lambda: self.tutor_ai.select_initial_settlement_location_with_explanation(
                player,
                game,
                available_vertices,
            ))
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
        available_edges: list[Edge],
        chosen_edge: Edge,
        title: str | None = None,
    ) -> TutorFeedbackExplanation | None:
        """Evaluate an opening road choice against the tutor's recommendation."""
        if chosen_edge not in available_edges:
            return None

        best_edge, best_explanation = self._run_tutor_preview(
            lambda: self.tutor_ai.select_initial_road_location_with_explanation(
                player,
                game,
                available_edges,
            ))
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
        counter: ResourceCount | None,
        title: str | None = None,
    ) -> TutorFeedbackExplanation | None:
        """Evaluate a trade-response choice against the tutor's recommendation."""
        _, _, best_explanation = self._run_tutor_preview(lambda: self.tutor_ai.respond_to_trade_with_explanation(
            player,
            game,
            opponent,
            selling,
            buying,
        ))
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
        available_players: list[tuple[Player, ResourceCount | None]],
        chosen_player: Player,
        counter: ResourceCount | None,
        title: str | None = None,
    ) -> TutorFeedbackExplanation | None:
        """Evaluate a trade-partner choice against the tutor's recommendation."""
        _, best_explanation = self._run_tutor_preview(lambda: self.tutor_ai.choose_trade_partner_with_explanation(
            player,
            game,
            selling,
            buying,
            available_players,
        ))
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
        title: str | None = None,
    ) -> TutorFeedbackExplanation | None:
        """Evaluate a discard choice against the tutor's recommendation."""
        _, best_explanation = self._run_tutor_preview(
            lambda: self.tutor_ai.select_discard_resources_with_explanation(player, game, discard_count))
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
        valid_hexes: list[HexTile],
        chosen_hex: HexTile,
        chosen_player: Player | None,
        title: str | None = None,
    ) -> TutorFeedbackExplanation | None:
        """Evaluate a robber choice against the tutor's recommendation."""
        _, _, best_explanation = self._run_tutor_preview(
            lambda: self.tutor_ai.select_robber_target_with_explanation(player, game, valid_hexes))
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
        title: str | None = None,
    ) -> TutorFeedbackExplanation | None:
        """Evaluate a Year of Plenty choice against the tutor's recommendation."""
        _, best_explanation = self._run_tutor_preview(
            lambda: self.tutor_ai.select_year_of_plenty_resources_with_explanation(player, game))
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
        title: str | None = None,
    ) -> TutorFeedbackExplanation | None:
        """Evaluate a Monopoly choice against the tutor's recommendation."""
        _, best_explanation = self._run_tutor_preview(
            lambda: self.tutor_ai.select_monopoly_resource_with_explanation(player, game))
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
        actual_explanation: ActionExplanation | None,
        best_explanation: ActionExplanation | None,
        game: Any,
        title: str | None = None,
    ) -> TutorFeedbackExplanation | None:
        """Build tutor feedback from the actual and recommended explanations."""
        if actual_explanation is None or best_explanation is None:
            return None

        assessment = self._build_assessment(decision_type, actual_explanation, best_explanation)
        feedback = TutorFeedbackExplanation.from_assessment(
            title=title or self._TITLE_BY_DECISION[decision_type],
            assessment=assessment,
            game_state=game,
        )
        if not actions_equivalent(actual_explanation.chosen_action, best_explanation.chosen_action):
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
        """Build a tutor assessment from the compared explanations."""
        same_choice = actions_equivalent(actual_explanation.chosen_action, best_explanation.chosen_action)
        display_score, display_best_score = self._display_scores_for_feedback(
            actual_explanation,
            best_explanation,
            same_choice,
        )
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
            better_move_context = ""
        else:
            negative = weaknesses[0] if weaknesses else "A stronger alternative was available."
            judgment = f"{self._strip_period(positive)}, but {self._lowercase_first(self._strip_period(negative))}."
            better_move = self._move_sentence(best_explanation)
            better_move_context = self._move_context(best_explanation)

        return TutorAssessment(
            decision_type=decision_type,
            internal_score=display_score,
            best_internal_score=display_best_score,
            label=move_quality_label(display_score),
            judgment_sentence=judgment,
            your_move=self._move_sentence(actual_explanation),
            move_context=self._move_context(actual_explanation),
            better_move=better_move,
            better_move_context=better_move_context,
            top_strengths=strengths,
            top_weaknesses=weaknesses,
            better_move_reasons=better_move_reasons,
            tip=self._TIP_BY_DECISION[decision_type],
        )

    @staticmethod
    def _display_scores_for_feedback(
        actual_explanation: ActionExplanation,
        best_explanation: ActionExplanation,
        same_choice: bool,
    ) -> tuple[float, float]:
        """Prepare display scores for tutor feedback."""
        actual_score = actual_explanation.move_quality
        best_score = best_explanation.move_quality

        if not same_choice:
            return actual_score, best_score

        chosen_action = actual_explanation.chosen_action
        chosen_candidate = actual_explanation.chosen_candidate

        if (chosen_action.type == ActionType.END_TURN
                and float(getattr(chosen_candidate, "etw_before", 0.0) or 0.0) <= EPSILON):
            return 1.0, 1.0

        floor_score = MOVE_QUALITY_OKAY_THRESHOLD
        if chosen_action.type == ActionType.BUILD:
            payload = chosen_action.payload
            buildable = payload[0] if isinstance(payload, tuple) and payload else None
            if buildable in {Buildable.SETTLEMENT, Buildable.CITY}:
                floor_score = 0.4

        adjusted_score = clamp_move_quality(max(actual_score, floor_score))
        adjusted_best_score = clamp_move_quality(max(best_score, adjusted_score))
        if chosen_action.type == ActionType.END_TURN:
            adjusted_score = min(adjusted_score, MOVE_QUALITY_GOOD_THRESHOLD)
            adjusted_best_score = min(max(adjusted_best_score, adjusted_score), MOVE_QUALITY_GOOD_THRESHOLD)
        return adjusted_score, adjusted_best_score

    def _distinct_reasons_from_seed(self, candidates: list[str], existing: list[str], limit: int) -> list[str]:
        """Collect distinct reasons while preserving the starting selection."""
        selected: list[str] = []
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
        """Build an explanation for an opening settlement choice."""
        return self.tutor_ai.opening_policy.build_initial_settlement_explanation(player, vertex, best_score, max_score)

    def _build_initial_road_explanation(
        self,
        edge: Edge,
        target_vertex: Vertex | None,
        explanation_kind: RoadExplanationKind,
        move_quality: float,
    ) -> ActionExplanation:
        """Build an explanation for an opening road option."""
        return self.tutor_ai.opening_policy.build_initial_road_explanation(edge, target_vertex, explanation_kind,
                                                                           move_quality)

    def _build_initial_road_choice_explanation(
        self,
        player: Player,
        game: Game,
        available_edges: list[Edge],
        chosen_edge: Edge,
    ) -> ActionExplanation:
        """Build an explanation for the chosen opening road."""
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
    ) -> list[str]:
        """Build the positive reason sentences for an explanation."""
        texts: list[str] = []
        seen = set()
        for reason in self._prioritised_reasons(explanation, reasons):
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
    ) -> list[str]:
        """Build the weakness sentences for an explanation."""
        weaknesses = self._reason_sentences(
            actual_explanation,
            actual_explanation.sorted_reasons_against(),
            limit=limit,
        )
        actual_labels = {reason.label for reason in actual_explanation.sorted_reasons_for()}
        for reason in self._prioritised_reasons(best_explanation, best_explanation.sorted_reasons_for()):
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
    ) -> list[str]:
        """Build the better-move reason sentences for an explanation."""
        actual_labels = {reason.label for reason in actual_explanation.sorted_reasons_for()}
        reasons = []
        for reason in self._prioritised_reasons(best_explanation, best_explanation.sorted_reasons_for()):
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

    def _prioritised_reasons(self, explanation: ActionExplanation, reasons) -> list:
        """Prefer strategic development-card reasons over generic quickness in feedback."""
        ordered = list(reasons)
        if explanation.chosen_action.type != ActionType.BUY_DEV_CARD:
            return ordered

        has_dev_strategy = any(reason.label in self._DEV_CARD_STRATEGIC_LABELS for reason in ordered)
        if not has_dev_strategy:
            return ordered

        ordered = [
            reason for reason in ordered
            if reason.label not in self._GENERIC_QUICK_LABELS and reason.type != ReasonType.QUICK_TO_EXECUTE
        ]

        def priority(reason) -> tuple[int, float]:
            if reason.label in self._DEV_CARD_STRATEGIC_LABELS:
                return 0, -float(getattr(reason, "value", 0.0) or 0.0)
            return 1, -float(getattr(reason, "value", 0.0) or 0.0)

        return sorted(ordered, key=priority)

    def _move_sentence(self, explanation: ActionExplanation) -> str:
        """Describe the move referenced by an explanation."""
        template = explanation.metadata.get("template") or explanation.chosen_candidate.metadata.get("template")
        _, sentence = explanation.generate_text_concise()
        if template is not None and sentence:
            return self._sentence(sentence)
        return self._sentence(explanation.describe_action(short=False))

    def _move_context(self, explanation: ActionExplanation) -> str:
        """Describe the resource context for an explained move."""
        template = explanation.metadata.get("template") or explanation.chosen_candidate.metadata.get("template")
        metadata = explanation.chosen_candidate.metadata
        action = explanation.chosen_action

        if template == ExplanationTemplate.TRADE_PARTNER:
            exchange = self._trade_exchange_text(metadata.get("payment"), metadata.get("buying"))
            return f"Exchange: {exchange}" if exchange else ""

        if template == ExplanationTemplate.TRADE_RESPONSE:
            offered = metadata.get("selling_to_us")
            requested = metadata.get("payment")
            decision = metadata.get("decision")
            if decision == "counter":
                exchange = self._trade_exchange_text(metadata.get("counter_payment"), offered)
                return f"Counteroffer: {exchange}" if exchange else ""
            exchange = self._trade_exchange_text(requested, offered)
            return f"Offer: {exchange}" if exchange else ""

        if template == ExplanationTemplate.DISCARD_RESOURCES:
            discard_text = self._resource_count_text(metadata.get("discard_resources", {}))
            return f"Discarded: {discard_text}" if discard_text else ""

        if template == ExplanationTemplate.YEAR_OF_PLENTY_RESOURCES:
            selected_text = self._resource_count_text(metadata.get("selected_resources", {}))
            return f"Picked: {selected_text}" if selected_text else ""

        if template == ExplanationTemplate.MONOPOLY_RESOURCE:
            selected_resource = metadata.get("selected_resource")
            if selected_resource is None:
                return ""
            return f"Called: {self._resource_name(selected_resource)}"

        if action.type in {ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER}:
            payload = action.payload
            if isinstance(payload, tuple) and len(payload) == 2:
                exchange = self._trade_exchange_text(payload[0], payload[1])
                return f"Exchange: {exchange}" if exchange else ""

        return ""

    @staticmethod
    def _resource_name(resource: Any) -> str:
        """Return the display name for a resource."""
        return getattr(resource, "name", str(resource)).replace("_", " ").title()

    def _resource_count_text(self, resources: Any) -> str:
        """Format a resource bundle for display."""
        if not resources:
            return ""
        parts: list[str] = []
        for resource, amount in resources.items():
            if not amount or amount <= 0:
                continue
            parts.append(f"{amount} {self._resource_name(resource)}")
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        if len(parts) == 2:
            return f"{parts[0]} and {parts[1]}"
        return ", ".join(parts[:-1]) + f", and {parts[-1]}"

    def _trade_exchange_text(self, payment: Any, buying: Any) -> str:
        """Format a trade exchange for display."""
        pay_text = self._resource_count_text(payment)
        receive_text = self._resource_count_text(buying)
        if pay_text and receive_text:
            return f"give {pay_text} for {receive_text}"
        if receive_text:
            return f"receive {receive_text}"
        if pay_text:
            return f"give {pay_text}"
        return ""

    @staticmethod
    def _recommended_build_visual_plan(explanation: ActionExplanation) -> list[tuple[Buildable, object]]:
        """Build the recommended visual plan for an explanation."""
        visual_plan = explanation.get_visual_build_plan()
        allowed_buildables = {Buildable.ROAD, Buildable.SETTLEMENT, Buildable.CITY}
        return [(buildable, position) for buildable, position in visual_plan if buildable in allowed_buildables]

    def _missed_reason_sentence(self, explanation: ActionExplanation, reason) -> str:
        """Build a sentence describing a missed reason."""
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
        return f"You miss out because {TutorEvaluator._lowercase_first(text)}."

    @classmethod
    def _contains_equivalent_reason(cls, existing_reasons: list[str], candidate: str) -> bool:
        """Check whether an equivalent reason is already present."""
        candidate_key = cls._reason_core_text(candidate)
        if not candidate_key:
            return False
        return any(cls._reason_core_text(reason) == candidate_key for reason in existing_reasons)

    @classmethod
    def _reason_core_text(cls, text: str) -> str:
        """Extract the canonical comparison text for a reason."""
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
        """Normalise text into a display sentence."""
        text = re.sub(r"<[^>]+>", "", text)
        text = " ".join(text.split()).strip()
        if not text:
            return ""
        if text[-1] not in ".!?":
            text += "."
        return text[0].upper() + text[1:]

    @staticmethod
    def _strip_period(text: str) -> str:
        """Strip trailing sentence punctuation from text."""
        return text.rstrip().rstrip(".!?")

    @staticmethod
    def _lowercase_first(text: str) -> str:
        """Lowercase the first character of the text."""
        if not text:
            return ""
        return text[0].lower() + text[1:]
