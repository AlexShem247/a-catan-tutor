import math
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
    overlay2 = sim_game.overlay.copy()
    overlay2.set_sim_player(sim_player)
    return SimGame(game=sim_game.game, overlay=overlay2)


class EtwEstimator:
    def __init__(self):
        self._eval_stats = {"cache_hits": 0, "cache_misses": 0, "evaluations": 0}
        self._last_trade_resources: Optional[ResourceCount] = None
        self._last_trade_proposed: bool = False

    def new_turn(self):
        self._last_trade_proposed = False
        self._last_trade_resources = None

    def estimated_time_to_build(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        R_target: ResourceCount,
        weights: StrategyWeights,
        include_player_trades: bool = True,
    ) -> float:
        target_key = tuple((r.value, R_target.get(r, 0)) for r in Resource)
        player_key = (
            player.player_number,
            tuple(player.settlements),
            tuple(player.cities),
            tuple((r.value, player.resources.get(r, 0)) for r in Resource),
        )
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
            weights=weights,
            bank_trade_ratio_func=lambda r: get_bank_trade_ratio(player.settlements + player.cities, r),
            include_player_trades=include_player_trades,
        )

        etb = max(trade_adjusted_rolls.values())
        player.etb_cache[cache_key] = etb
        return etb

    def _expected_rolls_for_resource(self, player: SimPlayerState, resource: Resource) -> float:
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
        weights: StrategyWeights,
        bank_trade_ratio_func,
        include_player_trades: bool,
    ) -> Dict[Resource, float]:
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
                    ratio = self._player_trade_ratio(resource_j, resource_i, player, opponents, rolls_per_unit, weights)
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
        weights: StrategyWeights,
    ) -> int:
        give_r = rolls_per_unit.get(resource_give, float("inf"))
        need_r = rolls_per_unit.get(resource_need, float("inf"))

        if need_r == float("inf"):
            base_ratio = weights.MAX_PLAYER_TRADE_GIVE_RATIO
        else:
            if give_r <= 0.0 or give_r == float("inf"):
                base_ratio = 1
            else:
                base_ratio = math.ceil(need_r / give_r)
                base_ratio = max(1, min(weights.MAX_PLAYER_TRADE_GIVE_RATIO, base_ratio))

        leading = max([player, *opponents], key=lambda p: p.victory_points()) if opponents else player
        if leading is not player and base_ratio < weights.MAX_PLAYER_TRADE_GIVE_RATIO:
            base_ratio = min(weights.MAX_PLAYER_TRADE_GIVE_RATIO, base_ratio + 1)

        return base_ratio

    def estimated_time_to_win(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        dev_played: bool,
        weights: StrategyWeights,
        include_player_trades: bool = True,
        max_depth_override: Optional[int] = None,
    ) -> float:
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

        default_depth = min(
            Game.VICTORY_POINTS_TO_WIN + ETW_MAX_DEPTH_OFFSET - points,
            ETW_MAX_DEPTH_OFFSET,
        )

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
                weights,
                include_player_trades,
            )

            if not candidate_actions:
                etw += weights.ETW_NO_ACTION_PENALTY
                break

            actions, etb, _ = candidate_actions[0]

            if etb > ETW_ETB_THRESHOLD:
                etw += weights.ETW_NO_ACTION_PENALTY
                break

            etw += etb

            for step in actions:
                self._simulate_step(sim_game_local, sim_player, step)

            points = sim_player.victory_points()
            iterations += 1

        if max_depth_override is None and points < Game.VICTORY_POINTS_TO_WIN:
            etw += (Game.VICTORY_POINTS_TO_WIN - points) * weights.ETW_MISSING_POINT_PENALTY

        player.etw_cache[cache_key] = etw
        return etw

    def _calculate_deficits_and_excesses(
        self,
        current: ResourceCount,
        target: ResourceCount,
    ) -> Tuple[Dict[Resource, int], Dict[Resource, int]]:
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

    def calc_etb_actions(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        total_actions: List[Action],
        weights: StrategyWeights,
    ) -> float:
        total_resources: ResourceCount = {res: 0 for res in Resource}

        for action in total_actions:
            step_resources = calc_step_resources(action)
            for res, cost in step_resources.items():
                total_resources[res] = total_resources.get(res, 0) + cost

        return self.estimated_time_to_build(player, sim_game, total_resources, weights)

    def _get_candidate_actions(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        dev_played: bool,
        weights: StrategyWeights,
        include_player_trades: bool = True,
    ) -> List[Tuple[List[Action], float, float]]:
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
                weights,
                include_player_trades=include_player_trades,
            )
            sorted_settlements = sorted(
                player.settlements,
                key=lambda settlement: sum(dice_probability(h.production_number) for h in settlement.hexes),
                reverse=True,
            )[:weights.MAX_SETTLEMENTS_FOR_CITY_UPGRADE]
            for s in sorted_settlements:
                candidate_actions.append(([Action(ActionType.BUILD, (Buildable.CITY, s))], city_etb, 1))

        settlement_candidates = distant_settlement_candidates(player, sim_game, self, weights)
        settlement_candidates.sort(key=lambda x: x[1])
        candidate_actions.extend(settlement_candidates[:MAX_SETTLEMENT_CANDIDATES])

        points_needed = Game.VICTORY_POINTS_TO_WIN - player.victory_points()
        if player.army_size >= 2 or points_needed <= 2:
            candidate_actions.extend(purchase_development_card_action(player, sim_game, self, weights))

        if not dev_played:
            candidate_actions.extend(play_development_card_action(player, sim_game, weights))

        if len(candidate_actions) < weights.MIN_CANDIDATES_FOR_ROAD:
            road_cost = Game.BUILDING_COST[Buildable.ROAD]
            road_etb = self.estimated_time_to_build(
                player,
                sim_game,
                road_cost,
                weights,
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

    def evaluate_utilities(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        dev_played: bool,
        candidates: List[Tuple[List[Action], float, float]],
        etw_before: float,
        opponents_etw_before: Dict[PlayerNumber, float],
        weights: StrategyWeights,
    ) -> List[Tuple[Action, float]]:
        self._eval_stats["evaluations"] += 1

        utilities: List[Tuple[Action, float]] = []
        candidates.sort(key=lambda x: x[1])
        max_eval = min(MAX_EVALUATIONS, len(candidates))

        leading_opp_num, opp_etw_before = None, None
        if opponents_etw_before:
            leading_opp_num = min(opponents_etw_before, key=opponents_etw_before.get)
            opp_etw_before = opponents_etw_before.get(leading_opp_num)

        for actions, etb, vp_inc in candidates[:max_eval]:
            if etb > MAX_ETB_THRESHOLD or not actions:
                continue

            next_step = actions[0]

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

            etw_after = self.estimated_time_to_win(
                player_copy,
                sim_game_copy,
                dev_played,
                weights,
                max_depth_override=EVAL_UTIL_MAX_DEPTH,
            )
            u_self = 0.0 if etw_before <= 0 else max(0.0, (etw_before - etw_after) / etw_before * 100.0)

            affects_board = any(
                s.type == ActionType.BUILD and s.payload[0] in (Buildable.ROAD, Buildable.SETTLEMENT)
                for s in actions
            )

            u_opp = 0.0
            if affects_board and leading_opp_num is not None and opp_etw_before and opp_etw_before > 0:
                opp_state = sim_game_copy.overlay.get_sim_player(leading_opp_num).copy()
                sim_game_opp = _sim_game_with_replaced_player(sim_game_copy, opp_state)

                opp_etw_after = self.estimated_time_to_win(
                    opp_state,
                    sim_game_opp,
                    False,
                    weights,
                    max_depth_override=EVAL_UTIL_MAX_DEPTH,
                )

                delay_caused = (opp_etw_after - opp_etw_before) / opp_etw_before * 100.0
                u_opp = weights.OPPONENT_INTERFERENCE_LEADING * delay_caused

            u_special = 0.0

            if did_build_road:
                delta_lr = max(0, player_copy.longest_road_length - player.longest_road_length)
                if delta_lr > 0 and player_copy.longest_road_length >= weights.LR_ROAD_THRESHOLD:
                    u_special += weights.LR_UTILITY_MULTIPLIER * delta_lr

            if did_play_knight:
                if player_copy.army_size >= weights.LA_ARMY_THRESHOLD:
                    u_special += compute_k_la(player_copy, sim_game, weights)

            took_lr_now = (not player.has_longest_road) and player_copy.has_longest_road
            vp_after = player_copy.victory_points()

            u_attention = 0.0
            if took_lr_now and vp_after < weights.ATTENTION_LR_VP_THRESHOLD:
                u_attention -= weights.ATTENTION_LR_EARLY_PENALTY

            discount_rate = weights.TIME_DISCOUNT_RATE
            eu = (
                    (
                            weights.BUILD_SELF_UTILITY * u_self
                            + weights.BUILD_OPPONENT_UTILITY * u_opp
                            + weights.BUILD_SPECIAL_UTILITY * u_special
                            + u_attention
                    )
                    / ((1.0 + discount_rate) ** max(1.0, etb))
            )

            utilities.append((next_step, eu))

        return utilities

    def _simulate_step(self, sim_game: SimGame, player: SimPlayerState, step: Action):
        overlay = sim_game.overlay

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

            deck = sim_game.game.development_deck
            if not deck.empty():
                vp_prob = deck.get_probability(DevelopmentCardType.VICTORY_POINT, player.dev_cards)
                player.vp_ev_bonus += vp_prob

        elif step.type == ActionType.PLAY_DEV_CARD:
            ctype = step.payload

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
            selling, buying = step.payload
            player.remove_resources(selling)
            player.add_resources(buying)

        elif step.type == ActionType.TRADE_WITH_PLAYER:
            selling, buying = step.payload
            player.remove_resources(selling)
            player.add_resources(buying)

    def last_trade_rejected(self, player: SimPlayerState) -> bool:
        if not self._last_trade_proposed or self._last_trade_resources is None:
            return False
        return self._last_trade_resources == player.resources

    def _choose_max_utility_action(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        utilities: List[Tuple[Action, float]],
        weights: StrategyWeights,
        ignore_affordability: bool = False,
    ) -> Action:
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
                        weights,
                    )
                    if trade_action and utility > best_utility:
                        best_utility = utility
                        best_action = trade_action

        return best_action if best_action is not None else Action(ActionType.END_TURN)

    def calculate_best_game_action(
        self,
        sim_game: SimGame,
        player_number: PlayerNumber,
        dev_played: bool,
        weights: StrategyWeights,
        ignore_affordability: bool = False,
        ignore_opponents: bool = False,
    ) -> Action:
        sim_player = sim_game.overlay.get_sim_player(player_number)

        etw_before = self.estimated_time_to_win(sim_player.copy(), sim_game, dev_played, weights)

        opponents_etw_before: Dict[PlayerNumber, float] = {}
        if not ignore_opponents:
            for opp in get_opponents(sim_game, player_number):
                opponents_etw_before[opp.player_number] = self.estimated_time_to_win(
                    opp.copy(),
                    sim_game,
                    False,
                    weights,
                )

        candidates = self._get_candidate_actions(sim_player, sim_game, dev_played, weights)
        if not candidates:
            return Action(ActionType.END_TURN)

        utilities = self.evaluate_utilities(
            sim_player,
            sim_game,
            dev_played,
            candidates,
            etw_before,
            opponents_etw_before,
            weights,
        )
        if not utilities:
            return Action(ActionType.END_TURN)

        best_build = max(
            (u for u in utilities if u[0].type != ActionType.BUY_DEV_CARD),
            default=None,
            key=lambda x: x[1],
        )
        best_dev = max(
            (u for u in utilities if u[0].type == ActionType.BUY_DEV_CARD),
            default=None,
            key=lambda x: x[1],
        )

        if (not ignore_affordability) and best_build is not None and best_dev is not None:
            if best_dev[1] >= best_build[1] * (1.0 - weights.DEV_CLOSE_THRESHOLD):
                utilities = [best_dev]

        return self._choose_max_utility_action(
            sim_player,
            sim_game,
            utilities,
            weights,
            ignore_affordability=ignore_affordability,
        )
