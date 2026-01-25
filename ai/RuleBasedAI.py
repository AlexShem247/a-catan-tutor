import random
from typing import Tuple, Optional, List

from ai.AI import AI
from ai.RandomAI import RandomAI
from ai.SimPlayerState import SimPlayerState
from ai.actions import Phase, Action, ActionType
from ai.heuristics import dice_probability, get_reachable_vertices, simulate_step, \
    estimated_time_to_win, get_candidate_actions, choose_max_utility_action, get_opponents, EPSILON
from config.Weight import Weight
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex


class RuleBasedAI(AI):
    def __init__(self):
        self.random_policy = RandomAI()
        self._eval_stats = {"cache_hits": 0, "cache_misses": 0, "evaluations": 0}

    def select_initial_settlement_location(self, player: Player, game: Game, available_vertices: List[Vertex]) \
            -> Optional[Vertex]:
        """Choose initial settlement location based on settlement utility formula."""
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
        """Choose the initial road that moves toward the highest-utility settlement vertex."""
        return self.random_policy.select_initial_road_location(player, game, available_edges)

    def _vertex_utility(
            self,
            vertex: Vertex,
            player: Player,
            game: Game,
            available_vertices: List[Vertex],
            first_settlement: bool = True,
    ) -> float:
        """Compute utility of a vertex for initial placement (settlement or target road vertex)."""
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
                Weight.INIT_PLACE_YIELD * dice_sum +
                Weight.INIT_PLACE_DIVERSITY * diversity -
                Weight.INIT_PLACE_BLOCK * blocking_penalty
        )

        # For second settlement: boost if adds new resource types
        if not first_settlement:
            first_resources = set()
            for s in player.settlements:
                first_resources.update({h.resource for h in s.hexes if h.resource is not None})
            combined_diversity = len(resources | first_resources)
            utility += Weight.INIT_PLACE_DIVERSITY * (combined_diversity - diversity)

        return utility

    def choose_trade_partner(self, player: Player, game: Game,
                             available_players: List[Tuple[Player, Optional[ResourceCount]]]) \
            -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        return self.random_policy.choose_trade_partner(player, game, available_players)

    def select_robber_target(self, player: Player, game: Game, valid_hexes: List[HexTile]) \
            -> Tuple[HexTile, Optional[Player]]:
        # 1. Score each valid hex
        best_score = -1
        best_hex = None
        our_resource_tiles = {h for v in player.settlements + player.cities for h in v.hexes}

        for h in valid_hexes:
            # Players on this hex
            players_on_h = [p for p in game.get_players_on_hex(h) if p != player]
            score = 0.0
            for p in players_on_h:
                # Dummy I(): always 1
                # TODO: Replace with indicator function based on inferred opponent needs
                score += p.calc_victory_points()[0] * 1
            # Multiply by dice probability
            score *= dice_probability(h.production_number)

            # Tie-breaking: prefer hex we do not occupy
            if h in our_resource_tiles:
                score *= Weight.ROBBER_OWN_HEX_PENALTY

            if score > best_score:
                best_score = score
                best_hex = h

        if best_hex is None:
            best_hex = random.choice(valid_hexes)

        # 2. Choose player to steal from
        players_on_best_hex = [p for p in game.get_players_on_hex(best_hex) if p != player]

        if not players_on_best_hex:
            return best_hex, None

        # Pick player with most cards weighted by VP
        best_player = max(
            players_on_best_hex,
            key=lambda pl: sum(p.resources.values()) * pl.calc_victory_points()[0]
        )

        return best_hex, best_player

    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        return self.random_policy.select_discard_resources(player, game, num_resources)

    def select_year_of_plenty_resources(self, player: Player, game: Game) -> ResourceCount:
        return self.random_policy.select_year_of_plenty_resources(player, game)

    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        return self.random_policy.select_monopoly_resource(player, game)

    def respond_to_trade(self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount) \
            -> Tuple[bool, Optional[ResourceCount]]:
        return self.random_policy.respond_to_trade(player, game, selling, buying)

    def _compute_k_lr(self, player: SimPlayerState, game: Game) -> float:
        """Compute scaling factor for Longest Road priority."""
        vp = player.victory_points()
        f_phase = min(vp / 10.0, 1.0)
        my_len = player.longest_road_length
        opponent_best = max([p.longest_road_length for p in get_opponents(player, game)], default=0)

        # Target length needed to claim / retain Longest Road
        longest_road = max(my_len, opponent_best)
        target = max(Weight.LR_MIN_ROAD_LENGTH, longest_road + 1)
        dist = max(0, target - my_len)
        f_dist = 1.0 / (1.0 + dist)
        gap = my_len - opponent_best
        f_contest = 1.0 / (1.0 + max(gap, 0) + EPSILON)

        k = Weight.LR_BASE + Weight.LR_PHASE * f_phase + Weight.LR_DISTANCE * f_dist + Weight.LR_CONTEST * f_contest
        return max(k, 0.0)

    def _compute_k_la(self, player: SimPlayerState, game: Game) -> float:
        """Compute scaling factor for Largest Army priority."""
        vp = player.victory_points()
        f_phase = min(vp / 10.0, 1.0)

        my_knights = player.army_size
        opponent_best = max([p.army_size for p in get_opponents(player, game)], default=0)

        # Target number of knights needed to claim / retain Largest Army
        largest_army = max(my_knights, opponent_best)
        target = max(Weight.LA_MIN_KNIGHTS, largest_army + 1)
        dist = max(0, target - my_knights)
        f_dist = 1.0 / (1.0 + dist)

        gap = my_knights - opponent_best
        f_contest = 1.0 / (1.0 + max(gap, 0) + EPSILON)

        k = Weight.LA_BASE + Weight.LA_PHASE * f_phase + Weight.LA_KNIGHT_DIST * f_dist + Weight.LA_CONTEST * f_contest
        return max(k, 0.0)

    def _evaluate_utilities(self, player: SimPlayerState, game: Game, dev_played: bool,
                            candidates: List[Tuple[List[Action], float, float]], etw_before: float) \
            -> List[Tuple[Action, float]]:

        self._eval_stats["evaluations"] += 1

        utilities = []

        # Sort candidates by ETB for early pruning
        candidates.sort(key=lambda x: x[1])

        # Only evaluate top N candidates
        max_eval = min(Weight.MAX_EVALUATIONS, len(candidates))

        for actions, etb, _ in candidates[:max_eval]:
            # Skip actions that take too long
            if etb > Weight.MAX_ETB_THRESHOLD:
                continue

            step = actions[0]
            player_copy = player.copy()
            simulate_step(player_copy, game, step)

            # Use cached ETW with reduced simulation depth
            etw_after = estimated_time_to_win(
                player_copy, game, dev_played,
                max_iterations=Weight.MAX_ETW_SIMULATION_DEPTH_SHALLOW
            )

            # Self Utility Calculation
            if etw_before == 0:
                u_self = 0
            else:
                u_self = max(0.0, (etw_before - etw_after) / etw_before * 100)

            # Special Calculation
            u_special = 0.0
            if step.type == ActionType.BUILD and step.payload[0] == Buildable.ROAD:
                # Only consider LR if we're close to the threshold
                if player.longest_road_length >= Weight.LR_ROAD_THRESHOLD:
                    delta = max(0, player_copy.longest_road_length - player.longest_road_length)
                    u_special += Weight.LR_UTILITY_MULTIPLIER * delta

            if step.type == ActionType.PLAY_DEV_CARD and step.payload == DevelopmentCardType.KNIGHT:
                # Only if we're close to the largest army
                if player.army_size >= Weight.LA_ARMY_THRESHOLD:
                    delta_knight = 1
                    u_special += self._compute_k_la(player_copy, game) * delta_knight

            # Discount for time: ETB of the action itself
            discount_rate = Weight.TIME_DISCOUNT_RATE  # Use weight for discount rate
            eu = ((Weight.BUILD_SELF_UTILITY * u_self + Weight.BUILD_SPECIAL_UTILITY * u_special) /
                  ((1 + discount_rate) ** max(1.0, etb)))  # Ensure at least 1 to avoid division by 0

            utilities.append((step, eu))

        return utilities

    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        if phase == Phase.PRE_ROLL:
            return Action(ActionType.ROLL)

        # Main Phase
        sim_player = SimPlayerState(player)
        etw_before = estimated_time_to_win(
            sim_player.copy(), game, dev_played,
            max_iterations=Weight.MAX_ETW_SIMULATION_DEPTH_DEEP
        )

        # Get limited candidate actions
        candidates = get_candidate_actions(
            sim_player, game, dev_played,
            max_candidates=Weight.MAX_CANDIDATES_GENERATE
        )

        if not candidates:
            return Action(ActionType.END_TURN)

        utilities = self._evaluate_utilities(sim_player, game, dev_played, candidates, etw_before)

        if not utilities:
            return Action(ActionType.END_TURN)

        best_action = choose_max_utility_action(player, utilities)

        return best_action
