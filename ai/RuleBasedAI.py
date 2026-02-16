from random import Random
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
    def __init__(self, rng: Random, weights: Optional[StrategyWeights] = None):
        super().__init__(rng)
        self.w = weights if weights is not None else StrategyWeights()
        self.etw_estimator = EtwEstimator()

    def new_turn(self):
        self.etw_estimator.new_turn()

    def select_initial_settlement_location(
        self,
        player: Player,
        game: Game,
        available_vertices: List[Vertex],
    ) -> Optional[Vertex]:
        if not available_vertices:
            return None

        first_settlement = (len(player.settlements) == 0)

        return max(
            available_vertices,
            key=lambda v: self.vertex_utility(v, player, game, available_vertices, self.w, first_settlement),
            default=None,
        )

    def select_initial_road_location(
        self,
        player: Player,
        game: Game,
        available_edges: List[Edge],
    ) -> Optional[Edge]:
        if not available_edges:
            return None

        if len(player.settlements) + len(player.cities) >= 2:
            return self.road_building_placement(player, game, available_edges)

        current_settlement = player.settlements[-1]
        legal_vertices = get_legal_settlement_vertices(make_sim_game_for_player(game, player))

        if len(player.settlements) == 1:
            best_vertex = max(
                legal_vertices,
                key=lambda v: self.vertex_utility(v, player, game, legal_vertices, self.w, first_settlement=False),
                default=None,
            )
            if best_vertex:
                return find_edge_toward_vertex(current_settlement, best_vertex, available_edges)
        else:
            for edge in available_edges:
                other_vertex = edge.get_other_vertex(current_settlement)
                if moves_toward_vertex(other_vertex, player.settlements[0]):
                    return edge

            best_vertex = max(
                legal_vertices,
                key=lambda v: self.vertex_utility(v, player, game, legal_vertices, self.w, first_settlement=False),
                default=None,
            )
            if best_vertex:
                return find_edge_toward_vertex(current_settlement, best_vertex, available_edges)

        return self.rng.choice(available_edges) if available_edges else None

    @staticmethod
    def vertex_utility(
        vertex: Vertex,
        player: Player,
        game: Game,
        available_vertices: List[Vertex],
        weights: StrategyWeights,
        first_settlement: bool = True,
    ) -> float:
        if not vertex.hexes:
            return float("-inf")

        dice_sum = sum(dice_probability(h.production_number) for h in vertex.hexes)

        resources: List[Resource] = []
        for h in vertex.hexes:
            if h.resource is not None and h.resource not in resources:
                resources.append(h.resource)
        diversity = len(resources)

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
                if vertex in reachable:
                    blocking_penalty = 0.0
                    break

            if blocking_penalty == 0.0:
                break

        utility = (
            weights.INIT_PLACE_YIELD * dice_sum
            + weights.INIT_PLACE_DIVERSITY * diversity
            - weights.INIT_PLACE_BLOCK * blocking_penalty
        )

        if not first_settlement:
            first_resources: List[Resource] = []
            for s in player.settlements:
                for h in s.hexes:
                    if h.resource is not None and h.resource not in first_resources:
                        first_resources.append(h.resource)

            combined = list(resources)
            for r in first_resources:
                if r not in combined:
                    combined.append(r)
            combined_diversity = len(combined)
            utility += weights.INIT_PLACE_DIVERSITY * (combined_diversity - diversity)

        return utility

    def choose_trade_partner(
        self,
        player: Player,
        game: Game,
        selling: ResourceCount,
        buying: ResourceCount,
        available_players: List[Tuple[Player, Optional[ResourceCount]]],
    ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        available_sim_players = [(SimPlayerState(p, opponent=True), offer) for (p, offer) in available_players]

        selection = select_best_trade_partner(
            player_sim=sim_us,
            sim_game=sim_game,
            etw_estimator=self.etw_estimator,
            selling_orig=selling,
            buying=buying,
            available_players=available_sim_players,
            weights=self.w,
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
        best_score = float("-inf")
        best_hex: Optional[HexTile] = None

        our_resource_tiles: List[HexTile] = []
        for v in (player.settlements + player.cities):
            for h in v.hexes:
                if h not in our_resource_tiles:
                    our_resource_tiles.append(h)

        sim_game_for_robber = make_sim_game_for_player(game, player)

        our_vp = player.calc_victory_points()[0]
        opp_vps = [p.calc_victory_points()[0] for p in game.players if p != player]
        best_opp_vp = max(opp_vps, default=0)
        diversion_boost = self.w.DIVERSION_BOOST if our_vp >= best_opp_vp else 1.0

        opponent_importance: Dict[PlayerNumber, Dict[Resource, float]] = {}
        for opponent in game.players:
            if opponent == player:
                continue

            sim_game_opp = make_sim_game_for_player(game, opponent)
            best_action = self.etw_estimator.calculate_best_game_action(
                sim_game=sim_game_opp,
                player_number=opponent.player_number,
                dev_played=False,
                weights=self.w,
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
                ) * (p.calc_victory_points()[0] * diversion_boost)

            if h in our_resource_tiles:
                score *= self.w.ROBBER_OWN_HEX_PENALTY

            if score > best_score:
                best_score = score
                best_hex = h

        if best_hex is None:
            best_hex = self.rng.choice(valid_hexes)

        players_on_best_hex = [p for p in game.get_players_on_hex(best_hex) if p != player]
        if not players_on_best_hex:
            return best_hex, None

        best_player = max(
            players_on_best_hex,
            key=lambda pl: sum(pl.resources.values()) * pl.calc_victory_points()[0],
        )
        return best_hex, best_player

    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        have = player.resources.copy()

        sim_game = make_sim_game_for_player(game, player)
        best_action = self.etw_estimator.calculate_best_game_action(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=False,
            weights=self.w,
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
        sim_game = make_sim_game_for_player(game, player)
        best_action = self.etw_estimator.calculate_best_game_action(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=False,
            weights=self.w,
        )

        needed = calc_step_resources(best_action)

        sorted_needed = sorted(
            needed,
            key=lambda r: max(0, needed[r] - player.resources[r]),
            reverse=True,
        )

        picked = (
            sorted_needed[:2]
            + [r for r in Resource if r not in sorted_needed][: max(0, 2 - len(sorted_needed))]
        )

        return {r: 1 for r in picked[:2]}

    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        need_counts: Dict[Resource, int] = {r: 0 for r in Resource}

        for opponent in game.players:
            if opponent == player:
                continue

            sim_game_opp = make_sim_game_for_player(game, opponent)
            best_action = self.etw_estimator.calculate_best_game_action(
                sim_game=sim_game_opp,
                player_number=opponent.player_number,
                dev_played=False,
                weights=self.w,
                ignore_affordability=True,
                ignore_opponents=True,
            )

            required = calc_step_resources(best_action)
            for r, amt in required.items():
                if amt > 0:
                    need_counts[r] += 1

        max_count = max(need_counts.values())
        candidates = [r for r, c in need_counts.items() if c == max_count]
        return self.rng.choice(candidates)

    def respond_to_trade(
        self,
        player: Player,
        game: Game,
        opponent: Player,
        selling: ResourceCount,
        buying: ResourceCount,
    ) -> Tuple[bool, Optional[ResourceCount]]:
        sim_game = make_sim_game_for_player(game, player)
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
            weights=self.w,
        )

    def road_building_placement(self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
        sim_game = make_sim_game_for_player(game, player)

        connecting_edge = find_gap_connection(player.player_number, sim_game, available_edges)
        if connecting_edge:
            return connecting_edge

        legal_vertices = get_legal_settlement_vertices(sim_game)
        if legal_vertices:
            best_vertex = max(
                legal_vertices,
                key=lambda v: self.vertex_utility(v, player, game, legal_vertices, self.w, first_settlement=False),
                default=None,
            )
            if best_vertex:
                return find_edge_toward_vertex_from_any(
                    player.player_number,
                    sim_game,
                    best_vertex,
                    available_edges,
                )

        return self.rng.choice(available_edges) if available_edges else None

    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        if phase == Phase.PRE_ROLL:
            if not dev_played:
                sim_game = make_sim_game_for_player(game, player)
                sim_us = sim_game.overlay.get_sim_player(player.player_number)

                dev_candidates = play_development_card_action(sim_us, sim_game, self.w)

                if dev_candidates:
                    etw_before = self.etw_estimator.estimated_time_to_win(sim_us.copy(), sim_game, dev_played, self.w)

                    opponents_etw_before: Dict[PlayerNumber, float] = {
                        opp.player_number: self.etw_estimator.estimated_time_to_win(opp.copy(), sim_game, False, self.w)
                        for opp in get_opponents(sim_game, player.player_number)
                    }

                    utilities = self.etw_estimator.evaluate_utilities(
                        sim_us,
                        sim_game,
                        dev_played,
                        dev_candidates,
                        etw_before,
                        opponents_etw_before,
                        self.w,
                    )

                    if utilities:
                        best_dev_action, best_u = max(utilities, key=lambda x: x[1])
                        if best_u > 0.0:
                            return best_dev_action

            return Action(ActionType.ROLL)

        sim_game = make_sim_game_for_player(game, player)

        best_action = self.etw_estimator.calculate_best_game_action(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=dev_played,
            weights=self.w,
        )

        if best_action.type == ActionType.TRADE_WITH_PLAYER:
            self.etw_estimator._last_trade_proposed = True
            self.etw_estimator._last_trade_resources = player.resources.copy()
        else:
            self.etw_estimator._last_trade_proposed = False
            self.etw_estimator._last_trade_resources = None

        return best_action
