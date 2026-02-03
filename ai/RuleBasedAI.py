import random
from typing import Optional, List, Dict, Tuple

from ai.AI import AI
from ai.ai_utils.EtwEstimator import EtwEstimator
from ai.ai_utils.SimGame import SimGame
from ai.ai_utils.SimPlayerState import SimPlayerState, dice_probability
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
from ai.ai_utils.resource_utils import calc_step_resources
from ai.ai_utils.trade_utils import respond_to_trade_batna, select_best_trade_partner
from config.StrategyWeights import StrategyWeights
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex


def _make_sim_game_for_player(game: Game, player: Player) -> SimGame:
    """Create a SimGame and ensure `player` is a full-information SimPlayerState in the overlay."""
    sim_game = SimGame.from_real_game(game, hide_opponent_dev_cards=True)

    sim_us = SimPlayerState(player, opponent=False)
    overlay2 = sim_game.overlay.copy()
    overlay2.set_sim_player(sim_us)

    return SimGame(game=sim_game.game, overlay=overlay2)


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

        first_settlement = len(player.settlements) == 0

        best_vertex = max(
            available_vertices,
            key=lambda v: self._vertex_utility(v, player, game, available_vertices, first_settlement),
            default=None,
        )
        return best_vertex

    def select_initial_road_location(
        self,
        player: Player,
        game: Game,
        available_edges: List[Edge],
    ) -> Optional[Edge]:
        """Return the best initial road edge connecting settlements or toward high-utility vertices."""
        if not available_edges:
            return None

        if len(player.settlements) + len(player.cities) >= 2:
            return self.road_building_placement(player, game, available_edges)

        current_settlement = player.settlements[-1]

        sim_game = _make_sim_game_for_player(game, player)
        legal_vertices = get_legal_settlement_vertices(sim_game)

        if len(player.settlements) == 1:
            best_vertex = max(
                legal_vertices,
                key=lambda v: self._vertex_utility(v, player, game, legal_vertices, first_settlement=False),
                default=None,
            )
            if best_vertex:
                return find_edge_toward_vertex(current_settlement, best_vertex, available_edges)
        else:
            first_settlement = player.settlements[0]

            for edge in available_edges:
                other_vertex = edge.get_other_vertex(current_settlement)
                if moves_toward_vertex(other_vertex, first_settlement):
                    return edge

            best_vertex = max(
                legal_vertices,
                key=lambda v: self._vertex_utility(v, player, game, legal_vertices, first_settlement=False),
                default=None,
            )
            if best_vertex:
                return find_edge_toward_vertex(current_settlement, best_vertex, available_edges)

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

        dice_sum = sum(dice_probability(h.production_number) for h in hexes)

        resources = {h.resource for h in hexes if h.resource is not None}
        diversity = len(resources)

        sim_game = _make_sim_game_for_player(game, player)

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
            first_resources = set()
            for s in player.settlements:
                first_resources.update({h.resource for h in s.hexes if h.resource is not None})
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
        sim_game = _make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)

        available_sim_players = [(SimPlayerState(p, opponent=True), offer) for (p, offer) in available_players]

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

        our_resource_tiles = {h for v in (player.settlements + player.cities) for h in v.hexes}

        sim_game_for_robber = _make_sim_game_for_player(game, player)

        opponent_importance: Dict[PlayerNumber, Dict[Resource, float]] = {}
        for opponent in game.players:
            if opponent == player:
                continue

            sim_game_opp = _make_sim_game_for_player(game, opponent)
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
                ) * p.calc_victory_points()[0]

            score *= dice_probability(h.production_number)

            if h in our_resource_tiles:
                score *= StrategyWeights.ROBBER_OWN_HEX_PENALTY

            if score > best_score:
                best_score = score
                best_hex = h

        if best_hex is None:
            best_hex = random.choice(valid_hexes)

        players_on_best_hex = [p for p in game.get_players_on_hex(best_hex) if p != player]
        if not players_on_best_hex:
            return best_hex, None

        best_player = max(players_on_best_hex, key=lambda pl: sum(pl.resources.values()) * pl.calc_victory_points()[0])
        return best_hex, best_player

    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        """Select resources to discard, keeping critical ones for best next action."""
        have = player.resources.copy()

        sim_game = _make_sim_game_for_player(game, player)
        best_action = self.etw_estimator.calculate_best_game_action(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=False,
        )

        needed = calc_step_resources(best_action)
        surplus = {r: max(0, have[r] - needed.get(r, 0)) for r in have}
        discard = {r: 0 for r in have}
        remaining = num_resources

        while remaining > 0:
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
        sim_game = _make_sim_game_for_player(game, player)
        best_action = self.etw_estimator.calculate_best_game_action(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=False,
        )
        needed = calc_step_resources(best_action)

        sorted_needed = sorted(needed, key=lambda r: max(0, needed[r] - player.resources[r]), reverse=True)
        picked = sorted_needed[:2] + [r for r in Resource if r not in sorted_needed][:max(0, 2 - len(sorted_needed))]
        return {r: 1 for r in picked[:2]}

    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        """Select the resource that will most hurt opponents based on their likely next actions."""
        need_counts: Dict[Resource, int] = {r: 0 for r in Resource}

        for opponent in game.players:
            if opponent == player:
                continue

            sim_game_opp = _make_sim_game_for_player(game, opponent)
            best_action = self.etw_estimator.calculate_best_game_action(
                sim_game=sim_game_opp,
                player_number=opponent.player_number,
                dev_played=False,
                ignore_affordability=True,
                ignore_opponents=True,
            )

            required = calc_step_resources(best_action)
            for r, amt in required.items():
                if amt > 0:
                    need_counts[r] += 1

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
        sim_game = _make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)

        opponent_sim = SimPlayerState(opponent, opponent=True)
        opponents = get_opponents(sim_game, player.player_number)

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
        sim_game = _make_sim_game_for_player(game, player)

        connecting_edge = find_gap_connection(player.player_number, sim_game, available_edges)
        if connecting_edge:
            return connecting_edge

        legal_vertices = get_legal_settlement_vertices(sim_game)
        if legal_vertices:
            best_vertex = max(
                legal_vertices,
                key=lambda v: self._vertex_utility(v, player, game, legal_vertices, first_settlement=False),
                default=None,
            )
            if best_vertex:
                return find_edge_toward_vertex_from_any(player.player_number, sim_game, best_vertex, available_edges)

        return random.choice(available_edges) if available_edges else None

    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        """Determine the next action to take for the current phase of the game."""
        if phase == Phase.PRE_ROLL:
            return Action(ActionType.ROLL)

        sim_game = _make_sim_game_for_player(game, player)

        best_action = self.etw_estimator.calculate_best_game_action(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=dev_played,
        )

        if best_action.type == ActionType.TRADE_WITH_PLAYER:
            self.etw_estimator._last_trade_proposed = True
            self.etw_estimator._last_trade_resources = player.resources.copy()
        else:
            self.etw_estimator._last_trade_proposed = False
            self.etw_estimator._last_trade_resources = None

        return best_action
