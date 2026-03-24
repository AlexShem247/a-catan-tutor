import random
from typing import Optional, List, Dict, Tuple

from ai.AI import AI
from ai.ai_utils.EtwEstimator import EtwEstimator
from ai.ai_utils.SimGame import make_sim_game_for_player
from ai.ai_utils.SimPlayerState import SimPlayerState, dice_probability
from ai.ai_utils.action_utils import play_development_card_action
from ai.ai_utils.actions import Phase, ActionType, Action
from ai.ai_utils.board_sim_utils import (
    get_legal_settlement_vertices,
    find_edge_toward_vertex,
    moves_toward_vertex,
    get_reachable_vertices,
    score_hex_for_opponent,
    find_gap_connection,
    find_edge_toward_vertex_from_any,
    get_opponents,
)
from ai.ai_utils.explanations import ActionExplanation, CandidateExplanation, Reason, ReasonType
from ai.ai_utils.resource_utils import calc_step_resources
from ai.ai_utils.trade_utils import respond_to_trade_batna, select_best_trade_partner
from config.StrategyWeights import StrategyWeights
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex


class RuleBasedAI(AI):
    def __init__(self):
        self.etw_estimator = EtwEstimator()

    def new_turn(self):
        self.etw_estimator.new_turn()

    def select_initial_settlement_location(
        self,
        player: Player,
        game: Game,
        available_vertices: List[Vertex],
    ) -> Optional[Vertex]:
        """Return the best initial settlement vertex based on utility evaluation."""
        if not available_vertices:
            return None

        # Score each candidate by expected yield + resource diversity,
        first_settlement = (len(player.settlements) == 0)

        return max(
            available_vertices,
            key=lambda v: self.vertex_utility(v, player, game, available_vertices, first_settlement),
            default=None,
        )

    def select_initial_road_location(
        self,
        player: Player,
        game: Game,
        available_edges: List[Edge],
    ) -> Optional[Edge]:
        """Return the best initial road edge connecting settlements or toward high-utility vertices."""
        if not available_edges:
            return None

        # After initial setup, fall back to the normal road placement logic.
        if len(player.settlements) + len(player.cities) >= 2:
            return self.road_building_placement(player, game, available_edges)

        # We place the road from the most recently placed settlement.
        current_settlement = player.settlements[-1]

        # Precompute candidate settlement spots so the road can "point" toward a good future expansion.
        legal_vertices = get_legal_settlement_vertices(make_sim_game_for_player(game, player))

        if len(player.settlements) == 1:
            # First road: head toward the best available second settlement location.
            best_vertex = max(
                legal_vertices,
                key=lambda v: self.vertex_utility(v, player, game, legal_vertices, first_settlement=False),
                default=None,
            )
            if best_vertex:
                return find_edge_toward_vertex(current_settlement, best_vertex, available_edges)
        else:
            # Second road: try to connect back toward the first settlement (helps with early connectivity).
            for edge in available_edges:
                other_vertex = edge.get_other_vertex(current_settlement)
                if moves_toward_vertex(other_vertex, player.settlements[0]):
                    return edge

            # If we can't connect neatly, still aim toward the best next settlement spot.
            best_vertex = max(
                legal_vertices,
                key=lambda v: self.vertex_utility(v, player, game, legal_vertices, first_settlement=False),
                default=None,
            )
            if best_vertex:
                return find_edge_toward_vertex(current_settlement, best_vertex, available_edges)

        # Safety fallback
        return random.choice(available_edges) if available_edges else None

    @staticmethod
    def vertex_utility(
        vertex: Vertex,
        player: Player,
        game: Game,
        available_vertices: List[Vertex],
        first_settlement: bool = True,
    ) -> float:
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
                # If an opponent could reasonably reach this spot, blocking value is low.
                if vertex in reachable:
                    blocking_penalty = 0.0
                    break

            if blocking_penalty == 0.0:
                break

        # Base utility: yield + diversity, with an optional blocking component.
        utility = (
                StrategyWeights.INIT_PLACE_YIELD * dice_sum
                + StrategyWeights.INIT_PLACE_DIVERSITY * diversity
                - StrategyWeights.INIT_PLACE_BLOCK * blocking_penalty
        )

        # For the second settlement, reward complementary resources across both placements.
        if not first_settlement:
            first_resources = {
                h.resource
                for s in player.settlements
                for h in s.hexes
                if h.resource is not None
            }
            combined_diversity = len(resources | first_resources)
            utility += StrategyWeights.INIT_PLACE_DIVERSITY * (combined_diversity - diversity)

        return utility

    def choose_trade_partner(
        self,
        player: Player,
        game: Game,
        selling: ResourceCount,
        buying: ResourceCount,
        available_players: List[Tuple[Player, Optional[ResourceCount]]],
    ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        """Return the chosen trade partner using ETW-based selection."""

        # Build a lightweight simulated view of the game (we know our own hand, opponents are hidden-info).
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        available_sim_players = [(SimPlayerState(p, opponent=True), offer) for (p, offer) in available_players]

        # Pick the partner (and optional counter-offer) that improves our ETW without helping the leader too much.
        selection = select_best_trade_partner(
            player_sim=sim_us,
            sim_game=sim_game,
            etw_estimator=self.etw_estimator,
            selling_orig=selling,
            buying=buying,
            available_players=available_sim_players,
        )

        if selection is None:
            return None

        # Map back from SimPlayerState to the real Player object for the engine.
        chosen_sim_player, counter = selection
        chosen_player = next(p for p in game.players if p.player_number == chosen_sim_player.player_number)
        return chosen_player, counter

    def select_robber_target(
        self,
        player: Player,
        game: Game,
        valid_hexes: List[HexTile],
    ) -> Tuple[HexTile, Optional[Player]]:
        """Select which hex tile to place the robber on, prioritising opponents' resources."""
        best_score = float("-inf")
        best_hex: Optional[HexTile] = None

        # Used to avoid blocking ourselves unless it's clearly worth it.
        our_resource_tiles = {h for v in (player.settlements + player.cities) for h in v.hexes}

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
                sim_game=sim_game_opp,
                player_number=opponent.player_number,
                dev_played=False,
                ignore_affordability=True,
                ignore_opponents=True,
            )

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
            best_hex = random.choice(valid_hexes)

        # Choose who to steal from on the chosen hex (more resources + more VP = better target).
        players_on_best_hex = [p for p in game.get_players_on_hex(best_hex) if p != player]
        if not players_on_best_hex:
            return best_hex, None

        best_player = max(
            players_on_best_hex,
            key=lambda pl: sum(pl.resources.values()) * pl.calc_victory_points()[0],
        )
        return best_hex, best_player

    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        """Select resources to discard, keeping critical ones for best next action."""
        have = player.resources.copy()

        # Estimate what we are trying to build next and protect those resources.
        sim_game = make_sim_game_for_player(game, player)
        best_action = self.etw_estimator.calculate_best_game_action(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=False,
        )

        needed = calc_step_resources(best_action)

        # Surplus = resources beyond what is needed for the next action.
        surplus = {r: max(0, have[r] - needed.get(r, 0)) for r in have}
        discard = {r: 0 for r in have}
        remaining = num_resources

        while remaining > 0:
            # Prefer discarding true surplus first, otherwise discard low-impact resources.
            # Ore and wheat are implicitly protected since they enable cities and dev cards.
            r = min(
                have.keys(),
                key=lambda x: (surplus[x] <= 0, have[x], x in (Resource.ORE, Resource.WHEAT)),
            )
            discard[r] += 1
            have[r] -= 1

            if surplus[r] > 0:
                surplus[r] -= 1

            remaining -= 1

        return discard

    def select_year_of_plenty_resources(self, player: Player, game: Game) -> ResourceCount:
        """Select the most-needed resources for the player's next action."""
        # Look ahead to what we want to build next.
        sim_game = make_sim_game_for_player(game, player)
        best_action = self.etw_estimator.calculate_best_game_action(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=False,
        )

        needed = calc_step_resources(best_action)

        # Rank resources by how short we are relative to the next action's cost.
        sorted_needed = sorted(
            needed,
            key=lambda r: max(0, needed[r] - player.resources[r]),
            reverse=True,
        )

        # Take the two most constraining resources, fall back to anything if fewer are needed.
        picked = (
                sorted_needed[:2]
                + [r for r in Resource if r not in sorted_needed][: max(0, 2 - len(sorted_needed))]
        )

        return {r: 1 for r in picked[:2]}

    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        """Select the resource that will most hurt opponents based on their likely next actions."""

        # Count how often each resource appears in opponents' next planned actions.
        need_counts: Dict[Resource, int] = {r: 0 for r in Resource}

        for opponent in game.players:
            if opponent == player:
                continue

            # Estimate what the opponent is trying to do next.
            sim_game_opp = make_sim_game_for_player(game, opponent)
            best_action = self.etw_estimator.calculate_best_game_action(
                sim_game=sim_game_opp,
                player_number=opponent.player_number,
                dev_played=False,
                ignore_affordability=True,
                ignore_opponents=True,
            )

            # Tally required resources for that action.
            required = calc_step_resources(best_action)
            for r, amt in required.items():
                if amt > 0:
                    need_counts[r] += 1

        # Pick the resource most commonly needed across opponents.
        max_count = max(need_counts.values())
        candidates = [r for r, c in need_counts.items() if c == max_count]
        return random.choice(candidates)

    def respond_to_trade(
        self,
        player: Player,
        game: Game,
        opponent: Player,
        selling: ResourceCount,
        buying: ResourceCount,
    ) -> Tuple[bool, Optional[ResourceCount]]:
        """Respond to a proposed trade using BATNA + risk constraints."""

        # Evaluate the offer in a simulated state.
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)

        # Represent the proposer as a hidden-information opponent for conservative scoring.
        opponent_sim = SimPlayerState(opponent, opponent=True)
        opponents = get_opponents(sim_game, player.player_number)

        # Accept if it improves our ETW versus waiting/bank trades, but avoid helping a close/leading opponent.
        return respond_to_trade_batna(
            player_sim=sim_us,
            opponent_sim=opponent_sim,
            sim_game=sim_game,
            etw_estimator=self.etw_estimator,
            selling_to_us=selling,
            buying_from_us=buying,
            opponents=opponents,
        )

    def road_building_placement(self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
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
                key=lambda v: self.vertex_utility(v, player, game, legal_vertices, first_settlement=False),
                default=None,
            )
            if best_vertex:
                return find_edge_toward_vertex_from_any(
                    player.player_number,
                    sim_game,
                    best_vertex,
                    available_edges,
                )

        # Fallback: keep the agent moving even if no clear preference exists.
        return random.choice(available_edges) if available_edges else None

    def next_action_with_explanation(self, player: Player, game: Game, phase: Phase, dev_played: bool
                                     ) -> Tuple[Action, ActionExplanation]:
        """Determine the next action and return a structured explanation."""
        if phase == Phase.PRE_ROLL:
            if not dev_played:
                sim_game = make_sim_game_for_player(game, player)
                sim_us = sim_game.overlay.get_sim_player(player.player_number)

                dev_candidates = play_development_card_action(sim_us, sim_game)

                if dev_candidates:
                    etw_before = self.etw_estimator.estimated_time_to_win(sim_us.copy(), sim_game, dev_played)

                    opponents_etw_before: Dict[PlayerNumber, float] = {
                        opp.player_number: self.etw_estimator.estimated_time_to_win(opp.copy(), sim_game, False)
                        for opp in get_opponents(sim_game, player.player_number)
                    }

                    explained_candidates = self.etw_estimator.evaluate_candidates_with_explanations(
                        sim_us,
                        sim_game,
                        dev_played,
                        dev_candidates,
                        etw_before,
                        opponents_etw_before,
                    )

                    if explained_candidates:
                        best_candidate = explained_candidates[0]
                        if best_candidate.utility_total > 0.0:
                            confidence = best_candidate.utility_total - (
                                explained_candidates[1].utility_total if len(explained_candidates) > 1 else 0.0
                            )
                            explanation = ActionExplanation(
                                chosen_action=best_candidate.action,
                                chosen_candidate=best_candidate,
                                alternatives=explained_candidates[1:4],
                                confidence=max(0.0, confidence),
                                confidence_label=self.etw_estimator.confidence_label(max(0.0, confidence)),
                                assumptions=[
                                    "Pre-roll explanation is based on available development-card candidates only."
                                ],
                                metadata={"phase": "pre_roll"},
                            )
                            return best_candidate.action, explanation

            roll_action = Action(ActionType.ROLL)
            explanation = ActionExplanation(
                chosen_action=roll_action,
                chosen_candidate=CandidateExplanation(
                    action=roll_action,
                    full_plan=[roll_action],
                    reasons_for=[
                        Reason(
                            type=ReasonType.HEURISTIC_CHOICE,
                            label="No beneficial pre-roll development-card play was identified",
                            value=0.0,
                        )
                    ],
                ),
                alternatives=[],
                confidence=0.0,
                confidence_label="medium",
                assumptions=[],
                metadata={"phase": "pre_roll"},
            )
            return roll_action, explanation

        sim_game = make_sim_game_for_player(game, player)

        explanation = self.etw_estimator.calculate_best_game_action_with_explanation(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=dev_played,
        )

        best_action = explanation.chosen_action

        if best_action.type == ActionType.TRADE_WITH_PLAYER:
            self.etw_estimator._last_trade_proposed = True
            self.etw_estimator._last_trade_resources = player.resources.copy()
        else:
            self.etw_estimator._last_trade_proposed = False
            self.etw_estimator._last_trade_resources = None

        return best_action, explanation

    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        """Determine the next action to take for the current phase of the game."""
        action, _ = self.next_action_with_explanation(player, game, phase, dev_played)
        return action
