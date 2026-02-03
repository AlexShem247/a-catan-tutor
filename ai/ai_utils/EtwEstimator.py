from typing import List, Tuple, Dict, Optional

from ai.ai_utils.SimGame import SimGame
from ai.ai_utils.SimPlayerState import SimPlayerState, dice_probability
from ai.ai_utils.action_utils import (
    compute_k_la,
    distant_settlement_candidates,
    purchase_development_card_action,
    play_development_card_action,
    get_bank_trade_for_action,
)
from ai.ai_utils.actions import ActionType, Action
from ai.ai_utils.board_sim_utils import get_opponents
from ai.ai_utils.resource_utils import get_bank_trade_ratio, calc_step_resources
from ai.ai_utils.trade_utils import propose_trade
from config.StrategyWeights import StrategyWeights
from config.performance_constants import (
    ETW_MAX_DEPTH_OFFSET,
    MAX_ETB_THRESHOLD,
    MAX_EVALUATIONS,
    MAX_SETTLEMENT_CANDIDATES,
    ROAD_ETB_THRESHOLD,
    ETW_ETB_THRESHOLD,
    ETW_SIMULATION_MAX_CANDIDATES, EVAL_UTIL_MAX_DEPTH,
)
from game.Game import Game
from game.Player import PlayerNumber
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount


def _sim_game_with_replaced_player(sim_game: SimGame, sim_player: SimPlayerState) -> SimGame:
    """Return a SimGame with one SimPlayerState replaced in the overlay."""
    overlay2 = sim_game.overlay.copy()
    overlay2.set_sim_player(sim_player)
    return SimGame(game=sim_game.game, overlay=overlay2)


class EtwEstimator:
    def __init__(self):
        self._eval_stats = {"cache_hits": 0, "cache_misses": 0, "evaluations": 0}
        self._last_trade_resources: Optional[ResourceCount] = None
        self._last_trade_proposed: bool = False

    def new_turn(self):
        """Clear previous turn trade info."""
        self._last_trade_proposed = False
        self._last_trade_resources = None

    def estimated_time_to_build(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        R_target: ResourceCount,
        include_player_trades: bool = True,
    ) -> float:
        """Estimate ETB for a resource target with caching."""
        target_key = tuple((r.value, R_target.get(r, 0)) for r in Resource)
        player_key = (player.player_number, tuple(player.settlements), tuple(player.cities))
        cache_key = (player_key, target_key, include_player_trades)

        if cache_key in player.etb_cache:
            return player.etb_cache[cache_key]

        current = {r: player.resources.get(r, 0) for r in Resource}
        rolls_per_unit = {r: self._expected_rolls_for_resource(player, r) for r in Resource}

        deficits, excesses = self._calculate_deficits_and_excesses(current, R_target)

        opponents = get_opponents(sim_game, player.player_number)

        trade_adjusted_rolls = self._calculate_trade_adjusted_rolls(
            player=player,
            opponents=opponents,
            deficits=deficits,
            excesses=excesses,
            rolls_per_unit=rolls_per_unit,
            bank_trade_ratio_func=lambda r: get_bank_trade_ratio(player.settlements + player.cities, r),
            include_player_trades=include_player_trades,
        )

        etb = max(trade_adjusted_rolls.values())
        player.etb_cache[cache_key] = etb
        return etb

    def _expected_rolls_for_resource(self, player: SimPlayerState, resource: Resource) -> float:
        """Return expected rolls to gain one unit of resource based on production rate."""
        fr = player.get_production_rate(resource)
        if fr <= 0.0:
            return float("inf")
        return 1.0 / fr

    def _calculate_trade_adjusted_rolls(
        self,
        player: SimPlayerState,
        opponents: List[SimPlayerState],
        deficits: Dict[Resource, int],
        excesses: Dict[Resource, int],
        rolls_per_unit: Dict[Resource, float],
        bank_trade_ratio_func,
        include_player_trades: bool,
    ) -> Dict[Resource, float]:
        """Compute expected rolls per resource after bank/port and optional player-trade conversions."""
        trade_adjusted: Dict[Resource, float] = {}

        for resource_i in Resource:
            if deficits[resource_i] <= 0:
                trade_adjusted[resource_i] = 0.0
                continue

            direct_rolls = deficits[resource_i] * rolls_per_unit[resource_i]

            bank_savings = 0.0
            for resource_j, excess in excesses.items():
                if resource_j == resource_i or excess <= 0:
                    continue
                sell_ratio = bank_trade_ratio_func(resource_j)
                units_gained = excess / max(1, sell_ratio)
                bank_savings += units_gained * rolls_per_unit[resource_i]

            player_savings = 0.0
            if include_player_trades:
                for resource_j, excess in excesses.items():
                    if resource_j == resource_i or excess <= 0:
                        continue
                    ratio = self._player_trade_ratio(resource_j, resource_i, player, opponents, rolls_per_unit)
                    units_gained = excess / max(1, ratio)
                    player_savings += units_gained * rolls_per_unit[resource_i]

            trade_adjusted[resource_i] = max(0.0, direct_rolls - bank_savings - player_savings)

        return trade_adjusted

    def _player_trade_ratio(
        self,
        resource_give: Resource,
        resource_need: Resource,
        player: SimPlayerState,
        opponents: List[SimPlayerState],
        rolls_per_unit: Dict[Resource, float],
    ) -> int:
        """Return a conservative give:take ratio for player trades."""
        give_r = rolls_per_unit.get(resource_give, float("inf"))
        need_r = rolls_per_unit.get(resource_need, float("inf"))

        if need_r == float("inf"):
            base_ratio = StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO
        else:
            if give_r <= 0.0 or give_r == float("inf"):
                base_ratio = 1
            else:
                base_ratio = int((need_r / give_r) + 0.999999)
                base_ratio = max(1, min(StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO, base_ratio))

        leading = max([player, *opponents], key=lambda p: p.victory_points()) if opponents else player
        if leading is not player and base_ratio < StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO:
            base_ratio = min(StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO, base_ratio + 1)

        return base_ratio

    def estimated_time_to_win(
            self,
            player: SimPlayerState,
            sim_game: SimGame,
            dev_played: bool,
            include_player_trades: bool = True,
            max_depth_override: Optional[int] = None,
    ) -> float:
        """
        Estimate ETW (expected turns to reach 10 VP) via a greedy forward simulation.

        Speed knob:
          - max_depth_override limits the number of greedy steps simulated.
            Use a small value (e.g., 2 or 3) inside utility evaluation to get a much
            faster but still rank-useful ETW approximation.
        """
        # Cache key must include the override depth; otherwise you mix "fast" and "full" ETW values.
        cache_key = (
            player.player_number,
            dev_played,
            include_player_trades,
            max_depth_override,
            len(player.settlements),
            len(player.cities),
            len(player.roads),
            tuple((r.value, player.resources.get(r, 0)) for r in Resource),
        )

        if cache_key in player.etw_cache:
            return player.etw_cache[cache_key]

        points = player.victory_points()
        if points >= Game.VICTORY_POINTS_TO_WIN:
            player.etw_cache[cache_key] = 0.0
            return 0.0

        etw = 0.0
        iterations = 0

        # Default depth behaviour (existing)
        default_depth = min(
            Game.VICTORY_POINTS_TO_WIN + ETW_MAX_DEPTH_OFFSET - points,
            ETW_MAX_DEPTH_OFFSET,
        )

        # Apply optional override (must be >= 1 to do any work)
        if max_depth_override is not None:
            max_depth = max(1, int(max_depth_override))
            max_depth = min(max_depth, default_depth)
        else:
            max_depth = default_depth

        sim_player = player.copy()
        sim_game_local = _sim_game_with_replaced_player(sim_game, sim_player)

        while points < Game.VICTORY_POINTS_TO_WIN and iterations < max_depth:
            candidate_actions = self._get_candidate_actions(
                sim_player,
                sim_game_local,
                dev_played,
                include_player_trades,
            )

            if not candidate_actions:
                etw += StrategyWeights.ETW_NO_ACTION_PENALTY
                break

            actions, etb, vp_inc = candidate_actions[0]

            if etb > ETW_ETB_THRESHOLD:
                etw += StrategyWeights.ETW_NO_ACTION_PENALTY
                break

            etw += etb
            points += vp_inc

            # Roll out the whole chosen plan step-by-step
            for step in actions:
                self._simulate_step(sim_game_local, sim_player, step)

            iterations += 1

        # Only apply the "missing points" penalty if we were doing a full estimate.
        # In fast mode, we want relative ranking, not absolute ETW magnitude inflation.
        if max_depth_override is None and points < Game.VICTORY_POINTS_TO_WIN:
            etw += (Game.VICTORY_POINTS_TO_WIN - points) * StrategyWeights.ETW_MISSING_POINT_PENALTY

        player.etw_cache[cache_key] = etw
        return etw

    def _calculate_deficits_and_excesses(
        self,
        current: ResourceCount,
        target: ResourceCount,
    ) -> Tuple[Dict[Resource, int], Dict[Resource, int]]:
        """Compute deficits and excesses relative to a target."""
        deficits: Dict[Resource, int] = {}
        excesses: Dict[Resource, int] = {}

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

    def calc_etb_actions(self, player: SimPlayerState, sim_game: SimGame, total_actions: List[Action]) -> float:
        """Compute ETB for a list of actions by summing resource costs."""
        total_resources: ResourceCount = {res: 0 for res in Resource}

        for action in total_actions:
            step_resources = calc_step_resources(action)
            for res, cost in step_resources.items():
                total_resources[res] = total_resources.get(res, 0) + cost

        return self.estimated_time_to_build(player, sim_game, total_resources)

    def _get_candidate_actions(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        dev_played: bool,
        include_player_trades: bool = True,
    ) -> List[Tuple[List[Action], float, float]]:
        """Generate and prune candidates, returning (actions, etb, expected_vp_gain)."""
        cache_key = (
            player.player_number,
            dev_played,
            len(player.settlements),
            len(player.cities),
            len(player.roads),
            tuple((r.value, player.resources.get(r, 0)) for r in Resource),
        )

        if cache_key in player.candidate_cache:
            return player.candidate_cache[cache_key][:ETW_SIMULATION_MAX_CANDIDATES]

        candidate_actions: List[Tuple[List[Action], float, float]] = []

        if len(player.cities) < Buildable.CITY.max_on_board and player.settlements:
            city_etb = self.estimated_time_to_build(
                player,
                sim_game,
                Game.BUILDING_COST[Buildable.CITY],
                include_player_trades=include_player_trades,
            )
            sorted_settlements = sorted(
                player.settlements,
                key=lambda settlement: sum(dice_probability(h.production_number) for h in settlement.hexes),
                reverse=True,
            )[:StrategyWeights.MAX_SETTLEMENTS_FOR_CITY_UPGRADE]
            for s in sorted_settlements:
                candidate_actions.append(([Action(ActionType.BUILD, (Buildable.CITY, s))], city_etb, 1))

        settlement_candidates = distant_settlement_candidates(player, sim_game, self)
        settlement_candidates.sort(key=lambda x: x[1])
        candidate_actions.extend(settlement_candidates[:MAX_SETTLEMENT_CANDIDATES])

        points_needed = Game.VICTORY_POINTS_TO_WIN - player.victory_points()
        if player.army_size >= 2 or points_needed <= 2:
            candidate_actions.extend(purchase_development_card_action(player, sim_game, self))

        if not dev_played:
            candidate_actions.extend(play_development_card_action(player, sim_game))

        if len(candidate_actions) < StrategyWeights.MIN_CANDIDATES_FOR_ROAD:
            road_cost = Game.BUILDING_COST[Buildable.ROAD]
            road_etb = self.estimated_time_to_build(
                player,
                sim_game,
                road_cost,
                include_player_trades=include_player_trades,
            )
            if road_etb < ROAD_ETB_THRESHOLD:
                for v in player.settlements + player.cities:
                    for edge in v.edges:
                        if not sim_game.overlay.is_edge_taken(edge):
                            candidate_actions.append(([Action(ActionType.BUILD, (Buildable.ROAD, edge))], road_etb, 0))
                            break
                    if candidate_actions and candidate_actions[-1][0]:
                        break

        candidate_actions.sort(key=lambda x: x[1])
        player.candidate_cache[cache_key] = candidate_actions
        return candidate_actions[:ETW_SIMULATION_MAX_CANDIDATES]

    def _evaluate_utilities(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        dev_played: bool,
        candidates: List[Tuple[List[Action], float, float]],
        etw_before: float,
        opponents_etw_before: Dict[PlayerNumber, float],
    ) -> List[Tuple[Action, float]]:
        """Evaluate utility for candidate actions."""
        self._eval_stats["evaluations"] += 1

        utilities: List[Tuple[Action, float]] = []
        candidates.sort(key=lambda x: x[1])  # Prefer cheaper (lower ETB) plans first for pruning
        max_eval = min(MAX_EVALUATIONS, len(candidates))

        leading_opp_num = None
        opp_etw_before = None

        if opponents_etw_before and len(opponents_etw_before) > 0:
            leading_opp_num = min(opponents_etw_before, key=opponents_etw_before.get)
            opp_etw_before = opponents_etw_before.get(leading_opp_num, None)

        for actions, etb, vp_inc in candidates[:max_eval]:
            if etb > MAX_ETB_THRESHOLD or not actions:
                continue

            next_step = actions[0]  # the actual action we will take this turn

            # Roll out the entire candidate plan into a counterfactual state
            player_copy = player.copy()
            sim_game_copy = _sim_game_with_replaced_player(sim_game, player_copy)

            did_build_road = False
            did_play_knight = False

            for s in actions:
                if s.type == ActionType.BUILD and s.payload[0] == Buildable.ROAD:
                    did_build_road = True
                elif s.type == ActionType.PLAY_DEV_CARD and s.payload == DevelopmentCardType.KNIGHT:
                    did_play_knight = True

                self._simulate_step(sim_game_copy, player_copy, s)

            # Self utility: ETW improvement after executing the whole plan
            etw_after = self.estimated_time_to_win(player_copy, sim_game_copy, dev_played,
                                                   max_depth_override=EVAL_UTIL_MAX_DEPTH)

            if etw_before <= 0:
                u_self = 0.0
            else:
                u_self = max(0.0, (etw_before - etw_after) / etw_before * 100.0)

            # Opponent utility: delay caused to the leading opponent (lowest ETW-before)
            affects_board = any(
                s.type == ActionType.BUILD and s.payload[0] in (Buildable.ROAD, Buildable.SETTLEMENT)
                for s in actions
            )

            u_opp = 0.0
            if affects_board and leading_opp_num is not None and opp_etw_before is not None and opp_etw_before > 0:
                opp_etw_before = opponents_etw_before[leading_opp_num]

                # Use the already-mutated sim_game_copy (our plan has been applied to the overlay),
                # then evaluate opponent ETW in that counterfactual world.
                opp_state = sim_game_copy.overlay.get_sim_player(leading_opp_num).copy()
                sim_game_opp = _sim_game_with_replaced_player(sim_game_copy, opp_state)

                opp_etw_after = self.estimated_time_to_win(opp_state, sim_game_opp, False,
                                                           max_depth_override=EVAL_UTIL_MAX_DEPTH)

                if opp_etw_before > 0:
                    delay_caused = (opp_etw_after - opp_etw_before) / opp_etw_before * 100.0
                    u_opp = StrategyWeights.OPPONENT_INTERFERENCE_LEADING * delay_caused

            # Special utility: Longest Road / Largest Army bonuses based on FINAL rollout state
            u_special = 0.0

            # Longest Road: reward any plan that increases longest road length
            if did_build_road:
                delta_lr = max(0, player_copy.longest_road_length - player.longest_road_length)

                # Gate on *post*-plan threshold so "crossing the threshold this plan" counts
                if delta_lr > 0 and player_copy.longest_road_length >= StrategyWeights.LR_ROAD_THRESHOLD:
                    u_special += StrategyWeights.LR_UTILITY_MULTIPLIER * delta_lr

            # Largest Army: reward plans that play a knight (and thus move toward / secure LA)
            if did_play_knight:
                # Gate on post-plan army size so "reaching threshold this plan" counts
                if player_copy.army_size >= StrategyWeights.LA_ARMY_THRESHOLD:
                    u_special += compute_k_la(player_copy, sim_game) * 1.0

            # Time discounting: prefer faster-to-complete plans
            discount_rate = StrategyWeights.TIME_DISCOUNT_RATE
            eu = (
                    (
                            StrategyWeights.BUILD_SELF_UTILITY * u_self
                            + StrategyWeights.BUILD_OPPONENT_UTILITY * u_opp
                            + StrategyWeights.BUILD_SPECIAL_UTILITY * u_special
                    )
                    / ((1.0 + discount_rate) ** max(1.0, etb))
            )

            utilities.append((next_step, eu))

        return utilities

    def _simulate_step(self, sim_game: SimGame, player: SimPlayerState, step: Action):
        """Apply an action to SimPlayerState and BoardOverlay (including resource costs)."""
        overlay = sim_game.overlay

        # Helper: pay cost safely (don't go negative if something slips through)
        def _pay(cost: ResourceCount) -> None:
            for r, c in cost.items():
                if c <= 0:
                    continue
                player.resources[r] = max(0, player.resources.get(r, 0) - c)

        if step.type == ActionType.BUILD:
            building, loc = step.payload

            _pay(Game.BUILDING_COST[building])

            if building == Buildable.ROAD:
                opp_lengths = [
                    p.longest_road_length
                    for num, p in overlay.sim_players.items()
                    if num != player.player_number
                ]
                player.build_road(loc, opp_lengths)
                overlay.claim_edge(loc, player.player_number)

            elif building == Buildable.SETTLEMENT:
                player.build_settlement(loc)
                overlay.claim_vertex(loc, player.player_number)

            elif building == Buildable.CITY:
                player.build_city(loc)
                overlay.claim_vertex(loc, player.player_number)

        elif step.type == ActionType.BUY_DEV_CARD:
            _pay(Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD])

            # EV: buying a dev card gives some probability of +1 VP
            deck = sim_game.game.development_deck
            if not deck.empty():
                vp_prob = deck.get_probability(DevelopmentCardType.VICTORY_POINT, player.dev_cards)
                player.vp_ev_bonus += vp_prob

        elif step.type == ActionType.PLAY_DEV_CARD:
            ctype = step.payload

            # Don't allow playing cards you don't have in sim rollouts
            if player.dev_cards.get(ctype, 0) <= 0:
                return

            player.remove_card(ctype)

            if ctype == DevelopmentCardType.KNIGHT:
                opp_armies = [
                    p.army_size
                    for num, p in overlay.sim_players.items()
                    if num != player.player_number
                ]
                player.add_knight(opp_armies)

        elif step.type == ActionType.TRADE_WITH_BANK:
            # Optional: simulate bank trade if you want rollouts to reflect it
            selling, buying = step.payload
            player.remove_resources(selling)
            player.add_resources(buying)

        elif step.type == ActionType.TRADE_WITH_PLAYER:
            # Optional: from our perspective, we give "selling" and receive "buying"
            selling, buying = step.payload
            player.remove_resources(selling)
            player.add_resources(buying)

    def last_trade_rejected(self, player: SimPlayerState) -> bool:
        """Return True if the last trade was proposed but resources did not change."""
        if not self._last_trade_proposed or self._last_trade_resources is None:
            return False
        return self._last_trade_resources == player.resources

    def _choose_max_utility_action(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        utilities: List[Tuple[Action, float]],
        ignore_affordability: bool = False,
    ) -> Action:
        """Select the max-utility action, optionally inserting bank/player trades."""
        best_action: Optional[Action] = None
        best_utility = float("-inf")

        for action, utility in utilities:
            cost = calc_step_resources(action)

            if player.can_afford(cost) or ignore_affordability:
                if utility > best_utility:
                    best_utility = utility
                    best_action = action
                continue

            bank_trade_action = get_bank_trade_for_action(player, cost)
            if bank_trade_action and utility > best_utility:
                best_utility = utility
                best_action = bank_trade_action

            if not self.last_trade_rejected(player):
                player_deficit, player_excesses = self._calculate_deficits_and_excesses(player.resources, cost)
                missing = next((r for r, v in player_deficit.items() if v > 0), None)
                if missing is not None:
                    sim_game_for_trade = _sim_game_with_replaced_player(sim_game, player)
                    opponents = get_opponents(sim_game_for_trade, player.player_number)
                    trade_action = propose_trade(
                        player,
                        sim_game_for_trade,
                        missing,
                        player_excesses,
                        opponents,
                        self,
                    )
                    if trade_action and utility > best_utility:
                        best_utility = utility
                        best_action = trade_action

        if best_action is not None:
            return best_action

        return Action(ActionType.END_TURN)

    def calculate_best_game_action(
        self,
        sim_game: SimGame,
        player_number: PlayerNumber,
        dev_played: bool,
        ignore_affordability: bool = False,
        ignore_opponents: bool = False,
    ) -> Action:
        """Return the best next action for the given player number using the SimGame overlay."""
        sim_player = sim_game.overlay.get_sim_player(player_number)

        etw_before = self.estimated_time_to_win(sim_player.copy(), sim_game, dev_played)

        opponents_etw_before: Dict[PlayerNumber, float] = {}
        if not ignore_opponents:
            for opp in get_opponents(sim_game, player_number):
                opponents_etw_before[opp.player_number] = self.estimated_time_to_win(opp.copy(), sim_game, False)

        candidates = self._get_candidate_actions(sim_player, sim_game, dev_played)
        if not candidates:
            return Action(ActionType.END_TURN)

        utilities = self._evaluate_utilities(
            sim_player,
            sim_game,
            dev_played,
            candidates,
            etw_before,
            opponents_etw_before,
        )
        if not utilities:
            return Action(ActionType.END_TURN)

        return self._choose_max_utility_action(
            sim_player,
            sim_game,
            utilities,
            ignore_affordability=ignore_affordability,
        )
