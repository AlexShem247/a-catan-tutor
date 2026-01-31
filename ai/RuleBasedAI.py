import random
from typing import Optional, List, Dict, Tuple

from ai.AI import AI
from ai.ai_utils.EtwEstimator import EtwEstimator
from ai.ai_utils.SimPlayerState import SimPlayerState, dice_probability, SimGame
from ai.ai_utils.actions import Phase, ActionType, Action
from ai.ai_utils.board_sim_utils import get_legal_settlement_vertices, find_edge_toward_vertex, moves_toward_vertex, \
    get_reachable_vertices, score_hex_for_opponent, find_gap_connection, find_edge_toward_vertex_from_any, get_opponents
from ai.ai_utils.resource_utils import calc_step_resources
from ai.ai_utils.trade_utils import respond_to_trade_batna, select_best_trade_partner
from config.StrategyWeights import StrategyWeights
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex


class RuleBasedAI(AI):
    def __init__(self):
        self.etw_estimator = EtwEstimator()

    def new_turn(self):
        self.etw_estimator.new_turn()

    def select_initial_settlement_location(self, player: Player, game: Game, available_vertices: List[Vertex]) \
            -> Optional[Vertex]:
        """Return the best initial settlement vertex based on utility evaluation."""
        if not available_vertices:
            return None

        first_settlement = len(player.settlements) == 0

        # Pick the vertex with the highest utility
        best_vertex = max(
            available_vertices,
            key=lambda v: self._vertex_utility(v, player, game, available_vertices, first_settlement),
            default=None
        )
        return best_vertex

    def select_initial_road_location(self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
        """Return the best initial road edge connecting settlements or toward high-utility vertices."""
        if not available_edges:
            return None

        if len(player.settlements) + len(player.cities) >= 2:
            return self.road_building_placement(player, game, available_edges)

        current_settlement = player.settlements[-1]

        # Get all legal settlement vertices on the board
        legal_vertices = get_legal_settlement_vertices(game)

        if len(player.settlements) == 1:
            # FIRST SETTLEMENT: Find the best legal vertex, build road toward it
            best_vertex = max(
                legal_vertices,
                key=lambda v: self._vertex_utility(v, player, game, legal_vertices, first_settlement=False),
                default=None
            )

            if best_vertex:
                # Find which available edge gets us closest to this best vertex
                return find_edge_toward_vertex(current_settlement, best_vertex, available_edges)

        else:
            # SECOND SETTLEMENT: Try to connect to first settlement
            first_settlement = player.settlements[0]

            # Check if any available edge helps connect to first settlement
            for edge in available_edges:
                other_vertex = edge.get_other_vertex(current_settlement)

                # Check if this edge moves us toward first settlement
                if moves_toward_vertex(other_vertex, first_settlement):
                    return edge

            # If no connection possible, build toward the best legal vertex (same as first)
            best_vertex = max(
                legal_vertices,
                key=lambda v: self._vertex_utility(v, player, game, legal_vertices, first_settlement=False),
                default=None
            )

            if best_vertex:
                return find_edge_toward_vertex(current_settlement, best_vertex, available_edges)

        # Fallback
        return random.choice(available_edges) if available_edges else None

    def _vertex_utility(
            self,
            vertex: Vertex,
            player: Player,
            game: Game,
            available_vertices: List[Vertex],
            first_settlement: bool = True,
    ) -> float:
        """Compute utility score for a vertex as a potential settlement location."""
        hexes = vertex.hexes
        if not hexes:
            return float("-inf")

        # Dice probability sum
        dice_sum = sum(dice_probability(h.production_number) for h in hexes)

        # Resource diversity
        resources = {h.resource for h in hexes if h.resource is not None}
        diversity = len(resources)

        # Blocking penalty (1 if no opponent can reach, 0 otherwise)
        blocking_penalty = 1.0
        for opp in game.players:
            if opp == player:
                continue
            for opp_v in opp.settlements:
                if vertex in get_reachable_vertices(opp_v, opp, available_vertices):
                    blocking_penalty = 0.0
                    break
            if blocking_penalty == 0.0:
                break

        utility = (
                StrategyWeights.INIT_PLACE_YIELD * dice_sum +
                StrategyWeights.INIT_PLACE_DIVERSITY * diversity -
                StrategyWeights.INIT_PLACE_BLOCK * blocking_penalty
        )

        # For second settlement: boost if adds new resource types
        if not first_settlement:
            first_resources = set()
            for s in player.settlements:
                first_resources.update({h.resource for h in s.hexes if h.resource is not None})
            combined_diversity = len(resources | first_resources)
            utility += StrategyWeights.INIT_PLACE_DIVERSITY * (combined_diversity - diversity)

        return utility

    def choose_trade_partner(self, player: Player, game: "Game", selling: ResourceCount, buying: ResourceCount,
                             available_players: List[Tuple[Player, Optional[ResourceCount]]],
                             ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        """Return the chosen trade partner using fallback random policy."""
        sim_player = SimPlayerState(player)
        selection = select_best_trade_partner(
            player_sim=sim_player,
            sim_game=SimGame(sim_player, game),
            etw_estimator=self.etw_estimator,
            selling_orig=selling,
            buying=buying,
            available_players=[(SimPlayerState(player), offer) for (player, offer) in available_players],
        )

        if selection is None:
            return None
        chosen_sim_player, counter = selection
        chosen_player = next(p for p in game.players if p.player_number == chosen_sim_player.player_number)

        return chosen_player, counter

    def select_robber_target(self, player: Player, game: Game, valid_hexes: List[HexTile]) \
            -> Tuple[HexTile, Optional[Player]]:
        """Select which hex tile to place the robber on, prioritising opponents' resources."""
        best_score = float("-inf")
        best_hex: Optional[HexTile] = None

        # All hexes we touch (for penalty)
        our_resource_tiles = {h for v in (player.settlements + player.cities) for h in v.hexes}

        # Compute opponent importance
        opponent_importance: Dict[Player, Dict[Resource, float]] = {}
        for opponent in game.players:
            if opponent == player:
                continue

            best_action = self.etw_estimator.calculate_best_game_action(
                SimPlayerState(opponent), game, False, ignore_affordability=True, ignore_opponents=True)

            required = calc_step_resources(best_action)
            total = sum(required.values())

            opponent_importance[opponent] = {res: amt / total for res, amt in required.items() if amt > 0} \
                if total > 0 else {}

        # Score each valid hex
        for h in valid_hexes:
            players_on_h = [p for p in game.get_players_on_hex(h) if p != player]

            if not players_on_h:
                continue

            score = 0.0
            for p in players_on_h:
                score += score_hex_for_opponent(p, game, h, opponent_importance[p]) * p.calc_victory_points()[0]

            # Weight by dice probability
            score *= dice_probability(h.production_number)

            # Penalise blocking ourselves
            if h in our_resource_tiles:
                score *= StrategyWeights.ROBBER_OWN_HEX_PENALTY

            if score > best_score:
                best_score = score
                best_hex = h

        # Fallback
        if best_hex is None:
            best_hex = random.choice(valid_hexes)

        # Pick steal target
        players_on_best_hex = [p for p in game.get_players_on_hex(best_hex) if p != player]

        if not players_on_best_hex:
            return best_hex, None

        best_player = max(players_on_best_hex, key=lambda pl: sum(pl.resources.values()) * pl.calc_victory_points()[0])
        return best_hex, best_player

    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        """Select resources to discard, keeping critical ones for best next action."""
        have = player.resources.copy()
        best_action = self.etw_estimator.calculate_best_game_action(SimPlayerState(player), game, False)
        needed = calc_step_resources(best_action)
        surplus = {r: max(0, have[r] - needed.get(r, 0)) for r in have}
        discard = {r: 0 for r in have}
        remaining = num_resources

        while remaining > 0:
            r = min(
                have.keys(),
                key=lambda x: (surplus[x] <= 0, have[x], x in (Resource.ORE, Resource.WHEAT))
            )
            discard[r] += 1
            have[r] -= 1
            if surplus[r] > 0:
                surplus[r] -= 1
            remaining -= 1

        return discard

    def select_year_of_plenty_resources(self, player: Player, game: Game) -> ResourceCount:
        """Select the most-needed resources for the player's next action."""
        best_action = self.etw_estimator.calculate_best_game_action(SimPlayerState(player), game, False)
        needed = calc_step_resources(best_action)
        # Sort resources by how much is still needed, descending
        sorted_needed = sorted(needed, key=lambda r: max(0, needed[r] - player.resources[r]), reverse=True)
        # Pick up to two, fill with any if less than two
        picked = sorted_needed[:2] + [r for r in Resource if r not in sorted_needed][:max(0, 2 - len(sorted_needed))]
        return {r: 1 for r in picked[:2]}

    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        """Select the resource that will most hurt opponents based on their likely next actions."""
        # Estimate resource needs for all opponents
        need_counts: Dict[Resource, int] = {r: 0 for r in Resource}
        for opponent in game.players:
            if opponent == player:
                continue

            best_action = self.etw_estimator.calculate_best_game_action(
                SimPlayerState(opponent), game, False, ignore_affordability=True, ignore_opponents=True)

            required = calc_step_resources(best_action)
            for r, amt in required.items():
                if amt > 0:
                    need_counts[r] += 1  # Count how many opponents need this resource

        # Pick the resource needed by the most opponents (tie-break randomly)
        max_count = max(need_counts.values())
        candidates = [r for r, c in need_counts.items() if c == max_count]
        return random.choice(candidates)

    def respond_to_trade(self, player: Player, game: "Game", opponent: Player, selling: ResourceCount,
                         buying: ResourceCount) -> Tuple[bool, Optional[ResourceCount]]:
        """Respond to a proposed trade using fallback random policy."""
        sim_player = SimPlayerState(player)
        return respond_to_trade_batna(
            player_sim=sim_player,
            opponent_sim=SimPlayerState(opponent),
            sim_game=SimGame(sim_player, game),
            etw_estimator=self.etw_estimator,
            selling_to_us=selling,
            buying_from_us=buying,
            opponents=get_opponents(sim_player, game),
        )

    def road_building_placement(self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
        """Select an edge for road building, prioritising network connections or high-utility settlements."""
        # 1. Try to connect disconnected parts of road network
        connecting_edge = find_gap_connection(player, available_edges)
        if connecting_edge:
            return connecting_edge

        # 2. Build toward the best potential settlement
        legal_vertices = get_legal_settlement_vertices(game)
        if legal_vertices:
            best_vertex = max(
                legal_vertices,
                key=lambda v: self._vertex_utility(v, player, game, legal_vertices, first_settlement=False),
                default=None
            )

            if best_vertex:
                # Find edge that moves toward the best vertex from any of our structures
                return find_edge_toward_vertex_from_any(player, best_vertex, available_edges)

        # 3. Random fallback
        return random.choice(available_edges) if available_edges else None

    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        """Determine the next action to take for the current phase of the game."""
        if phase == Phase.PRE_ROLL:
            return Action(ActionType.ROLL)

        # Main Phase
        best_action = self.etw_estimator.calculate_best_game_action(SimPlayerState(player), game, dev_played)

        # Keep track on success of player trades
        if best_action.type == ActionType.TRADE_WITH_PLAYER:
            self.etw_estimator._last_trade_proposed = True
            self.etw_estimator._last_trade_resources = player.resources.copy()
        else:
            self.etw_estimator._last_trade_proposed = False
            self.etw_estimator._last_trade_resources = None

        return best_action
