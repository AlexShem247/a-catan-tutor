from random import Random
from typing import List, Optional, Tuple

from ai.RandomAI import RandomAI
from ai.actions import Action, ActionType
from ai.simulation.SimGame import make_sim_game_for_player
from ai.simulation.SimPlayerState import dice_probability
from ai.simulation.board_sim_utils import (
    find_edge_toward_vertex,
    find_edge_toward_vertex_from_any,
    find_gap_connection,
    get_legal_settlement_vertices,
    get_reachable_vertices,
    moves_toward_vertex,
)
from ai.tutor.explanations import (
    ActionExplanation,
    CandidateExplanation,
    ExplanationTemplate,
    Reason,
    ReasonLabel,
    ReasonType,
    RoadExplanationKind,
)
from ai.tutor.move_quality import (
    initial_road_connection_move_quality,
    initial_road_expansion_move_quality,
    initial_road_flexible_move_quality,
    initial_settlement_move_quality,
)
from config.StrategyWeights import StrategyWeights
from game.Edge import Edge
from game.Game import Game
from game.Player import Player
from game.PlayerAssets import Buildable
from game.Vertex import Vertex


class OpeningPolicy:
    def __init__(self, rng: Random, random_ai: RandomAI, decision_config, use_strategic_move):
        self.rng = rng
        self.random_ai = random_ai
        self.decision_config = decision_config
        self._use_strategic_move = use_strategic_move

    def select_initial_settlement_location(
            self, player: Player, game: Game, available_vertices: List[Vertex]) -> Optional[Vertex]:
        vertex, _ = self.select_initial_settlement_location_with_explanation(player, game, available_vertices)
        return vertex

    def select_initial_road_location(
            self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
        edge, _ = self.select_initial_road_location_with_explanation(player, game, available_edges)
        return edge

    def select_initial_settlement_location_with_explanation(
            self, player: Player, game: Game,
            available_vertices: List[Vertex]) -> Tuple[Optional[Vertex], Optional[ActionExplanation]]:
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

    def select_initial_road_location_with_explanation(
            self, player: Player, game: Game,
            available_edges: List[Edge]) -> Tuple[Optional[Edge], Optional[ActionExplanation]]:
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
        if not vertex.hexes:
            return float("-inf")

        dice_sum = sum(dice_probability(h.production_number) for h in vertex.hexes)
        resources = {h.resource for h in vertex.hexes if h.resource is not None}
        diversity = len(resources)
        sim_game = make_sim_game_for_player(game, player)
        blocking_penalty = 1.0

        if use_opponent_interference:
            for opp in game.players:
                if opp == player:
                    continue

                for opp_v in opp.settlements:
                    reachable = get_reachable_vertices(
                        start_vertex=opp_v,
                        player_number=opp.player_number,
                        sim_game=sim_game,
                        available_vertices=available_vertices,
                    )
                    if vertex in reachable:
                        blocking_penalty = 0.0
                        break

                if blocking_penalty == 0.0:
                    break

        utility = (
            StrategyWeights.INIT_PLACE_YIELD * dice_sum
            + StrategyWeights.INIT_PLACE_DIVERSITY * diversity
            - StrategyWeights.INIT_PLACE_BLOCK * blocking_penalty
        )

        if not first_settlement:
            first_resources = {h.resource for s in player.settlements for h in s.hexes if h.resource is not None}
            combined_diversity = len(resources | first_resources)
            utility += StrategyWeights.INIT_PLACE_DIVERSITY * (combined_diversity - diversity)

        return utility

    def road_building_placement(
            self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
        sim_game = make_sim_game_for_player(game, player)
        connecting_edge = find_gap_connection(player.player_number, sim_game, available_edges)
        if connecting_edge:
            return connecting_edge

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
                default=None,
            )
            if best_vertex:
                return find_edge_toward_vertex_from_any(player.player_number, sim_game, best_vertex, available_edges)

        return self.rng.choice(available_edges) if available_edges else None

    def build_initial_settlement_explanation(
            self, player: Player, vertex: Vertex, best_score: float, max_score: float) -> ActionExplanation:
        return self._build_initial_settlement_explanation(player, vertex, best_score, max_score)

    def build_initial_road_explanation(
            self,
            edge: Edge,
            target_vertex: Optional[Vertex],
            explanation_kind: RoadExplanationKind,
            move_quality: float,
    ) -> ActionExplanation:
        return self._build_initial_road_explanation(edge, target_vertex, explanation_kind, move_quality)

    def _build_initial_settlement_explanation(
            self, player: Player, vertex: Vertex, best_score: float, max_score: float) -> ActionExplanation:
        first_settlement = len(player.settlements) == 0
        reasons_for = self._initial_settlement_reasons(player, vertex, first_settlement)
        action = Action(ActionType.BUILD, (Buildable.SETTLEMENT, vertex))
        candidate = CandidateExplanation(
            action=action,
            full_plan=[action],
            reasons_for=reasons_for,
            metadata={
                "template": ExplanationTemplate.INITIAL_SETTLEMENT,
                "target_vertex": vertex,
                "port": vertex.port,
            },
        )
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
            action=action,
            full_plan=[action],
            reasons_for=reasons_for,
            metadata={
                "template": ExplanationTemplate.INITIAL_ROAD,
                "target_vertex": target_vertex,
                "road_explanation_kind": explanation_kind,
                "visual_plan": visual_plan,
            },
        )
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
            reasons.append(Reason(
                ReasonType.IMPROVES_RESOURCE_DIVERSITY,
                ReasonLabel.INIT_RESOURCE_DIVERSITY,
                float(len(resources)),
            ))

        if high_yield_count > 0:
            reasons.append(Reason(
                ReasonType.FASTEST_PROGRESS,
                ReasonLabel.INIT_HIGH_FREQUENCY,
                float(high_yield_count),
            ))

        if vertex.port is not None:
            reasons.append(Reason(
                ReasonType.HEURISTIC_CHOICE,
                ReasonLabel.INIT_PORT_ACCESS,
                1.0,
                {"port": vertex.port},
            ))

        if not first_settlement:
            first_resources = {
                hex_tile.resource
                for settlement in player.settlements
                for hex_tile in settlement.hexes
                if hex_tile.resource is not None
            }
            combined_resources = resources | first_resources
            if len(combined_resources) > len(first_resources):
                reasons.append(Reason(
                    ReasonType.IMPROVES_RESOURCE_DIVERSITY,
                    ReasonLabel.INIT_COMPLEMENTS_FIRST,
                    float(len(combined_resources)),
                ))

        reasons.sort(key=lambda reason: reason.value, reverse=True)
        return reasons

    @staticmethod
    def _initial_road_reasons(
            target_vertex: Optional[Vertex], explanation_kind: RoadExplanationKind) -> List[Reason]:
        reasons: List[Reason] = []
        if explanation_kind == RoadExplanationKind.CONNECTION:
            reasons.append(Reason(ReasonType.ENABLES_EXPANSION, ReasonLabel.INIT_ROAD_CONNECTION, 2.0))
        elif target_vertex is not None:
            reasons.append(Reason(ReasonType.ENABLES_EXPANSION, ReasonLabel.INIT_ROAD_TO_SETTLEMENT, 2.0))
            reasons.append(Reason(ReasonType.IMPROVES_RESOURCE_DIVERSITY, ReasonLabel.INIT_ROAD_TO_BALANCE, 1.0))
        else:
            reasons.append(Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.INIT_ROAD_FLEXIBLE, 1.0))
        return reasons
