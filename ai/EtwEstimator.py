from typing import List, Tuple, Dict

from ai.SimPlayerState import SimPlayerState, dice_probability, SimGame
from ai.action_utils import compute_k_la, distant_settlement_candidates, purchase_development_card_action, \
    choose_max_utility_action, play_development_card_action
from ai.actions import ActionType, Action
from ai.board_sim_utils import get_opponents
from ai.resource_utils import expected_rolls_for_resource, get_bank_trade_ratio, calc_step_resources
from config.StrategyWeights import StrategyWeights
from config.performance_constants import ETW_MAX_DEPTH_OFFSET, MAX_ETB_THRESHOLD, MAX_EVALUATIONS, \
    MAX_SETTLEMENT_CANDIDATES, ROAD_ETB_THRESHOLD, ETW_ETB_THRESHOLD, ETW_SIMULATION_MAX_CANDIDATES
from game.Game import Game
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount


class EtwEstimator:
    def __init__(self):
        self._eval_stats = {"cache_hits": 0, "cache_misses": 0, "evaluations": 0}

    def estimated_time_to_build(self, player: SimPlayerState, R_target: ResourceCount) -> float:
        """Estimate ETB (expected time to build) for given resource target with caching."""
        target_key = tuple((r.value, R_target.get(r, 0)) for r in Resource)
        player_key = (
            player.player_number,
            tuple(v for v in player.settlements),
            tuple(v for v in player.cities)
        )
        cache_key = (player_key, target_key)

        if cache_key in player.etb_cache:
            return player.etb_cache[cache_key]

        # Get current resources
        current = {r: player.resources.get(r, 0) for r in Resource}

        # Calculate production rates
        production_rates = {
            r: expected_rolls_for_resource(player, r)
            for r in Resource
        }

        # Calculate deficits and excesses
        deficits, excesses = self._calculate_deficits_and_excesses(current, R_target)

        # Calculate trade-adjusted rolls
        trade_adjusted_rolls = self._calculate_trade_adjusted_rolls(
            deficits=deficits,
            excesses=excesses,
            production_rates=production_rates,
            trade_ratio_func=lambda r: get_bank_trade_ratio(player.settlements + player.cities, r)
        )

        # ETB = max of all resource times (parallel production)
        etb = max(trade_adjusted_rolls.values())

        # Cache result
        player.etb_cache[cache_key] = etb

        return etb

    def _estimated_time_to_win(self, player: SimPlayerState, sim_game: SimGame, dev_played: bool) -> float:
        """Estimate ETW (expected time to win) with caching, simulation, and early pruning."""

        # Create cache key
        cache_key = (
            player.player_number,
            dev_played,
            len(player.settlements),
            len(player.cities),
            len(player.roads),
            tuple((r.value, player.resources.get(r, 0)) for r in Resource)
        )

        # Check cache
        if cache_key in player.etw_cache:
            return player.etw_cache[cache_key]

        points = player.victory_points()
        if points >= Game.VICTORY_POINTS_TO_WIN:
            return 0.0

        etw = 0
        iterations = 0

        # Limit simulation depth based on current points
        max_depth = min(Game.VICTORY_POINTS_TO_WIN + ETW_MAX_DEPTH_OFFSET - points, ETW_MAX_DEPTH_OFFSET)

        # Use a copy for simulation
        sim_player = player.copy()

        while points < Game.VICTORY_POINTS_TO_WIN and iterations < max_depth:
            # Get candidates but limit number
            candidate_actions = self._get_candidate_actions(sim_player, sim_game, dev_played)

            if not candidate_actions:
                etw += StrategyWeights.ETW_NO_ACTION_PENALTY  # Large penalty if no actions
                break

            # Take the best candidate
            actions, etb, vp_inc = candidate_actions[0]

            # Early exit if ETB is very high
            if etb > ETW_ETB_THRESHOLD:
                etw += StrategyWeights.ETW_NO_ACTION_PENALTY
                break

            etw += etb
            points += vp_inc

            # Apply actions
            for step in actions:
                self._simulate_step(sim_player, sim_game.game, step)

            iterations += 1

        # Add penalty for remaining points needed
        if points < Game.VICTORY_POINTS_TO_WIN:
            etw += (Game.VICTORY_POINTS_TO_WIN - points) * StrategyWeights.ETW_MISSING_POINT_PENALTY

        # Cache result
        player.etw_cache[cache_key] = etw
        return etw

    def _calculate_deficits_and_excesses(self, current: ResourceCount, target: ResourceCount) \
            -> Tuple[Dict[Resource, int], Dict[Resource, int]]:
        """Compute deficits and excesses for each resource relative to a target."""
        deficits, excesses = {}, {}

        for resource in Resource:
            needed = target.get(resource, 0)
            have = current.get(resource, 0)

            if have >= needed:
                excesses[resource] = have - needed
                deficits[resource] = 0
            else:
                excesses[resource] = 0
                deficits[resource] = needed - have

        return deficits, excesses

    def _calculate_trade_adjusted_rolls(
            self,
            deficits: Dict[Resource, int],
            excesses: Dict[Resource, int],
            production_rates: Dict[Resource, float],
            trade_ratio_func
    ) -> Dict[Resource, float]:
        """Compute expected rolls for each resource adjusted by trading possibilities."""
        trade_adjusted = {}

        for resource_i in Resource:
            if deficits[resource_i] <= 0:
                trade_adjusted[resource_i] = 0.0
                continue

            # Direct production time
            direct_rolls = deficits[resource_i] * production_rates[resource_i]

            # Get trade ratio for converting to this resource
            trade_ratio = trade_ratio_func(resource_i)

            # Calculate Σ excess_rj / tradeRatio_j→i
            trade_savings = 0.0
            for resource_j in Resource:
                if resource_j == resource_i:
                    continue

                excess = excesses.get(resource_j, 0)
                if excess > 0:
                    # Convert excess of resource_j to resource_i via trading
                    resource_i_from_trade = excess / trade_ratio
                    time_saved = resource_i_from_trade * production_rates[resource_i]
                    trade_savings += time_saved

            # Apply formula: max(0, direct - savings)
            trade_adjusted[resource_i] = max(0.0, direct_rolls - trade_savings)

        return trade_adjusted

    def calc_etb_actions(self, player: SimPlayerState, total_actions: List[Action]) -> float:
        """Compute total ETB for a list of actions by summing resource costs."""
        total_resources: ResourceCount = {res: 0 for res in Resource}

        for action in total_actions:
            step_resources = calc_step_resources(action)
            for res, cost in step_resources.items():
                total_resources[res] = total_resources.get(res, 0) + cost

        # Compute ETB based on total resources
        return self.estimated_time_to_build(player, total_resources)

    def _get_candidate_actions(self, player: SimPlayerState, sim_game: SimGame, dev_played: bool) \
            -> List[Tuple[List[Action], float, float]]:
        """Generate and prune candidate actions, returning ETB and expected VP gain."""

        # Cache key
        cache_key = (
            player.player_number,
            dev_played,
            len(player.settlements),
            len(player.cities),
            len(player.roads),
            tuple((r.value, player.resources.get(r, 0)) for r in Resource)
        )

        if cache_key in player.candidate_cache:
            return player.candidate_cache[cache_key][:ETW_SIMULATION_MAX_CANDIDATES]

        candidate_actions: List[Tuple[List[Action], float, float]] = []

        # 1. Always consider city upgrades first (high impact, low ETB)
        if len(player.cities) < Buildable.CITY.max_on_board and player.settlements:
            city_etb = self.estimated_time_to_build(player, Game.BUILDING_COST[Buildable.CITY])
            # Only consider best N settlement locations for cities (by production)
            sorted_settlements = sorted(
                player.settlements,
                key=lambda settlement: sum(dice_probability(h.production_number) for h in settlement.hexes),
                reverse=True
            )[:StrategyWeights.MAX_SETTLEMENTS_FOR_CITY_UPGRADE]
            for s in sorted_settlements:
                candidate_actions.append(([Action(ActionType.BUILD, (Buildable.CITY, s))], city_etb, 1))

        # 2. Settlement candidates with distance limit
        settlement_candidates = distant_settlement_candidates(player, sim_game, self)
        # Sort by ETB and take top N
        settlement_candidates.sort(key=lambda x: x[1])
        candidate_actions.extend(settlement_candidates[:MAX_SETTLEMENT_CANDIDATES])

        # 3. Development cards - only consider if we're close to the largest army or need VP
        points_needed = Game.VICTORY_POINTS_TO_WIN - player.victory_points()
        if player.army_size >= 2 or points_needed <= 2:
            dev_card_actions = purchase_development_card_action(player, sim_game.game, self)
            candidate_actions.extend(dev_card_actions)

        # 4. Play development cards if available (only if not already played this turn)
        if not dev_played:
            play_cards = play_development_card_action(player, sim_game.game)
            candidate_actions.extend(play_cards)

        # 5. Consider buying roads only if we have excess resources or need for settlements
        if len(candidate_actions) < StrategyWeights.MIN_CANDIDATES_FOR_ROAD:
            road_cost = Game.BUILDING_COST[Buildable.ROAD]
            road_etb = self.estimated_time_to_build(player, road_cost)
            # Only add road if we can build it relatively quickly
            if road_etb < ROAD_ETB_THRESHOLD:
                # Find a legal road edge
                for v in player.settlements + player.cities:
                    for edge in v.edges:
                        if edge.owner is None:
                            candidate_actions.append((
                                [Action(ActionType.BUILD, (Buildable.ROAD, edge))],
                                road_etb,
                                0
                            ))
                            break
                    if candidate_actions and len(candidate_actions[-1][0]) > 0:
                        break

        # Sort by ETB and limit
        candidate_actions.sort(key=lambda x: x[1])

        # Cache result
        player.candidate_cache[cache_key] = candidate_actions

        return candidate_actions[:ETW_SIMULATION_MAX_CANDIDATES]

    def _evaluate_utilities(self, player: SimPlayerState, game: Game, dev_played: bool,
                            candidates: List[Tuple[List[Action], float, float]], etw_before: float,
                            opponents_etw_before: Dict[SimPlayerState, float]) \
            -> List[Tuple[Action, float]]:
        """Evaluate utility scores for candidate actions including ETW impact and special factors."""
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
            self._simulate_step(player_copy, game, step)

            # Use cached ETW with reduced simulation depth
            etw_after = self._estimated_time_to_win(
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
                opponent_etw_after = self._estimated_time_to_win(
                    opponent, SimGame(player_copy, game), False,
                )
                if opponent_etw_before == 0:
                    delay_caused = 0
                else:
                    delay_caused = max(0.0, (opponent_etw_after - opponent_etw_before) / opponent_etw_before * 100)

                if opponent == leading_opponent:
                    u_opp += StrategyWeights.OPPONENT_INTERFERENCE_LEADING * delay_caused
                else:
                    u_opp += (1 - StrategyWeights.OPPONENT_INTERFERENCE_LEADING) / 2 * delay_caused

            # Special Calculation
            u_special = 0.0
            if step.type == ActionType.BUILD and step.payload[0] == Buildable.ROAD:
                # Only consider LR if we're close to the threshold
                if player.longest_road_length >= StrategyWeights.LR_ROAD_THRESHOLD:
                    delta = max(0, player_copy.longest_road_length - player.longest_road_length)
                    u_special += StrategyWeights.LR_UTILITY_MULTIPLIER * delta

            if step.type == ActionType.PLAY_DEV_CARD and step.payload == DevelopmentCardType.KNIGHT:
                # Only if we're close to the largest army
                if player.army_size >= StrategyWeights.LA_ARMY_THRESHOLD:
                    delta_knight = 1
                    u_special += compute_k_la(player_copy, game) * delta_knight

            # Discount for time: ETB of the action itself
            discount_rate = StrategyWeights.TIME_DISCOUNT_RATE  # Use weight for discount rate
            eu = ((StrategyWeights.BUILD_SELF_UTILITY * u_self + StrategyWeights.BUILD_OPPONENT_UTILITY * u_opp +
                   StrategyWeights.BUILD_SPECIAL_UTILITY * u_special) /
                  ((1 + discount_rate) ** max(1.0, etb)))  # Ensure at least 1 to avoid division by 0

            utilities.append((step, eu))

        return utilities

    def calculate_best_game_action(self, sim_player: SimPlayerState, game: Game, dev_played: bool,
                                   ignore_affordability: bool = False, ignore_opponents: bool = False) \
            -> Action:
        """Select the single best action for the player based on ETW and utility evaluation."""
        etw_before = self._estimated_time_to_win(
            sim_player.copy(), SimGame(sim_player, game), dev_played,
        )

        opponents_etw_before: Dict[SimPlayerState, float] = {}
        if not ignore_opponents:
            for opponent in get_opponents(sim_player, game):
                opponents_etw_before[opponent] = self._estimated_time_to_win(
                    opponent.copy(), SimGame(sim_player, game), False,
                )

        # Get limited candidate actions
        candidates = self._get_candidate_actions(
            sim_player, SimGame(sim_player, game), dev_played,
        )

        if not candidates:
            return Action(ActionType.END_TURN)

        utilities = self._evaluate_utilities(sim_player, game, dev_played, candidates, etw_before, opponents_etw_before)

        if not utilities:
            return Action(ActionType.END_TURN)

        best_action = choose_max_utility_action(sim_player, utilities, ignore_affordability=ignore_affordability)

        return best_action

    def _simulate_step(self, player: SimPlayerState, game: Game, step: Action):
        """Simulate the effect of a single action on a player's game state."""
        if step.type == ActionType.BUILD:
            building, loc = step.payload
            if building == Buildable.ROAD:
                # Get opponent road lengths
                opp_roads = []
                for p in game.players:
                    if p.player_number != player.player_number:
                        opp_roads.append(p.longest_road_length)
                player.build_road(loc, opp_roads)
            elif building == Buildable.SETTLEMENT:
                player.build_settlement(loc)
            elif building == Buildable.CITY:
                player.build_city(loc)
        elif step.type == ActionType.PLAY_DEV_CARD:
            ctype = step.payload
            player.remove_card(ctype)
            if ctype == DevelopmentCardType.KNIGHT:
                # Get opponent army sizes
                opp_armies = []
                for p in game.players:
                    if p.player_number != player.player_number:
                        opp_armies.append(p.army_size)
                player.add_knight(opp_armies)
