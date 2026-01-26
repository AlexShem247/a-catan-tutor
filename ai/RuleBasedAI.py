import random

from ai.AI import AI
from ai.RandomAI import RandomAI
from ai.actions import Phase
from ai.heuristics import *
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
        """First settlement: road toward the best legal vertex. Second: try to connect."""
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
        best_score = float("-inf")
        best_hex: Optional[HexTile] = None

        # All hexes we touch (for penalty)
        our_resource_tiles = {h for v in (player.settlements + player.cities) for h in v.hexes}

        # Compute opponent importance
        opponent_importance: Dict[Player, Dict[Resource, float]] = {}
        for opponent in game.players:
            if opponent == player:
                continue

            best_action = self.calculate_best_main_game_action(SimPlayerState(opponent), game, False,
                                                               ignore_affordability=True, ignore_opponents=True)

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
                score *= Weight.ROBBER_OWN_HEX_PENALTY

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
        best_action = self.calculate_best_main_game_action(SimPlayerState(player), game, False)
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
        """Select the two most-needed resources for the player's next action."""
        best_action = self.calculate_best_main_game_action(SimPlayerState(player), game, False)
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

            best_action = self.calculate_best_main_game_action(
                SimPlayerState(opponent), game, False,
                ignore_affordability=True, ignore_opponents=True
            )

            required = calc_step_resources(best_action)
            for r, amt in required.items():
                if amt > 0:
                    need_counts[r] += 1  # Count how many opponents need this resource

        # Pick the resource needed by the most opponents (tie-break randomly)
        max_count = max(need_counts.values())
        candidates = [r for r, c in need_counts.items() if c == max_count]
        return random.choice(candidates)

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
                            candidates: List[Tuple[List[Action], float, float]], etw_before: float,
                            opponents_etw_before: Dict[SimPlayerState, float]) \
            -> List[Tuple[Action, float]]:

        self._eval_stats["evaluations"] += 1

        utilities = []

        # Sort candidates by ETB for early pruning
        candidates.sort(key=lambda x: x[1])

        # Only evaluate top N candidates
        max_eval = min(MAX_EVALUATIONS, len(candidates))

        for actions, etb, _ in candidates[:max_eval]:
            # Skip actions that take too long
            if etb > MAX_ETB_THRESHOLD:
                continue

            step = actions[0]
            player_copy = player.copy()
            simulate_step(player_copy, game, step)

            # Use cached ETW with reduced simulation depth
            etw_after = estimated_time_to_win(
                player_copy, SimGame(player_copy, game), dev_played,
            )

            # Self Utility Calculation
            if etw_before == 0:
                u_self = 0
            else:
                u_self = max(0.0, (etw_before - etw_after) / etw_before * 100)

            # Opponent-Interference Utility Calculation
            u_opp = 0.0
            leading_opponent = None if not opponents_etw_before else \
                min(opponents_etw_before, key=opponents_etw_before.get)
            for opponent, opponent_etw_before in opponents_etw_before.items():
                opponent_etw_after = estimated_time_to_win(
                    opponent, SimGame(player_copy, game), False,
                )
                if opponent_etw_before == 0:
                    delay_caused = 0
                else:
                    delay_caused = max(0.0, (opponent_etw_after - opponent_etw_before) / opponent_etw_before * 100)

                if opponent == leading_opponent:
                    u_opp += Weight.OPPONENT_INTERFERENCE_LEADING * delay_caused
                else:
                    u_opp += (1 - Weight.OPPONENT_INTERFERENCE_LEADING) / 2 * delay_caused

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
            eu = ((Weight.BUILD_SELF_UTILITY * u_self + Weight.BUILD_OPPONENT_UTILITY * u_opp +
                   Weight.BUILD_SPECIAL_UTILITY * u_special) /
                  ((1 + discount_rate) ** max(1.0, etb)))  # Ensure at least 1 to avoid division by 0

            utilities.append((step, eu))

        return utilities

    def calculate_best_main_game_action(self, sim_player: SimPlayerState, game: Game, dev_played: bool,
                                        ignore_affordability: bool = False, ignore_opponents: bool = False) \
            -> Action:
        # Main Phase
        etw_before = estimated_time_to_win(
            sim_player.copy(), SimGame(sim_player, game), dev_played,
        )

        opponents_etw_before: Dict[SimPlayerState, float] = {}
        if not ignore_opponents:
            for opponent in get_opponents(sim_player, game):
                opponents_etw_before[opponent] = estimated_time_to_win(
                    opponent.copy(), SimGame(sim_player, game), False,
                )

        # Get limited candidate actions
        candidates = get_candidate_actions(
            sim_player, SimGame(sim_player, game), dev_played,
        )

        if not candidates:
            return Action(ActionType.END_TURN)

        utilities = self._evaluate_utilities(sim_player, game, dev_played, candidates, etw_before, opponents_etw_before)

        if not utilities:
            return Action(ActionType.END_TURN)

        best_action = choose_max_utility_action(sim_player, utilities, ignore_affordability=ignore_affordability)

        return best_action

    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        if phase == Phase.PRE_ROLL:
            return Action(ActionType.ROLL)

        # Main Phase
        best_action = self.calculate_best_main_game_action(SimPlayerState(player), game, dev_played)

        return best_action

    def road_building_placement(self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
        """Place road: connect gaps first, otherwise build toward the best settlement."""

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
