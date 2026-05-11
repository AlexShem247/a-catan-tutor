from dataclasses import dataclass
from random import Random
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple

from ai.AI import AI
from ai.RandomAI import RandomAI
from ai.simulation.EtwEstimator import EtwEstimator
from ai.simulation.EtwEstimator import EtwTradeStateSnapshot
from ai.simulation.SimGame import make_sim_game_for_player
from ai.simulation.SimPlayerState import SimPlayerState, dice_probability
from ai.utils.action_utils import play_development_card_action
from ai.actions import Phase, ActionType, Action
from ai.simulation.board_sim_utils import (
    find_edge_toward_vertex, find_edge_toward_vertex_from_any, find_gap_connection,
    get_legal_settlement_vertices, get_opponents, get_reachable_vertices, moves_toward_vertex,
    score_hex_for_opponent,
)
from ai.tutor.move_quality import (
    discard_move_quality,
    initial_road_connection_move_quality,
    initial_road_expansion_move_quality,
    initial_road_flexible_move_quality,
    initial_settlement_move_quality,
    monopoly_move_quality,
    robber_move_quality,
    strategic_turn_move_quality,
    trade_partner_move_quality,
    year_of_plenty_move_quality,
)
from ai.tutor.explanations import (
    ActionExplanation, AssumptionCode, CandidateExplanation, ExplanationTemplate,
    RoadExplanationKind, Reason, ReasonLabel, ReasonType,
)
from ai.utils.resource_utils import calc_step_resources
from ai.utils.trade_utils import respond_to_trade_batna, select_best_trade_partner
from config.settings import AI_DIFFICULTY_STRATEGIC_MOVE_PROBABILITIES, load_effective_settings
from config.StrategyWeights import StrategyWeights
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex


def use_strategy_weights(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.strategy_weights.applied():
            return method(self, *args, **kwargs)
    return wrapper


@dataclass(frozen=True)
class RuleBasedAIDecisionConfig:
    use_etw_planning: bool = True
    use_opponent_interference: bool = True
    use_time_discount: bool = True
    use_player_trading: bool = True
    use_development_cards: bool = True

    @classmethod
    def full_system(cls) -> "RuleBasedAIDecisionConfig":
        return cls()

    @classmethod
    def no_etw_planning(cls) -> "RuleBasedAIDecisionConfig":
        return cls(use_etw_planning=False)

    @classmethod
    def single_step_etw_rollout(cls) -> "RuleBasedAIDecisionConfig":
        """Keep ETW scoring, but disable multi-step candidate plans."""
        return cls(use_etw_planning=False)

    @classmethod
    def no_opponent_interference(cls) -> "RuleBasedAIDecisionConfig":
        return cls(use_opponent_interference=False)

    @classmethod
    def no_time_discount(cls) -> "RuleBasedAIDecisionConfig":
        return cls(use_time_discount=False)

    @classmethod
    def no_player_trading(cls) -> "RuleBasedAIDecisionConfig":
        return cls(use_player_trading=False)

    @classmethod
    def no_development_cards(cls) -> "RuleBasedAIDecisionConfig":
        return cls(use_development_cards=False)


@dataclass(frozen=True)
class RuleBasedAIStateSnapshot:
    rng_state: Any
    trade_state: EtwTradeStateSnapshot


class RuleBasedAI(AI):
    def __init__(
            self,
            rng: Random,
            strategy_weights: Optional[StrategyWeights] = None,
            decision_config: Optional[RuleBasedAIDecisionConfig] = None):
        super().__init__(rng)
        self.strategy_weights = strategy_weights or StrategyWeights()
        self.decision_config = decision_config or RuleBasedAIDecisionConfig()
        self.etw_estimator = EtwEstimator()
        self.random_ai = RandomAI(rng)

    def new_turn(self):
        self.etw_estimator.new_turn()

    def snapshot_state(self) -> RuleBasedAIStateSnapshot:
        return RuleBasedAIStateSnapshot(
            rng_state=self.rng.getstate(),
            trade_state=self.etw_estimator.snapshot_trade_state(),
        )

    def restore_state(self, snapshot: RuleBasedAIStateSnapshot) -> None:
        self.rng.setstate(snapshot.rng_state)
        self.etw_estimator.restore_trade_state(snapshot.trade_state)

    def _use_strategic_move(self) -> bool:
        settings = load_effective_settings()
        difficulty = str(settings.get("ai_difficulty", "medium")).lower()
        strategic_move_probability = AI_DIFFICULTY_STRATEGIC_MOVE_PROBABILITIES.get(
            difficulty,
            AI_DIFFICULTY_STRATEGIC_MOVE_PROBABILITIES["medium"],
        )
        return self.rng.random() < strategic_move_probability

    def _build_random_action_explanation(self, action: Action, phase: Phase) -> ActionExplanation:
        candidate = CandidateExplanation(
            action=action,
            full_plan=[action],
            reasons_for=[
                Reason(
                    ReasonType.HEURISTIC_CHOICE,
                    ReasonLabel.QUICK_GENERIC,
                    0.0,
                )
            ],
            metadata={"phase": phase.name.lower(), "selection_mode": "random"},
        )
        return ActionExplanation(
            chosen_action=action,
            chosen_candidate=candidate,
            alternatives=[],
            move_quality=0.0,
            assumptions=[],
            metadata={"phase": phase.name.lower(), "selection_mode": "random"},
        )

    def _planner_kwargs(self, ignore_opponents: bool = False) -> Dict[str, object]:
        return {
            "include_player_trades": self.decision_config.use_player_trading,
            "ignore_opponents": ignore_opponents or not self.decision_config.use_opponent_interference,
            "use_time_discount": self.decision_config.use_time_discount,
            "allow_development_cards": self.decision_config.use_development_cards,
            "use_planning": self.decision_config.use_etw_planning,
        }

    def _etw_kwargs(self, include_player_trades: bool = True) -> Dict[str, object]:
        return {
            "include_player_trades": include_player_trades,
            "allow_development_cards": self.decision_config.use_development_cards,
            "use_planning": self.decision_config.use_etw_planning,
        }

    def _trade_risk_kwargs(self) -> Dict[str, float]:
        if self.decision_config.use_opponent_interference:
            return {}
        return {
            "lambda_leader": float("inf"),
            "lambda_base": float("inf"),
            "leader_penalty": 0.0,
        }

    @use_strategy_weights
    def select_initial_settlement_location(
            self, player: Player, game: Game, available_vertices: List[Vertex]) -> Optional[Vertex]:
        """Return the best initial settlement vertex based on utility evaluation."""
        vertex, _ = self.select_initial_settlement_location_with_explanation(player, game, available_vertices)
        return vertex

    @use_strategy_weights
    def select_initial_road_location(
            self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
        """Return the best initial road edge connecting settlements or toward high-utility vertices."""
        edge, _ = self.select_initial_road_location_with_explanation(player, game, available_edges)
        return edge

    @use_strategy_weights
    def select_initial_settlement_location_with_explanation(
            self, player: Player, game: Game,
            available_vertices: List[Vertex]) -> Tuple[Optional[Vertex], Optional[ActionExplanation]]:
        """Return the best initial settlement vertex together with an explanation."""
        if not available_vertices:
            return None, None
        if not self._use_strategic_move():
            vertex = self.random_ai.select_initial_settlement_location(player, game, available_vertices)
            if vertex is None:
                return None, None
            return vertex, self.explain_initial_settlement_choice(player, game, available_vertices, vertex)

        first_settlement = len(player.settlements) == 0
        scored_vertices = sorted(
            [
                (
                    vertex,
                    self.vertex_utility(
                        vertex,
                        player,
                        game,
                        available_vertices,
                        first_settlement,
                        use_opponent_interference=self.decision_config.use_opponent_interference,
                    ),
                )
                for vertex in available_vertices
            ],
            key=lambda item: item[1],
            reverse=True,
        )
        best_vertex, best_score = scored_vertices[0]
        max_score = scored_vertices[0][1]

        explanation = self._build_initial_settlement_explanation(player, best_vertex, best_score, max_score)
        return best_vertex, explanation

    @use_strategy_weights
    def explain_initial_settlement_choice(
            self, player: Player, game: Game,
            available_vertices: List[Vertex], chosen_vertex: Vertex) -> ActionExplanation:
        first_settlement = len(player.settlements) == 0
        vertex_scores = {
            vertex: self.vertex_utility(
                vertex,
                player,
                game,
                available_vertices,
                first_settlement,
                use_opponent_interference=self.decision_config.use_opponent_interference,
            )
            for vertex in available_vertices
        }
        chosen_score = vertex_scores.get(chosen_vertex, float("-inf"))
        max_score = max(vertex_scores.values(), default=0.0)
        return self._build_initial_settlement_explanation(player, chosen_vertex, chosen_score, max_score)

    @use_strategy_weights
    def score_initial_settlement_choice(
            self, player: Player, game: Game, available_vertices: List[Vertex], chosen_vertex: Vertex) -> float:
        if chosen_vertex not in available_vertices:
            return 0.0
        first_settlement = len(player.settlements) == 0
        vertex_scores = {
            vertex: self.vertex_utility(
                vertex,
                player,
                game,
                available_vertices,
                first_settlement,
                use_opponent_interference=self.decision_config.use_opponent_interference,
            )
            for vertex in available_vertices
        }
        return initial_settlement_move_quality(
            vertex_scores.get(chosen_vertex, float("-inf")),
            max(vertex_scores.values(), default=0.0),
        )

    @use_strategy_weights
    def select_initial_road_location_with_explanation(
            self, player: Player, game: Game,
            available_edges: List[Edge]) -> Tuple[Optional[Edge], Optional[ActionExplanation]]:
        """Return the best initial road edge together with an explanation."""
        if not available_edges:
            return None, None
        if not self._use_strategic_move():
            edge = self.random_ai.select_initial_road_location(player, game, available_edges)
            if edge is None:
                return None, None
            return edge, self.explain_initial_road_choice(player, game, available_edges, edge)

        if len(player.settlements) + len(player.cities) >= 2:
            edge = self.road_building_placement(player, game, available_edges)
            if edge is None:
                return None, None
            explanation = self._build_initial_road_explanation(
                edge,
                target_vertex=None,
                explanation_kind=RoadExplanationKind.FLEXIBLE,
                move_quality=initial_road_flexible_move_quality(),
            )
            return edge, explanation

        current_settlement = player.settlements[-1]
        legal_vertices = get_legal_settlement_vertices(make_sim_game_for_player(game, player))
        vertex_scores = {
            vertex: self.vertex_utility(
                vertex,
                player,
                game,
                legal_vertices,
                first_settlement=False,
                use_opponent_interference=self.decision_config.use_opponent_interference,
            )
            for vertex in legal_vertices
        }
        max_legal_vertex_utility = max(vertex_scores.values(), default=0.0)

        if len(player.settlements) == 1:
            best_vertex = max(vertex_scores, key=vertex_scores.get, default=None)
            if best_vertex is not None:
                edge = find_edge_toward_vertex(current_settlement, best_vertex, available_edges)
                if edge is not None:
                    explanation = self._build_initial_road_explanation(
                        edge,
                        target_vertex=best_vertex,
                        explanation_kind=RoadExplanationKind.EXPANSION,
                        move_quality=initial_road_expansion_move_quality(
                            vertex_scores[best_vertex],
                            max_legal_vertex_utility,
                        ),
                    )
                    return edge, explanation
        else:
            connection_edges = [
                edge for edge in available_edges
                if moves_toward_vertex(edge.get_other_vertex(current_settlement), player.settlements[0])
            ]
            if connection_edges:
                explanation = self._build_initial_road_explanation(
                    connection_edges[0],
                    target_vertex=player.settlements[0],
                    explanation_kind=RoadExplanationKind.CONNECTION,
                    move_quality=initial_road_connection_move_quality(len(connection_edges)),
                )
                return connection_edges[0], explanation

            best_vertex = max(vertex_scores, key=vertex_scores.get, default=None)
            if best_vertex is not None:
                edge = find_edge_toward_vertex(current_settlement, best_vertex, available_edges)
                if edge is not None:
                    explanation = self._build_initial_road_explanation(
                        edge,
                        target_vertex=best_vertex,
                        explanation_kind=RoadExplanationKind.EXPANSION,
                        move_quality=initial_road_expansion_move_quality(
                            vertex_scores[best_vertex],
                            max_legal_vertex_utility,
                        ),
                    )
                    return edge, explanation

        edge = self.rng.choice(available_edges)
        explanation = self._build_initial_road_explanation(
            edge,
            target_vertex=None,
            explanation_kind=RoadExplanationKind.FLEXIBLE,
            move_quality=initial_road_flexible_move_quality(),
        )
        return edge, explanation

    @use_strategy_weights
    def explain_initial_road_choice(
            self, player: Player, game: Game, available_edges: List[Edge], chosen_edge: Edge) -> ActionExplanation:
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
            vertex: self.vertex_utility(
                vertex,
                player,
                game,
                legal_vertices,
                first_settlement=False,
                use_opponent_interference=self.decision_config.use_opponent_interference,
            )
            for vertex in legal_vertices
        }
        max_legal_vertex_utility = max(vertex_scores.values(), default=0.0)

        if len(player.settlements) == 1:
            target_vertices = [
                vertex for vertex in legal_vertices
                if find_edge_toward_vertex(current_settlement, vertex, available_edges) == chosen_edge
            ]
            if target_vertices:
                best_vertex = max(target_vertices, key=vertex_scores.get)
                return self._build_initial_road_explanation(
                    chosen_edge,
                    target_vertex=best_vertex,
                    explanation_kind=RoadExplanationKind.EXPANSION,
                    move_quality=initial_road_expansion_move_quality(
                        vertex_scores[best_vertex],
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
            best_vertex = max(target_vertices, key=vertex_scores.get)
            return self._build_initial_road_explanation(
                chosen_edge,
                target_vertex=best_vertex,
                explanation_kind=RoadExplanationKind.EXPANSION,
                move_quality=initial_road_expansion_move_quality(
                    vertex_scores[best_vertex],
                    max_legal_vertex_utility,
                ),
            )

        return self._build_initial_road_explanation(
            chosen_edge,
            target_vertex=None,
            explanation_kind=RoadExplanationKind.FLEXIBLE,
            move_quality=initial_road_flexible_move_quality(),
        )

    @use_strategy_weights
    def score_initial_road_choice(
            self, player: Player, game: Game, available_edges: List[Edge], chosen_edge: Edge) -> float:
        if chosen_edge not in available_edges:
            return 0.0
        if len(player.settlements) + len(player.cities) >= 2:
            return initial_road_flexible_move_quality()

        current_settlement = player.settlements[-1]
        legal_vertices = get_legal_settlement_vertices(make_sim_game_for_player(game, player))
        vertex_scores = {
            vertex: self.vertex_utility(
                vertex,
                player,
                game,
                legal_vertices,
                first_settlement=False,
                use_opponent_interference=self.decision_config.use_opponent_interference,
            )
            for vertex in legal_vertices
        }
        max_legal_vertex_utility = max(vertex_scores.values(), default=0.0)

        if len(player.settlements) == 1:
            target_utilities = [
                vertex_scores[vertex]
                for vertex in legal_vertices
                if find_edge_toward_vertex(current_settlement, vertex, available_edges) == chosen_edge
            ]
            if target_utilities:
                return initial_road_expansion_move_quality(max(target_utilities), max_legal_vertex_utility)
            return initial_road_flexible_move_quality()

        connection_edges = [
            edge for edge in available_edges
            if moves_toward_vertex(edge.get_other_vertex(current_settlement), player.settlements[0])
        ]
        if chosen_edge in connection_edges:
            return initial_road_connection_move_quality(len(connection_edges))

        target_utilities = [
            vertex_scores[vertex]
            for vertex in legal_vertices
            if find_edge_toward_vertex(current_settlement, vertex, available_edges) == chosen_edge
        ]
        if target_utilities:
            return initial_road_expansion_move_quality(max(target_utilities), max_legal_vertex_utility)
        return initial_road_flexible_move_quality()

    @staticmethod
    def vertex_utility(
            vertex: Vertex, player: Player, game: Game, available_vertices: List[Vertex],
            first_settlement: bool = True, use_opponent_interference: bool = True) -> float:
        """Compute utility score for a vertex as a potential settlement location."""
        if not vertex.hexes:
            return float("-inf")

        # Expected resource yield from adjacent hexes (dice probability weighted).
        dice_sum = sum(dice_probability(h.production_number) for h in vertex.hexes)

        # Count distinct resource types for early-game flexibility.
        resources = {h.resource for h in vertex.hexes if h.resource is not None}
        diversity = len(resources)

        # Estimate how much this vertex blocks opponent expansion.
        sim_game = make_sim_game_for_player(game, player)
        blocking_penalty = 1.0

        if use_opponent_interference:
            for opp in game.players:
                if opp == player:
                    continue

                for opp_v in opp.settlements:
                    reachable = get_reachable_vertices(
                        start_vertex=opp_v, player_number=opp.player_number, sim_game=sim_game,
                        available_vertices=available_vertices)
                    # If an opponent could reasonably reach this spot, blocking value is low.
                    if vertex in reachable:
                        blocking_penalty = 0.0
                        break

                if blocking_penalty == 0.0:
                    break

        # Base utility: yield + diversity, with an optional blocking component.
        utility = (StrategyWeights.INIT_PLACE_YIELD * dice_sum + StrategyWeights.INIT_PLACE_DIVERSITY * diversity
                   - StrategyWeights.INIT_PLACE_BLOCK * blocking_penalty)

        # For the second settlement, reward complementary resources across both placements.
        if not first_settlement:
            first_resources = {h.resource for s in player.settlements for h in s.hexes if h.resource is not None}
            combined_diversity = len(resources | first_resources)
            utility += StrategyWeights.INIT_PLACE_DIVERSITY * (combined_diversity - diversity)

        return utility

    def _build_initial_settlement_explanation(
            self, player: Player, vertex: Vertex, best_score: float, max_score: float) -> ActionExplanation:
        first_settlement = len(player.settlements) == 0
        reasons_for = self._initial_settlement_reasons(player, vertex, first_settlement)

        action = Action(ActionType.BUILD, (Buildable.SETTLEMENT, vertex))
        candidate = CandidateExplanation(
            action=action, full_plan=[action], reasons_for=reasons_for,
            metadata={"template": ExplanationTemplate.INITIAL_SETTLEMENT, "target_vertex": vertex, "port": vertex.port})
        return ActionExplanation(
            chosen_action=action,
            chosen_candidate=candidate,
            move_quality=initial_settlement_move_quality(best_score, max_score),
        )

    def _build_initial_road_explanation(
            self, edge: Edge, target_vertex: Optional[Vertex],
            explanation_kind: RoadExplanationKind, move_quality: float) -> ActionExplanation:
        reasons_for = self._initial_road_reasons(target_vertex, explanation_kind)
        visual_plan: List[Tuple[Buildable, object]] = [(Buildable.ROAD, edge)]
        if target_vertex is not None and explanation_kind == RoadExplanationKind.EXPANSION:
            visual_plan.append((Buildable.SETTLEMENT, target_vertex))

        action = Action(ActionType.BUILD, (Buildable.ROAD, edge))
        candidate = CandidateExplanation(
            action=action, full_plan=[action], reasons_for=reasons_for,
            metadata={"template": ExplanationTemplate.INITIAL_ROAD, "target_vertex": target_vertex,
                      "road_explanation_kind": explanation_kind, "visual_plan": visual_plan})
        return ActionExplanation(
            chosen_action=action,
            chosen_candidate=candidate,
            move_quality=move_quality,
        )

    def _initial_settlement_reasons(
            self, player: Player, vertex: Vertex, first_settlement: bool) -> List[Reason]:
        reasons: List[Reason] = []
        resources = {hex_tile.resource for hex_tile in vertex.hexes if hex_tile.resource is not None}
        total_yield = sum(dice_probability(hex_tile.production_number) for hex_tile in vertex.hexes)
        high_yield_count = sum(1 for hex_tile in vertex.hexes if hex_tile.production_number in (6, 8))

        if total_yield > 0:
            reasons.append(Reason(ReasonType.IMPROVES_PRODUCTION, ReasonLabel.INIT_EARLY_PRODUCTION, total_yield))

        if len(resources) >= 2:
            reasons.append(
                Reason(ReasonType.IMPROVES_RESOURCE_DIVERSITY, ReasonLabel.INIT_RESOURCE_DIVERSITY,
                       float(len(resources))))

        if high_yield_count > 0:
            reasons.append(
                Reason(ReasonType.FASTEST_PROGRESS, ReasonLabel.INIT_HIGH_FREQUENCY, float(high_yield_count)))

        if vertex.port is not None:
            reasons.append(
                Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.INIT_PORT_ACCESS, 1.0, {"port": vertex.port}))

        if not first_settlement:
            first_resources = {
                hex_tile.resource for settlement in player.settlements for hex_tile in settlement.hexes
                if hex_tile.resource is not None
            }
            combined_resources = resources | first_resources
            if len(combined_resources) > len(first_resources):
                reasons.append(
                    Reason(ReasonType.IMPROVES_RESOURCE_DIVERSITY, ReasonLabel.INIT_COMPLEMENTS_FIRST,
                           float(len(combined_resources))))

        reasons.sort(key=lambda reason: reason.value, reverse=True)
        return reasons

    def _initial_road_reasons(
            self, target_vertex: Optional[Vertex], explanation_kind: RoadExplanationKind) -> List[Reason]:
        reasons: List[Reason] = []

        if explanation_kind == RoadExplanationKind.CONNECTION:
            reasons.append(Reason(ReasonType.ENABLES_EXPANSION, ReasonLabel.INIT_ROAD_CONNECTION, 2.0))
        elif target_vertex is not None:
            reasons.append(Reason(ReasonType.ENABLES_EXPANSION, ReasonLabel.INIT_ROAD_TO_SETTLEMENT, 2.0))
            reasons.append(Reason(ReasonType.IMPROVES_RESOURCE_DIVERSITY, ReasonLabel.INIT_ROAD_TO_BALANCE, 1.0))
        else:
            reasons.append(Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.INIT_ROAD_FLEXIBLE, 1.0))

        return reasons

    @use_strategy_weights
    def choose_trade_partner(
            self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount,
            available_players: List[Tuple[Player, Optional[ResourceCount]]]) -> Optional[
            Tuple[Player, Optional[ResourceCount]]]:
        """Return the chosen trade partner using ETW-based selection."""
        selection, _ = self.choose_trade_partner_with_explanation(player, game, selling, buying, available_players)
        return selection

    @use_strategy_weights
    def choose_trade_partner_with_explanation(
            self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount,
            available_players: List[Tuple[Player, Optional[ResourceCount]]]) -> Tuple[
            Optional[Tuple[Player, Optional[ResourceCount]]], Optional[ActionExplanation]]:
        """Return the chosen trade partner and a structured explanation."""
        if not self.decision_config.use_player_trading:
            return None, None
        if not self._use_strategic_move():
            selection = self.random_ai.choose_trade_partner(player, game, selling, buying, available_players)
            if selection is None:
                return None, None
            chosen_player, counter = selection
            explanation = self.explain_trade_partner_choice(
                player, game, selling, buying, available_players, chosen_player, counter)
            return selection, explanation

        # Build a lightweight simulated view of the game (we know our own hand, opponents are hidden-info).
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        available_sim_players = [(SimPlayerState(p, opponent=True), offer) for (p, offer) in available_players]

        # Pick the partner (and optional counter-offer) that improves our ETW without helping the leader too much.
        selection = select_best_trade_partner(
            player_sim=sim_us, sim_game=sim_game, etw_estimator=self.etw_estimator, selling_orig=selling,
            buying=buying, available_players=available_sim_players, **self._trade_risk_kwargs())

        if selection is None:
            return None, None

        # Map back from SimPlayerState to the real Player object for the engine.
        chosen_sim_player, counter = selection
        chosen_player = next(p for p in game.players if p.player_number == chosen_sim_player.player_number)
        explanation = self._build_trade_partner_explanation(
            player, sim_us, sim_game, selling, buying, available_players, chosen_player, counter)
        return (chosen_player, counter), explanation

    @use_strategy_weights
    def explain_trade_partner_choice(
            self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount,
            available_players: List[Tuple[Player, Optional[ResourceCount]]], chosen_player: Player,
            counter: Optional[ResourceCount]) -> ActionExplanation:
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        return self._build_trade_partner_explanation(
            player, sim_us, sim_game, selling, buying, available_players, chosen_player, counter)

    @use_strategy_weights
    def select_robber_target(
            self, player: Player, game: Game, valid_hexes: List[HexTile]) -> Tuple[HexTile, Optional[Player]]:
        """Select which hex tile to place the robber on, prioritising opponents' resources."""
        tile, steal_from, _ = self.select_robber_target_with_explanation(player, game, valid_hexes)
        return tile, steal_from

    @use_strategy_weights
    def select_robber_target_with_explanation(
            self, player: Player, game: Game,
            valid_hexes: List[HexTile]) -> Tuple[HexTile, Optional[Player], Optional[ActionExplanation]]:
        """Select robber placement and return a structured explanation."""
        if not self._use_strategic_move():
            tile, steal_from = self.random_ai.select_robber_target(player, game, valid_hexes)
            return tile, steal_from, self.explain_robber_choice(player, game, valid_hexes, tile, steal_from)

        best_score = float("-inf")
        best_hex: Optional[HexTile] = None

        # Used to avoid blocking ourselves unless it's clearly worth it.
        our_resource_tiles = {h for v in (player.settlements + player.cities) for h in v.hexes}

        if not self.decision_config.use_opponent_interference:
            neutral_hexes = [hex_tile for hex_tile in valid_hexes if hex_tile not in our_resource_tiles]
            best_hex = self.rng.choice(neutral_hexes or valid_hexes)
            players_on_best_hex = [p for p in game.get_players_on_hex(best_hex) if p != player]
            best_player = self.rng.choice(players_on_best_hex) if players_on_best_hex else None
            self_harm = 0.0
            if best_hex in our_resource_tiles:
                self_harm = sum(
                    dice_probability(best_hex.production_number) * (2.0 if vertex in player.cities else 1.0)
                    for vertex in (player.settlements + player.cities)
                    if best_hex in vertex.hexes
                )
            explanation = self._build_robber_explanation(
                best_hex, best_player, 0.0, best_hex in our_resource_tiles, self_harm, 0.0)
            return best_hex, best_player, explanation

        sim_game_for_robber = make_sim_game_for_player(game, player)

        # Diversion: if we're (at least) tied for the VP lead, lean into blocking whoever looks strongest.
        our_vp = player.calc_victory_points()[0]
        opp_vps = [p.calc_victory_points()[0] for p in game.players if p != player]
        best_opp_vp = max(opp_vps, default=0)
        diversion_boost = StrategyWeights.DIVERSION_BOOST if our_vp >= best_opp_vp else 1.0

        # For each opponent, estimate which resources matter most to their next "best" action.
        opponent_importance: Dict[PlayerNumber, Dict[Resource, float]] = {}
        for opponent in game.players:
            if opponent == player:
                continue

            sim_game_opp = make_sim_game_for_player(game, opponent)
            best_action = self.etw_estimator.calculate_best_game_action(
                sim_game=sim_game_opp, player_number=opponent.player_number, dev_played=False,
                ignore_affordability=True, **self._planner_kwargs(ignore_opponents=True))

            required = calc_step_resources(best_action)
            total = sum(required.values())
            opponent_importance[opponent.player_number] = (
                {res: amt / total for res, amt in required.items() if amt > 0} if total > 0 else {}
            )

        # Score each candidate robber hex by (production probability * how important the resource is * opponent VP).
        for h in valid_hexes:
            players_on_h = [p for p in game.get_players_on_hex(h) if p != player]
            if not players_on_h:
                continue

            score = 0.0
            for p in players_on_h:
                score += score_hex_for_opponent(
                    opponent_number=p.player_number,
                    sim_game=sim_game_for_robber,
                    hex_tile=h,
                    importance=opponent_importance.get(p.player_number, {}),
                ) * (p.calc_victory_points()[0] * diversion_boost)

            # Prefer not to rob our own production unless the blocking value is high.
            if h in our_resource_tiles:
                score *= StrategyWeights.ROBBER_OWN_HEX_PENALTY

            if score > best_score:
                best_score = score
                best_hex = h

        # Fallback if no hex has opponents on it.
        if best_hex is None:
            best_hex = self.rng.choice(valid_hexes)

        self_harm = 0.0
        if best_hex in our_resource_tiles:
            self_harm = sum(
                dice_probability(best_hex.production_number) * (2.0 if vertex in player.cities else 1.0)
                for vertex in (player.settlements + player.cities)
                if best_hex in vertex.hexes
            )

        # Choose who to steal from on the chosen hex (more resources + more VP = better target).
        players_on_best_hex = [p for p in game.get_players_on_hex(best_hex) if p != player]
        if not players_on_best_hex:
            explanation = self._build_robber_explanation(
                best_hex,
                None,
                best_score,
                best_hex in our_resource_tiles,
                self_harm,
                0.0,
            )
            return best_hex, None, explanation

        best_player = max(players_on_best_hex, key=lambda pl: sum(pl.resources.values()) * pl.calc_victory_points()[0])
        leader_vp_ratio = 0.0
        if best_opp_vp > 0:
            leader_vp_ratio = best_player.calc_victory_points()[0] / best_opp_vp
        explanation = self._build_robber_explanation(
            best_hex,
            best_player,
            best_score,
            best_hex in our_resource_tiles,
            self_harm,
            leader_vp_ratio,
        )
        return best_hex, best_player, explanation

    @use_strategy_weights
    def explain_robber_choice(
            self, player: Player, game: Game, _valid_hexes: List[HexTile], chosen_hex: HexTile,
            chosen_player: Optional[Player]) -> ActionExplanation:
        our_resource_tiles = {h for v in (player.settlements + player.cities) for h in v.hexes}
        if not self.decision_config.use_opponent_interference:
            self_harm = 0.0
            if chosen_hex in our_resource_tiles:
                self_harm = sum(
                    dice_probability(chosen_hex.production_number) * (2.0 if vertex in player.cities else 1.0)
                    for vertex in (player.settlements + player.cities)
                    if chosen_hex in vertex.hexes
                )
            return self._build_robber_explanation(
                chosen_hex, chosen_player, 0.0, chosen_hex in our_resource_tiles, self_harm, 0.0)
        sim_game_for_robber = make_sim_game_for_player(game, player)
        our_vp = player.calc_victory_points()[0]
        opp_vps = [p.calc_victory_points()[0] for p in game.players if p != player]
        best_opp_vp = max(opp_vps, default=0)
        diversion_boost = StrategyWeights.DIVERSION_BOOST if our_vp >= best_opp_vp else 1.0

        opponent_importance: Dict[PlayerNumber, Dict[Resource, float]] = {}
        for opponent in game.players:
            if opponent == player:
                continue
            sim_game_opp = make_sim_game_for_player(game, opponent)
            best_action = self.etw_estimator.calculate_best_game_action(
                sim_game=sim_game_opp, player_number=opponent.player_number, dev_played=False,
                ignore_affordability=True, **self._planner_kwargs(ignore_opponents=True))
            required = calc_step_resources(best_action)
            total = sum(required.values())
            opponent_importance[opponent.player_number] = (
                {res: amt / total for res, amt in required.items() if amt > 0} if total > 0 else {}
            )

        chosen_score = 0.0
        players_on_hex = [p for p in game.get_players_on_hex(chosen_hex) if p != player]
        for p in players_on_hex:
            chosen_score += score_hex_for_opponent(
                opponent_number=p.player_number,
                sim_game=sim_game_for_robber,
                hex_tile=chosen_hex,
                importance=opponent_importance.get(p.player_number, {}),
            ) * (p.calc_victory_points()[0] * diversion_boost)
        if chosen_hex in our_resource_tiles:
            chosen_score *= StrategyWeights.ROBBER_OWN_HEX_PENALTY

        self_harm = 0.0
        if chosen_hex in our_resource_tiles:
            self_harm = sum(
                dice_probability(chosen_hex.production_number) * (2.0 if vertex in player.cities else 1.0)
                for vertex in (player.settlements + player.cities)
                if chosen_hex in vertex.hexes
            )
        target_player = chosen_player
        if target_player is None and players_on_hex:
            target_player = max(players_on_hex, key=lambda pl: sum(pl.resources.values()) * pl.calc_victory_points()[0])
        leader_vp_ratio = 0.0
        if target_player is not None and best_opp_vp > 0:
            leader_vp_ratio = target_player.calc_victory_points()[0] / best_opp_vp
        return self._build_robber_explanation(
            chosen_hex,
            target_player,
            chosen_score,
            chosen_hex in our_resource_tiles,
            self_harm,
            leader_vp_ratio,
        )

    @use_strategy_weights
    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        """Select resources to discard, keeping critical ones for best next action."""
        discard, _ = self.select_discard_resources_with_explanation(player, game, num_resources)
        return discard

    @use_strategy_weights
    def select_discard_resources_with_explanation(
            self, player: Player, game: Game, num_resources: int) -> Tuple[ResourceCount, Optional[ActionExplanation]]:
        """Select the legal discard that maximises the displayed discard move quality."""
        if not self._use_strategic_move():
            discard = self.random_ai.select_discard_resources(player, game, num_resources)
            return discard, self.explain_discard_choice(player, game, discard)

        current_resources, needed, best_plan_explanation = self._discard_context(player, game)
        best_discard: Optional[ResourceCount] = None
        best_explanation: Optional[ActionExplanation] = None
        best_quality = float("-inf")

        for discard in self._legal_discard_candidates(current_resources, num_resources):
            explanation = self._evaluate_discard_choice(
                discard, current_resources, needed, best_plan_explanation)
            if explanation.move_quality > best_quality:
                best_quality = explanation.move_quality
                best_discard = discard
                best_explanation = explanation

        if best_discard is None:
            best_discard = {resource: 0 for resource in Resource}
            best_explanation = self._evaluate_discard_choice(
                best_discard, current_resources, needed, best_plan_explanation)
        return best_discard, best_explanation

    @use_strategy_weights
    def explain_discard_choice(
            self, player: Player, game: Game, discard: ResourceCount) -> ActionExplanation:
        current_resources, needed, best_plan_explanation = self._discard_context(player, game)
        normalized_discard = {resource: int(discard.get(resource, 0)) for resource in Resource}
        return self._evaluate_discard_choice(
            normalized_discard, current_resources, needed, best_plan_explanation)

    def _discard_context(
            self, player: Player, game: Game) -> Tuple[ResourceCount, ResourceCount, ActionExplanation]:
        current_resources = {resource: int(player.resources.get(resource, 0)) for resource in Resource}
        sim_game = make_sim_game_for_player(game, player)
        best_plan_explanation = self.etw_estimator.calculate_best_game_action_with_explanation(
            sim_game=sim_game, player_number=player.player_number, dev_played=False, **self._planner_kwargs())
        needed = {resource: int(calc_step_resources(best_plan_explanation.chosen_action).get(resource, 0))
                  for resource in Resource}
        return current_resources, needed, best_plan_explanation

    def _evaluate_discard_choice(
            self, discard: ResourceCount, current_resources: ResourceCount, needed: ResourceCount,
            best_plan_explanation: ActionExplanation) -> ActionExplanation:
        return self._build_discard_explanation(discard, current_resources, needed, best_plan_explanation)

    def _legal_discard_candidates(
            self, current_resources: ResourceCount, num_resources: int) -> List[ResourceCount]:
        resources = list(Resource)
        candidates: List[ResourceCount] = []

        def build_candidate(index: int, remaining: int, partial: ResourceCount) -> None:
            if index == len(resources):
                if remaining == 0:
                    candidates.append(partial.copy())
                return

            resource = resources[index]
            max_take = min(remaining, int(current_resources.get(resource, 0)))
            for amount in range(max_take + 1):
                partial[resource] = amount
                build_candidate(index + 1, remaining - amount, partial)

        build_candidate(0, num_resources, {resource: 0 for resource in resources})
        return candidates

    def _build_robber_explanation(
            self, hex_tile: HexTile, target_player: Optional[Player], best_score: float,
            blocks_own_hex: bool, self_harm: float, leader_vp_ratio: float) -> ActionExplanation:
        reasons_for: List[Reason] = []
        if best_score > float("-inf"):
            reasons_for.append(Reason(
                ReasonType.SLOWS_LEADING_OPPONENT, ReasonLabel.ROBBER_BLOCKS_KEY_HEX, max(0.0, best_score)))
        if target_player is not None:
            reasons_for.append(Reason(
                ReasonType.SLOWS_LEADING_OPPONENT, ReasonLabel.ROBBER_TARGETS_THREAT,
                float(target_player.calc_victory_points()[0])))
        if not blocks_own_hex:
            reasons_for.append(Reason(
                ReasonType.HEURISTIC_CHOICE, ReasonLabel.ROBBER_AVOIDS_OWN_HEX, 1.0))

        action = Action(ActionType.PLAY_DEV_CARD, "robber")
        candidate = CandidateExplanation(
            action=action,
            full_plan=[action],
            reasons_for=reasons_for,
            metadata={
                "template": ExplanationTemplate.ROBBER_TARGET,
                "target_hex": hex_tile,
                "target_player_name": target_player.name if target_player is not None else None,
                "visual_plan": [("ROBBER_HEX", hex_tile)],
            },
        )
        return ActionExplanation(
            chosen_action=action,
            chosen_candidate=candidate,
            move_quality=robber_move_quality(
                opponent_production_blocked=max(0.0, best_score),
                steal_value=float(sum(target_player.resources.values())) if target_player is not None else 0.0,
                self_harm=self_harm if blocks_own_hex else 0.0,
                leader_vp_ratio=leader_vp_ratio,
            ),
            metadata={"template": ExplanationTemplate.ROBBER_TARGET},
        )

    def _build_discard_explanation(
            self, discard: ResourceCount, current_resources: ResourceCount, needed: ResourceCount,
            best_plan_explanation: ActionExplanation) -> ActionExplanation:
        protected_resources = sum(min(needed.get(resource, 0), amount) for resource, amount in discard.items())
        surplus_discarded = sum(discard.values()) - protected_resources
        plan_metadata = self._discard_plan_metadata(best_plan_explanation)
        reasons_for = [
            Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.DISCARD_PROTECTS_PLAN, float(sum(needed.values()))),
            Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.DISCARD_USES_SURPLUS, float(max(0, surplus_discarded))),
        ]
        action = Action(ActionType.END_TURN, discard)
        candidate = CandidateExplanation(
            action=action,
            full_plan=[action],
            reasons_for=reasons_for,
            metadata={
                "template": ExplanationTemplate.DISCARD_RESOURCES,
                "discard_resources": discard,
                **plan_metadata,
            },
        )
        return ActionExplanation(
            chosen_action=action,
            chosen_candidate=candidate,
            move_quality=discard_move_quality(discard, current_resources, needed),
            metadata={"template": ExplanationTemplate.DISCARD_RESOURCES},
        )

    @staticmethod
    def _discard_plan_metadata(explanation: ActionExplanation) -> Dict[str, object]:
        action = explanation.chosen_action
        protected_action = RuleBasedAI._protected_follow_up_action_from_explanation(explanation)

        metadata: Dict[str, object] = {"protected_action": protected_action}

        trade_action = None
        if action.type in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER):
            trade_action = action
        elif action.type == ActionType.END_TURN and explanation.chosen_candidate.next_plan:
            first_next = explanation.chosen_candidate.next_plan[0]
            if first_next.type in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER):
                trade_action = first_next

        if trade_action is not None:
            payload = trade_action.payload
            if isinstance(payload, tuple) and len(payload) == 2:
                _, buying = payload
                target_resources = [resource for resource, amount in buying.items() if amount > 0]
                if target_resources:
                    metadata["trade_target_resources"] = target_resources

                follow_up_action = protected_action if protected_action != trade_action else (
                    RuleBasedAI._trade_follow_up_action_for_resources(target_resources)
                )
                if follow_up_action is not None:
                    metadata["trade_follow_up_action"] = follow_up_action

        return metadata

    @staticmethod
    def _protected_follow_up_action_from_explanation(explanation: ActionExplanation) -> Action:
        action = explanation.chosen_action
        if action.type == ActionType.END_TURN and explanation.chosen_candidate.next_plan:
            return explanation.chosen_candidate.next_plan[-1]
        if explanation.chosen_candidate.full_plan and explanation.chosen_candidate.full_plan[-1] != action:
            return explanation.chosen_candidate.full_plan[-1]
        return action

    @staticmethod
    def _trade_follow_up_action_for_resources(resources: List[Resource]) -> Optional[Action]:
        resource_set = set(resources)

        if Resource.ORE in resource_set and Resource.WHEAT in resource_set:
            return Action(ActionType.BUILD, (Buildable.CITY, None))
        if Resource.WOOD in resource_set and Resource.BRICK in resource_set and Resource.SHEEP in resource_set:
            return Action(ActionType.BUILD, (Buildable.SETTLEMENT, None))
        if Resource.ORE in resource_set and Resource.SHEEP in resource_set and Resource.WHEAT in resource_set:
            return Action(ActionType.BUY_DEV_CARD)
        if Resource.WOOD in resource_set and Resource.BRICK in resource_set:
            return Action(ActionType.BUILD, (Buildable.ROAD, None))
        return None

    @staticmethod
    def _action_summary_text(action: Action) -> str:
        if action.type == ActionType.BUILD and isinstance(action.payload, tuple) and len(action.payload) >= 1:
            buildable = action.payload[0]
            if hasattr(buildable, "name"):
                return f"build a {buildable.name.lower()}"
        if action.type == ActionType.BUY_DEV_CARD:
            return "buy a development card"
        if action.type == ActionType.TRADE_WITH_BANK:
            return "make a bank trade"
        if action.type == ActionType.TRADE_WITH_PLAYER:
            return "make a player trade"
        if action.type == ActionType.PLAY_DEV_CARD:
            return "play a development card"
        return "take the next planned action"

    @use_strategy_weights
    def select_year_of_plenty_resources(self, player: Player, game: Game) -> ResourceCount:
        """Select the most-needed resources for the player's next action."""
        resources, _ = self.select_year_of_plenty_resources_with_explanation(player, game)
        return resources

    @use_strategy_weights
    def select_year_of_plenty_resources_with_explanation(
            self, player: Player, game: Game) -> Tuple[ResourceCount, Optional[ActionExplanation]]:
        """Select Year of Plenty resources and return a structured explanation."""
        if not self._use_strategic_move():
            selected = self.random_ai.select_year_of_plenty_resources(player, game)
            return selected, self.explain_year_of_plenty_choice(player, game, selected)

        sim_game = make_sim_game_for_player(game, player)
        best_plan_explanation = self.etw_estimator.calculate_best_game_action_with_explanation(
            sim_game=sim_game, player_number=player.player_number, dev_played=False, **self._planner_kwargs())
        primary_action, target_action, target_shortfalls, already_had_next_step = self._year_of_plenty_plan_target(
            player, best_plan_explanation)

        shortfall_priority: List[Resource] = []
        for resource in Resource:
            shortfall_priority.extend([resource] * target_shortfalls[resource])

        if not shortfall_priority and target_action is not None:
            target_cost = calc_step_resources(target_action)
            for resource in Resource:
                shortfall_priority.extend([resource] * target_cost.get(resource, 0))

        if not shortfall_priority:
            shortfall_priority = self._flexible_year_of_plenty_priority(player)

        picked = shortfall_priority[:2]
        selected: ResourceCount = {resource: 0 for resource in Resource}
        for resource in picked:
            selected[resource] += 1

        clearly_supports_follow_up = (
            target_action is not None
            and 0 < sum(selected.values()) == sum(
                min(selected[resource], target_shortfalls[resource])
                for resource in Resource
            )
        )

        explanation = self._build_year_of_plenty_explanation(
            selected,
            primary_action,
            target_action if clearly_supports_follow_up or already_had_next_step else None,
            clearly_supports_follow_up,
            already_had_next_step,
            best_plan_explanation,
        )
        return selected, explanation

    @use_strategy_weights
    def explain_year_of_plenty_choice(
            self, player: Player, game: Game, selected: ResourceCount) -> ActionExplanation:
        normalized_selected = {resource: int(selected.get(resource, 0)) for resource in Resource}
        sim_game = make_sim_game_for_player(game, player)
        best_plan_explanation = self.etw_estimator.calculate_best_game_action_with_explanation(
            sim_game=sim_game, player_number=player.player_number, dev_played=False, **self._planner_kwargs())
        primary_action, target_action, target_shortfalls, already_had_next_step = self._year_of_plenty_plan_target(
            player, best_plan_explanation)
        clearly_supports_follow_up = (
            target_action is not None
            and 0 < sum(normalized_selected.values()) == sum(
                min(normalized_selected[resource], target_shortfalls[resource]) for resource in Resource
            )
        )
        return self._build_year_of_plenty_explanation(
            normalized_selected,
            primary_action,
            target_action if clearly_supports_follow_up or already_had_next_step else None,
            clearly_supports_follow_up,
            already_had_next_step,
            best_plan_explanation,
        )

    @use_strategy_weights
    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        """Select the resource that will most hurt opponents based on their likely next actions."""
        resource, _ = self.select_monopoly_resource_with_explanation(player, game)
        return resource

    @use_strategy_weights
    def select_monopoly_resource_with_explanation(
            self, player: Player, game: Game) -> Tuple[Resource, Optional[ActionExplanation]]:
        """Select Monopoly resource and return a structured explanation."""
        if not self._use_strategic_move():
            chosen = self.random_ai.select_monopoly_resource(player, game)
            return chosen, self.explain_monopoly_choice(player, game, chosen)

        if not self.decision_config.use_opponent_interference:
            best_self_action = self.etw_estimator.calculate_best_game_action(
                sim_game=make_sim_game_for_player(game, player),
                player_number=player.player_number,
                dev_played=False,
                ignore_affordability=True,
                **self._planner_kwargs(ignore_opponents=True),
            )
            required = calc_step_resources(best_self_action)
            candidates = [resource for resource, amount in required.items() if amount > 0]
            chosen = self.rng.choice(candidates) if candidates else self.rng.choice(list(Resource))
            explanation = self._build_monopoly_resource_explanation(chosen, 0, float(required.get(chosen, 0)), 0.0)
            return chosen, explanation

        # Count how often each resource appears in opponents' next planned actions.
        need_counts: Dict[Resource, int] = {r: 0 for r in Resource}
        held_counts: Dict[Resource, int] = {r: 0 for r in Resource}
        leader_counts: Dict[Resource, int] = {r: 0 for r in Resource}
        leader_vp = max(
            (opponent.calc_victory_points()[0] for opponent in game.players if opponent != player),
            default=0,
        )

        for opponent in game.players:
            if opponent == player:
                continue

            # Estimate what the opponent is trying to do next.
            sim_game_opp = make_sim_game_for_player(game, opponent)
            best_action = self.etw_estimator.calculate_best_game_action(
                sim_game=sim_game_opp, player_number=opponent.player_number, dev_played=False,
                ignore_affordability=True, **self._planner_kwargs(ignore_opponents=True))

            # Tally required resources for that action.
            required = calc_step_resources(best_action)
            for r, amt in required.items():
                if amt > 0:
                    need_counts[r] += 1
            for resource, amount in opponent.resources.items():
                held_counts[resource] += amount
                if opponent.calc_victory_points()[0] == leader_vp:
                    leader_counts[resource] += amount

        # Pick the resource most commonly needed across opponents.
        max_count = max(need_counts.values())
        candidates = [r for r, c in need_counts.items() if c == max_count]
        chosen = self.rng.choice(candidates)
        best_self_action = self.etw_estimator.calculate_best_game_action(
            sim_game=make_sim_game_for_player(game, player),
            player_number=player.player_number,
            dev_played=False,
            ignore_affordability=True,
            **self._planner_kwargs(ignore_opponents=True),
        )
        self_gain_efficiency = float(calc_step_resources(best_self_action).get(chosen, 0))
        leader_share = leader_counts[chosen] / max(held_counts[chosen], 1) if held_counts[chosen] > 0 else 0.0
        explanation = self._build_monopoly_resource_explanation(
            chosen,
            held_counts[chosen],
            self_gain_efficiency,
            leader_share,
        )
        return chosen, explanation

    @use_strategy_weights
    def explain_monopoly_choice(self, player: Player, game: Game, chosen: Resource) -> ActionExplanation:
        held_counts: Dict[Resource, int] = {r: 0 for r in Resource}
        leader_counts: Dict[Resource, int] = {r: 0 for r in Resource}
        leader_vp = max(
            (opponent.calc_victory_points()[0] for opponent in game.players if opponent != player),
            default=0,
        )
        for opponent in game.players:
            if opponent == player:
                continue
            for resource, amount in opponent.resources.items():
                held_counts[resource] += amount
                if opponent.calc_victory_points()[0] == leader_vp:
                    leader_counts[resource] += amount
        best_self_action = self.etw_estimator.calculate_best_game_action(
            sim_game=make_sim_game_for_player(game, player),
            player_number=player.player_number,
            dev_played=False,
            ignore_affordability=True,
            **self._planner_kwargs(ignore_opponents=True),
        )
        self_gain_efficiency = float(calc_step_resources(best_self_action).get(chosen, 0))
        leader_share = leader_counts[chosen] / max(held_counts[chosen], 1) if held_counts[chosen] > 0 else 0.0
        return self._build_monopoly_resource_explanation(
            chosen,
            held_counts[chosen],
            self_gain_efficiency,
            leader_share,
        )

    def _build_year_of_plenty_explanation(
            self, selected: ResourceCount, primary_action: Optional[Action], target_action: Optional[Action],
            clearly_supports_follow_up: bool, already_had_next_step: bool,
            best_plan_explanation: ActionExplanation) -> ActionExplanation:
        reasons_for: List[Reason] = []
        if clearly_supports_follow_up and target_action is not None:
            reasons_for.append(Reason(
                ReasonType.QUICK_TO_EXECUTE, ReasonLabel.YOP_FILLS_SHORTFALL, float(sum(selected.values()))))
            reasons_for.append(Reason(
                ReasonType.HEURISTIC_CHOICE, ReasonLabel.YOP_SUPPORTS_FOLLOW_UP, 1.0,
                {
                    "primary_action": primary_action,
                    "follow_up_action": target_action,
                    "already_had_next_step": already_had_next_step,
                }))
        elif target_action is not None:
            reasons_for.append(Reason(
                ReasonType.HEURISTIC_CHOICE, ReasonLabel.YOP_SUPPORTS_FOLLOW_UP, 1.0,
                {
                    "primary_action": primary_action,
                    "follow_up_action": target_action,
                    "already_had_next_step": already_had_next_step,
                }))
        else:
            reasons_for.append(Reason(
                ReasonType.HEURISTIC_CHOICE, ReasonLabel.YOP_FLEXIBLE_PICK, 1.0))

        action = Action(ActionType.PLAY_DEV_CARD, DevelopmentCardType.YEAR_OF_PLENTY)
        candidate = CandidateExplanation(
            action=action,
            full_plan=[action],
            reasons_for=reasons_for,
            metadata={
                "template": ExplanationTemplate.YEAR_OF_PLENTY_RESOURCES,
                "selected_resources": selected,
                "primary_action": primary_action,
                "follow_up_action": target_action,
                "supports_follow_up": clearly_supports_follow_up,
                "already_had_next_step": already_had_next_step,
            },
        )
        return ActionExplanation(
            chosen_action=action,
            chosen_candidate=candidate,
            move_quality=year_of_plenty_move_quality(
                etw_gain=max(0.0, best_plan_explanation.chosen_candidate.etw_delta),
                utility_gain=max(0.0, best_plan_explanation.chosen_candidate.utility_total),
                enables_immediate_build=clearly_supports_follow_up,
            ),
            metadata={"template": ExplanationTemplate.YEAR_OF_PLENTY_RESOURCES},
        )

    def _build_monopoly_resource_explanation(
            self, selected_resource: Resource, total_resource_count: int, self_gain_efficiency: float,
            leader_share: float) -> ActionExplanation:
        reasons_for: List[Reason] = []
        if total_resource_count > 0:
            reasons_for.append(Reason(
                ReasonType.SLOWS_LEADING_OPPONENT, ReasonLabel.MONOPOLY_HIGHEST_DEMAND, float(total_resource_count)))
        else:
            reasons_for.append(Reason(
                ReasonType.HEURISTIC_CHOICE, ReasonLabel.MONOPOLY_FLEXIBLE_PICK, 1.0))

        action = Action(ActionType.PLAY_DEV_CARD, DevelopmentCardType.MONOPOLY)
        candidate = CandidateExplanation(
            action=action,
            full_plan=[action],
            reasons_for=reasons_for,
            metadata={
                "template": ExplanationTemplate.MONOPOLY_RESOURCE,
                "selected_resource": selected_resource,
                "selected_resources": {selected_resource: 1},
            },
        )
        return ActionExplanation(
            chosen_action=action,
            chosen_candidate=candidate,
            move_quality=monopoly_move_quality(total_resource_count, self_gain_efficiency, leader_share),
            metadata={"template": ExplanationTemplate.MONOPOLY_RESOURCE},
        )

    @staticmethod
    def _year_of_plenty_plan_target(
            player: Player, explanation: ActionExplanation
    ) -> Tuple[Optional[Action], Optional[Action], ResourceCount, bool]:
        if explanation.chosen_action.type == ActionType.END_TURN and explanation.chosen_candidate.next_plan:
            plan = explanation.chosen_candidate.next_plan
        elif explanation.chosen_candidate.full_plan:
            plan = explanation.chosen_candidate.full_plan
        else:
            plan = [explanation.chosen_action]

        simulated_resources = player.resources.copy()
        primary_action: Optional[Action] = None
        already_had_next_step = False

        for action in plan:
            cost = calc_step_resources(action)
            if not any(cost.values()):
                continue

            if primary_action is None:
                primary_action = action

            shortfalls = {
                resource: max(0, cost.get(resource, 0) - simulated_resources[resource])
                for resource in Resource
            }
            if sum(shortfalls.values()) > 0:
                return primary_action, action, shortfalls, already_had_next_step

            already_had_next_step = True
            for resource, amount in cost.items():
                simulated_resources[resource] -= amount

        if primary_action is not None:
            return primary_action, primary_action, {resource: 0 for resource in Resource}, already_had_next_step

        return None, None, {resource: 0 for resource in Resource}, False

    @staticmethod
    def _flexible_year_of_plenty_priority(player: Player) -> List[Resource]:
        sorted_resources = sorted(Resource, key=lambda resource: (player.resources[resource], resource.value))
        if len(sorted_resources) >= 2:
            return sorted_resources[:2]
        return sorted_resources

    @use_strategy_weights
    def respond_to_trade(
            self, player: Player, game: Game, opponent: Player, selling: ResourceCount,
            buying: ResourceCount) -> Tuple[bool, Optional[ResourceCount]]:
        """Respond to a proposed trade using BATNA + risk constraints."""
        accepted, counter, _ = self.respond_to_trade_with_explanation(player, game, opponent, selling, buying)
        return accepted, counter

    @use_strategy_weights
    def respond_to_trade_with_explanation(
            self, player: Player, game: Game, opponent: Player, selling: ResourceCount,
            buying: ResourceCount) -> Tuple[bool, Optional[ResourceCount], Optional[ActionExplanation]]:
        """Respond to a proposed trade and return a structured explanation."""
        if not self.decision_config.use_player_trading:
            return False, None, None
        if not self._use_strategic_move():
            accepted, counter = self.random_ai.respond_to_trade(player, game, opponent, selling, buying)
            explanation = self.explain_trade_response_choice(
                player, game, opponent, selling, buying, accepted, counter)
            return accepted, counter, explanation

        # Evaluate the offer in a simulated state.
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)

        # Represent the proposer as a hidden-information opponent for conservative scoring.
        opponent_sim = SimPlayerState(opponent, opponent=True)
        opponents = get_opponents(sim_game, player.player_number)

        # Accept if it improves our ETW versus waiting/bank trades, but avoid helping a close/leading opponent.
        accepted, counter = respond_to_trade_batna(
            player_sim=sim_us, opponent_sim=opponent_sim, sim_game=sim_game, etw_estimator=self.etw_estimator,
            selling_to_us=selling,
            buying_from_us=buying,
            opponents=opponents,
            **{
                key: value
                for key, value in self._trade_risk_kwargs().items()
                if key != "leader_penalty"
            },
        )
        explanation = self._build_trade_response_explanation(
            player, opponent, sim_us, opponent_sim, sim_game, selling, buying, opponents, accepted, counter)
        return accepted, counter, explanation

    @use_strategy_weights
    def explain_trade_response_choice(
            self, player: Player, game: Game, opponent: Player, selling: ResourceCount,
            buying: ResourceCount, accepted: bool, counter: Optional[ResourceCount]) -> ActionExplanation:
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        opponent_sim = SimPlayerState(opponent, opponent=True)
        opponents = get_opponents(sim_game, player.player_number)
        return self._build_trade_response_explanation(
            player, opponent, sim_us, opponent_sim, sim_game, selling, buying, opponents, accepted, counter)

    def _build_trade_partner_explanation(
            self, player: Player, sim_us: SimPlayerState, sim_game, selling: ResourceCount, buying: ResourceCount,
            available_players: List[Tuple[Player, Optional[ResourceCount]]], chosen_player: Player,
            counter: Optional[ResourceCount]) -> ActionExplanation:
        batna_etw = self.etw_estimator.estimated_time_to_win(
            sim_us, sim_game, False, **self._etw_kwargs(include_player_trades=False))
        candidate_explanations: List[CandidateExplanation] = []

        all_sims = [sim_us] + [SimPlayerState(opp, opponent=True) for opp, _ in available_players]
        etw_by_player = {
            sim_player: self.etw_estimator.estimated_time_to_win(
                sim_player.copy(), sim_game, False, **self._etw_kwargs(include_player_trades=False))
            for sim_player in all_sims
        }
        leading_sim = min(etw_by_player, key=etw_by_player.get)

        for opponent, offered_counter in available_players:
            opp_sim = SimPlayerState(opponent, opponent=True)
            payment = offered_counter if offered_counter is not None else selling
            if any(sim_us.resources.get(resource, 0) < amount for resource, amount in payment.items()):
                continue

            sim_after = sim_us.copy()
            sim_after.remove_resources(payment)
            sim_after.add_resources(buying)
            sim_game_after = make_sim_game_for_player(sim_game.game, player)
            sim_game_after.overlay.set_sim_player(sim_after)
            etw_after = self.etw_estimator.estimated_time_to_win(
                sim_after, sim_game_after, False, **self._etw_kwargs(include_player_trades=False))
            delta_ai = batna_etw - etw_after
            if delta_ai <= 0:
                continue

            delta_opp = 0.0
            if self.decision_config.use_opponent_interference:
                etw_opp_before = self.etw_estimator.estimated_time_to_win(
                    opp_sim, sim_game, False, **self._etw_kwargs(include_player_trades=False))
                sim_opp_after = opp_sim.copy()
                sim_opp_after.add_resources(payment)
                sim_opp_after.remove_resources(buying)
                sim_game_opp_after = make_sim_game_for_player(sim_game.game, player)
                sim_game_opp_after.overlay.set_sim_player(sim_opp_after)
                etw_opp_after = self.etw_estimator.estimated_time_to_win(
                    sim_opp_after, sim_game_opp_after, False, **self._etw_kwargs(include_player_trades=False))
                delta_opp = max(0.0, etw_opp_before - etw_opp_after)

            is_leader = opp_sim == leading_sim
            vp_gap = opp_sim.victory_points() - sim_us.victory_points()
            is_close = vp_gap >= -StrategyWeights.CLOSE_OPPONENT_VP_GAP
            lambda_risk = StrategyWeights.LAMBDA_RISK_LEADER if is_leader else StrategyWeights.LAMBDA_RISK_BASE
            if (
                self.decision_config.use_opponent_interference
                and (is_close or is_leader)
                and delta_opp >= lambda_risk * delta_ai
            ):
                continue

            reasons_for = [
                Reason(ReasonType.FASTEST_PROGRESS, ReasonLabel.TRADE_PARTNER_BEST_ETW, delta_ai),
            ]
            if offered_counter is not None:
                saved_resources = max(0.0, float(sum(selling.values()) - sum(payment.values())))
                reasons_for.append(
                    Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.TRADE_PARTNER_COUNTER_VALUE, saved_resources))
            if self.decision_config.use_opponent_interference and (is_close or is_leader):
                safety_margin = max(0.0, lambda_risk * delta_ai - delta_opp)
                reasons_for.append(
                    Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.TRADE_PARTNER_SAFE_OPPONENT, safety_margin))

            action = Action(ActionType.TRADE_WITH_PLAYER, (payment, buying))
            candidate_explanations.append(CandidateExplanation(
                action=action,
                full_plan=[action],
                etw_before=batna_etw,
                etw_after=etw_after,
                etw_delta=delta_ai,
                utility_total=batna_etw - etw_after - (
                    StrategyWeights.TRADE_LEADER_PENALTY
                    if self.decision_config.use_opponent_interference and is_leader else 0.0
                ),
                reasons_for=reasons_for,
                metadata={
                    "template": ExplanationTemplate.TRADE_PARTNER,
                    "partner_name": opponent.name,
                    "partner_player_number": opponent.player_number,
                    "payment": payment,
                    "buying": buying,
                    "self_gain": delta_ai,
                    "opponent_gain": delta_opp,
                    "partner_is_leader": is_leader,
                },
            ))

        candidate_explanations.sort(key=lambda candidate: candidate.utility_total, reverse=True)
        chosen_candidate = next((
            candidate for candidate in candidate_explanations
            if candidate.metadata.get("partner_player_number") == chosen_player.player_number
            and candidate.metadata.get("payment") == (counter if counter is not None else selling)
        ), None)
        if chosen_candidate is None:
            action = Action(ActionType.TRADE_WITH_PLAYER, ((counter if counter is not None else selling), buying))
            chosen_candidate = CandidateExplanation(
                action=action,
                full_plan=[action],
                reasons_for=[Reason(
                    ReasonType.HEURISTIC_CHOICE, ReasonLabel.TRADE_PARTNER_BEST_ETW, 0.0)],
                metadata={
                    "template": ExplanationTemplate.TRADE_PARTNER,
                    "partner_name": chosen_player.name,
                    "partner_player_number": chosen_player.player_number,
                    "payment": counter if counter is not None else selling,
                    "buying": buying,
                },
            )
            candidate_explanations.insert(0, chosen_candidate)
        alternatives = [
            candidate for candidate in candidate_explanations
            if candidate is not chosen_candidate
        ][:3]
        return ActionExplanation(
            chosen_action=chosen_candidate.action,
            chosen_candidate=chosen_candidate,
            alternatives=alternatives,
            move_quality=trade_partner_move_quality(
                self_gain=float(chosen_candidate.metadata.get("self_gain", 0.0)),
                opponent_gain=float(chosen_candidate.metadata.get("opponent_gain", 0.0)),
                partner_is_leader=bool(chosen_candidate.metadata.get("partner_is_leader", False)),
            ),
            metadata={"template": ExplanationTemplate.TRADE_PARTNER},
        )

    def _build_trade_response_explanation(
            self, player: Player, opponent: Player, sim_us: SimPlayerState, opponent_sim: SimPlayerState, sim_game,
            selling_to_us: ResourceCount, buying_from_us: ResourceCount, opponents: List[SimPlayerState],
            accepted: bool, counter: Optional[ResourceCount]) -> ActionExplanation:
        etw_before = self.etw_estimator.estimated_time_to_win(
            sim_us, sim_game, False, **self._etw_kwargs(include_player_trades=False))

        offered_after = sim_us.copy()
        offered_after.add_resources(selling_to_us)
        offered_after.remove_resources(buying_from_us)
        offered_game = make_sim_game_for_player(sim_game.game, player)
        offered_game.overlay.set_sim_player(offered_after)
        etw_after_offer = self.etw_estimator.estimated_time_to_win(
            offered_after, offered_game, False, **self._etw_kwargs(include_player_trades=False))
        delta_offer = etw_before - etw_after_offer

        all_players = [sim_us, *opponents]
        etw_by_player = {
            sim_player: self.etw_estimator.estimated_time_to_win(
                sim_player.copy(), sim_game, False, **self._etw_kwargs(include_player_trades=False))
            for sim_player in all_players
        }
        leading = min(etw_by_player, key=etw_by_player.get)
        is_leader = opponent_sim == leading
        vp_gap = opponent_sim.victory_points() - sim_us.victory_points()
        is_close = vp_gap >= -StrategyWeights.CLOSE_OPPONENT_VP_GAP
        lambda_risk = StrategyWeights.LAMBDA_RISK_LEADER if is_leader else StrategyWeights.LAMBDA_RISK_BASE

        delta_opp_offer = 0.0
        if self.decision_config.use_opponent_interference:
            opp_before = self.etw_estimator.estimated_time_to_win(
                opponent_sim, sim_game, False, **self._etw_kwargs(include_player_trades=False))
            opp_after_offer = opponent_sim.copy()
            opp_after_offer.remove_resources(selling_to_us)
            opp_after_offer.add_resources(buying_from_us)
            opp_game = make_sim_game_for_player(sim_game.game, player)
            opp_game.overlay.set_sim_player(opp_after_offer)
            opp_after = self.etw_estimator.estimated_time_to_win(
                opp_after_offer, opp_game, False, **self._etw_kwargs(include_player_trades=False))
            delta_opp_offer = max(0.0, opp_before - opp_after)

        decision = "reject"
        payment = buying_from_us
        reasons_for: List[Reason] = []
        chosen_action = Action(ActionType.TRADE_WITH_PLAYER, (payment, selling_to_us))
        etw_after = etw_after_offer
        etw_delta = delta_offer

        if accepted and counter is None:
            decision = "accept"
            reasons_for.append(Reason(ReasonType.FASTEST_PROGRESS, ReasonLabel.TRADE_RESPONSE_ACCEPT_VALUE,
                                      delta_offer))
            if self.decision_config.use_opponent_interference and (is_close or is_leader):
                reasons_for.append(Reason(
                    ReasonType.HEURISTIC_CHOICE, ReasonLabel.TRADE_PARTNER_SAFE_OPPONENT,
                    max(0.0, lambda_risk * delta_offer - delta_opp_offer)))
        elif accepted and counter is not None:
            decision = "counter"
            chosen_action = Action(ActionType.TRADE_WITH_PLAYER, (counter, selling_to_us))
            counter_after = sim_us.copy()
            counter_after.add_resources(selling_to_us)
            counter_after.remove_resources(counter)
            counter_game = make_sim_game_for_player(sim_game.game, player)
            counter_game.overlay.set_sim_player(counter_after)
            etw_after = self.etw_estimator.estimated_time_to_win(
                counter_after, counter_game, False, **self._etw_kwargs(include_player_trades=False))
            etw_delta = etw_before - etw_after
            reasons_for.append(
                Reason(ReasonType.FASTEST_PROGRESS, ReasonLabel.TRADE_RESPONSE_COUNTER_VALUE, etw_delta))
        else:
            if delta_offer <= 0:
                reasons_for.append(
                    Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.TRADE_RESPONSE_REJECT_NO_GAIN, abs(delta_offer)))
            else:
                reasons_for.append(
                    Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.TRADE_RESPONSE_REJECT_RISK, delta_opp_offer))

        candidate = CandidateExplanation(
            action=chosen_action,
            full_plan=[chosen_action],
            etw_before=etw_before,
            etw_after=etw_after,
            etw_delta=etw_delta,
            utility_total=max(0.0, etw_delta),
            reasons_for=reasons_for,
            metadata={
                "template": ExplanationTemplate.TRADE_RESPONSE,
                "decision": decision,
                "opponent_name": opponent.name,
                "turn_player_number": opponent.player_number,
                "selling_to_us": selling_to_us,
                "payment": buying_from_us,
                "counter_payment": counter,
            },
        )
        return ActionExplanation(
            chosen_action=chosen_action,
            chosen_candidate=candidate,
            move_quality=strategic_turn_move_quality(candidate),
            metadata={
                "template": ExplanationTemplate.TRADE_RESPONSE,
                "turn_player_number": opponent.player_number,
            },
        )

    @use_strategy_weights
    def road_building_placement(
            self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
        """Select an edge for road building, prioritising network connections or high-utility settlements."""
        sim_game = make_sim_game_for_player(game, player)

        # First priority: connect isolated road segments or attach roads back to our structures.
        connecting_edge = find_gap_connection(player.player_number, sim_game, available_edges)
        if connecting_edge:
            return connecting_edge

        # Otherwise, push roads toward the best available settlement expansion spot.
        legal_vertices = get_legal_settlement_vertices(sim_game)
        if legal_vertices:
            best_vertex = max(
                legal_vertices,
                key=lambda v: self.vertex_utility(
                    v,
                    player,
                    game,
                    legal_vertices,
                    first_settlement=False,
                    use_opponent_interference=self.decision_config.use_opponent_interference,
                ),
                default=None)
            if best_vertex:
                return find_edge_toward_vertex_from_any(player.player_number, sim_game, best_vertex, available_edges)

        # Fallback: keep the agent moving even if no clear preference exists.
        return self.rng.choice(available_edges) if available_edges else None

    @use_strategy_weights
    def next_action_with_explanation(
            self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Tuple[Action, ActionExplanation]:
        """Determine the next action and return a structured explanation."""
        if not self._use_strategic_move():
            action = self.random_ai.next_action(player, game, phase, dev_played)
            return action, self._build_random_action_explanation(action, phase)

        if phase == Phase.PRE_ROLL:
            if not dev_played and self.decision_config.use_development_cards:
                sim_game = make_sim_game_for_player(game, player)
                sim_us = sim_game.overlay.get_sim_player(player.player_number)

                dev_candidates = play_development_card_action(sim_us, sim_game)

                if dev_candidates:
                    etw_before = self.etw_estimator.estimated_time_to_win(
                        sim_us.copy(), sim_game, dev_played, **self._etw_kwargs())

                    opponents_etw_before: Dict[PlayerNumber, float] = {}
                    if self.decision_config.use_opponent_interference:
                        opponents_etw_before = {
                            opp.player_number: self.etw_estimator.estimated_time_to_win(
                                opp.copy(), sim_game, False, **self._etw_kwargs())
                            for opp in get_opponents(sim_game, player.player_number)
                        }

                    explained_candidates = self.etw_estimator.evaluate_candidates_with_explanations(
                        sim_us,
                        sim_game,
                        dev_played,
                        dev_candidates,
                        etw_before,
                        opponents_etw_before,
                        include_player_trades=self.decision_config.use_player_trading,
                        allow_development_cards=self.decision_config.use_development_cards,
                        use_planning=self.decision_config.use_etw_planning,
                        use_time_discount=self.decision_config.use_time_discount,
                    )

                    if explained_candidates:
                        best_candidate = explained_candidates[0]
                        if best_candidate.utility_total > 0.0:
                            explanation = ActionExplanation(
                                chosen_action=best_candidate.action,
                                chosen_candidate=best_candidate,
                                alternatives=explained_candidates[1:4],
                                move_quality=strategic_turn_move_quality(
                                    best_candidate,
                                    explained_candidates[1].utility_total if len(explained_candidates) > 1 else None,
                                    explained_candidates[-1].utility_total if explained_candidates else None,
                                ),
                                assumptions=[AssumptionCode.PRE_ROLL_DEV_ONLY],
                                metadata={"phase": "pre_roll"},
                            )
                            return best_candidate.action, explanation

            roll_action = Action(ActionType.ROLL)
            explanation = ActionExplanation(
                chosen_action=roll_action,
                chosen_candidate=CandidateExplanation(
                    action=roll_action, full_plan=[roll_action],
                    reasons_for=[Reason(type=ReasonType.HEURISTIC_CHOICE, label=ReasonLabel.PRE_ROLL_NO_DEV_PLAY,
                                        value=0.0)]),
                alternatives=[], move_quality=0.0, assumptions=[],
                metadata={"phase": "pre_roll"})
            return roll_action, explanation

        sim_game = make_sim_game_for_player(game, player)

        explanation = self.etw_estimator.calculate_best_game_action_with_explanation(
            sim_game=sim_game, player_number=player.player_number, dev_played=dev_played, **self._planner_kwargs())

        best_action = explanation.chosen_action

        if best_action.type == ActionType.TRADE_WITH_PLAYER:
            self.etw_estimator.record_trade_proposal(player.resources)
        else:
            self.etw_estimator.clear_trade_proposal()

        return best_action, explanation

    @use_strategy_weights
    def explain_pre_roll_dev_choice(
            self, player: Player, game: Game, card_type: DevelopmentCardType) -> ActionExplanation:
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        dev_candidates = play_development_card_action(sim_us, sim_game)
        etw_before = self.etw_estimator.estimated_time_to_win(sim_us.copy(), sim_game, False, **self._etw_kwargs())
        opponents_etw_before: Dict[PlayerNumber, float] = {}
        if self.decision_config.use_opponent_interference:
            opponents_etw_before = {
                opp.player_number: self.etw_estimator.estimated_time_to_win(
                    opp.copy(), sim_game, False, **self._etw_kwargs()
                )
                for opp in get_opponents(sim_game, player.player_number)
            }
        explained_candidates = self.etw_estimator.evaluate_candidates_with_explanations(
            sim_us,
            sim_game,
            False,
            dev_candidates,
            etw_before,
            opponents_etw_before,
            include_player_trades=self.decision_config.use_player_trading,
            allow_development_cards=self.decision_config.use_development_cards,
            use_planning=self.decision_config.use_etw_planning,
            use_time_discount=self.decision_config.use_time_discount,
        )
        chosen_candidate = next((
            candidate for candidate in explained_candidates
            if candidate.action.type == ActionType.PLAY_DEV_CARD and candidate.action.payload == card_type
        ), None)
        if chosen_candidate is None:
            chosen_candidate = CandidateExplanation(
                action=Action(ActionType.PLAY_DEV_CARD, card_type),
                full_plan=[Action(ActionType.PLAY_DEV_CARD, card_type)],
                reasons_for=[],
            )
        alternatives = [candidate for candidate in explained_candidates if candidate is not chosen_candidate][:3]
        return ActionExplanation(
            chosen_action=chosen_candidate.action,
            chosen_candidate=chosen_candidate,
            alternatives=alternatives,
            move_quality=strategic_turn_move_quality(
                chosen_candidate,
                alternatives[0].utility_total if alternatives else None,
                explained_candidates[-1].utility_total if explained_candidates else None,
            ),
            assumptions=[AssumptionCode.PRE_ROLL_DEV_ONLY],
            metadata={"phase": "pre_roll"},
        )

    @use_strategy_weights
    def explain_action(
            self, player: Player, game: Game, phase: Phase, dev_played: bool, action: Action) -> ActionExplanation:
        if phase == Phase.PRE_ROLL:
            candidate = CandidateExplanation(
                action=action,
                full_plan=[action],
                reasons_for=[],
            )
            return ActionExplanation(
                chosen_action=action,
                chosen_candidate=candidate,
                alternatives=[],
                move_quality=0.0,
                metadata={"phase": "pre_roll"},
            )

        sim_game = make_sim_game_for_player(game, player)
        return self.etw_estimator.explain_action(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=dev_played,
            action=action,
            **self._planner_kwargs(),
        )

    @use_strategy_weights
    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        """Determine the next action to take for the current phase of the game."""
        action, _ = self.next_action_with_explanation(player, game, phase, dev_played)
        return action
