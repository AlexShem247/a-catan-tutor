import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, cast

from ai.simulation.SimGame import SimGame
from ai.simulation.SimPlayerState import SimPlayerState, dice_probability
from ai.utils.action_utils import (
    compute_k_la, distant_settlement_candidates, get_bank_trade_for_action,
    play_development_card_action, purchase_development_card_action,
)
from ai.actions import ActionType, Action
from ai.simulation.board_sim_utils import get_opponents
from ai.tutor.move_quality import strategic_turn_move_quality
from ai.tutor.explanations import (
    ActionExplanation, AssumptionCode, CandidateExplanation, Reason, ReasonLabel,
    ReasonType,
)
from ai.utils.resource_utils import get_bank_trade_ratio, calc_step_resources
from ai.utils.trade_utils import propose_trade
from config.StrategyWeights import StrategyWeights
from config.performance_constants import (
    ETW_MAX_DEPTH_OFFSET, MAX_ETB_THRESHOLD, MAX_EVALUATIONS, MAX_SETTLEMENT_CANDIDATES,
    ROAD_ETB_THRESHOLD, ETW_ETB_THRESHOLD, ETW_SIMULATION_MAX_CANDIDATES, EVAL_UTIL_MAX_DEPTH,
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


@dataclass(frozen=True)
class EtwTradeStateSnapshot:
    last_trade_resources: Optional[ResourceCount]
    last_trade_proposed: bool


class EtwEstimator:
    def __init__(self):
        self._eval_stats = {"cache_hits": 0, "cache_misses": 0, "evaluations": 0}
        self._last_trade_resources: Optional[ResourceCount] = None
        self._last_trade_proposed: bool = False

    def new_turn(self):
        """Clear previous turn trade info."""
        self._last_trade_proposed = False
        self._last_trade_resources = None

    def snapshot_trade_state(self) -> EtwTradeStateSnapshot:
        last_trade_resources = self._last_trade_resources
        return EtwTradeStateSnapshot(
            last_trade_resources=None if last_trade_resources is None else last_trade_resources.copy(),
            last_trade_proposed=self._last_trade_proposed,
        )

    def restore_trade_state(self, snapshot: EtwTradeStateSnapshot) -> None:
        self._last_trade_proposed = snapshot.last_trade_proposed
        self._last_trade_resources = (
            None if snapshot.last_trade_resources is None else snapshot.last_trade_resources.copy()
        )

    def record_trade_proposal(self, resources: ResourceCount) -> None:
        self._last_trade_proposed = True
        self._last_trade_resources = resources.copy()

    def clear_trade_proposal(self) -> None:
        self._last_trade_proposed = False
        self._last_trade_resources = None

    @staticmethod
    def _apply_time_discount(utility: float, etb: float, use_time_discount: bool) -> float:
        if not use_time_discount:
            return utility
        discount_rate = StrategyWeights.TIME_DISCOUNT_RATE
        return utility / ((1.0 + discount_rate) ** max(1.0, etb))

    @staticmethod
    def _immediate_vp_gain(action: Action) -> float:
        if action.type != ActionType.BUILD:
            return 0.0
        buildable, _ = action.payload
        if buildable in (Buildable.SETTLEMENT, Buildable.CITY):
            return 1.0
        return 0.0

    def estimated_time_to_build(
        self, player: SimPlayerState, sim_game: SimGame, R_target: ResourceCount,
        include_player_trades: bool = True,
    ) -> float:
        """Estimate ETB for a resource target with caching."""

        # Cache key captures player state, target resources, and trade assumptions.
        target_key = tuple((r.value, R_target.get(r, 0)) for r in Resource)
        player_key = (
            player.player_number, tuple(player.settlements), tuple(player.cities),
            tuple((r.value, player.resources.get(r, 0)) for r in Resource),
        )
        cache_key = (player_key, target_key, include_player_trades)

        if cache_key in player.etb_cache:
            return player.etb_cache[cache_key]

        # Current holdings and expected rolls per resource.
        current = {r: player.resources.get(r, 0) for r in Resource}
        rolls_per_unit = {r: self._expected_rolls_for_resource(player, r) for r in Resource}

        # Split target into shortages and surplus.
        deficits, excesses = self._calculate_deficits_and_excesses(current, R_target)

        # Adjust expected rolls using bank/port trades and (optionally) player trades.
        opponents = get_opponents(sim_game, player.player_number)
        trade_adjusted_rolls = self._calculate_trade_adjusted_rolls(
            player=player, opponents=opponents, deficits=deficits, excesses=excesses,
            rolls_per_unit=rolls_per_unit,
            bank_trade_ratio_func=lambda r: get_bank_trade_ratio(player.settlements + player.cities, r),
            include_player_trades=include_player_trades,
        )

        # ETB is governed by the slowest required resource.
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
        self, player: SimPlayerState, opponents: List[SimPlayerState], deficits: Dict[Resource, int],
        excesses: Dict[Resource, int], rolls_per_unit: Dict[Resource, float], bank_trade_ratio_func,
        include_player_trades: bool,
    ) -> Dict[Resource, float]:
        """Compute expected rolls per resource after bank/port and optional player-trade conversions."""
        trade_adjusted: Dict[Resource, float] = {}

        for resource_i in Resource:
            # No shortage → no time required.
            if deficits[resource_i] <= 0:
                trade_adjusted[resource_i] = 0.0
                continue

            # Base time from direct production only.
            direct_rolls = deficits[resource_i] * rolls_per_unit[resource_i]

            # Current surplus can be converted immediately, but each source resource only gets one best conversion path.
            immediate_trade_savings = 0.0
            for resource_j, excess in excesses.items():
                if resource_j == resource_i or excess <= 0:
                    continue
                best_ratio = bank_trade_ratio_func(resource_j)
                if include_player_trades:
                    best_ratio = min(
                        best_ratio,
                        self._player_trade_ratio(resource_j, resource_i, player, opponents, rolls_per_unit),
                    )
                units_gained = excess / max(1, best_ratio)
                immediate_trade_savings += units_gained * rolls_per_unit[resource_i]

            adjusted_rolls = max(0.0, direct_rolls - immediate_trade_savings)
            future_trade_rolls = self._future_trade_rolls_for_resource(
                resource_i=resource_i,
                player=player,
                opponents=opponents,
                deficits=deficits,
                excesses=excesses,
                rolls_per_unit=rolls_per_unit,
                bank_trade_ratio_func=bank_trade_ratio_func,
                include_player_trades=include_player_trades,
            )

            # If direct production is impossible, allow other producible resources to stand in via future trades.
            trade_adjusted[resource_i] = min(adjusted_rolls, future_trade_rolls)

        return trade_adjusted

    def _future_trade_rolls_for_resource(
        self,
        resource_i: Resource,
        player: SimPlayerState,
        opponents: List[SimPlayerState],
        deficits: Dict[Resource, int],
        excesses: Dict[Resource, int],
        rolls_per_unit: Dict[Resource, float],
        bank_trade_ratio_func,
        include_player_trades: bool,
    ) -> float:
        """Estimate rolls to acquire a missing resource via future production that can later be traded."""
        units_needed = deficits.get(resource_i, 0)
        if units_needed <= 0:
            return 0.0

        best_rolls = float("inf")

        for resource_j in Resource:
            if resource_j == resource_i:
                continue

            # Do not spend future production of resources the target build still needs.
            if deficits.get(resource_j, 0) > 0:
                continue

            source_rolls = rolls_per_unit.get(resource_j, float("inf"))
            if not math.isfinite(source_rolls) or source_rolls <= 0.0:
                continue

            best_ratio = bank_trade_ratio_func(resource_j)
            if include_player_trades:
                best_ratio = min(
                    best_ratio,
                    self._player_trade_ratio(resource_j, resource_i, player, opponents, rolls_per_unit),
                )

            tradable_now = excesses.get(resource_j, 0)
            future_rolls = max(0.0, units_needed * best_ratio - tradable_now) * source_rolls
            best_rolls = min(best_rolls, future_rolls)

        return best_rolls

    def _player_trade_ratio(
        self, resource_give: Resource, resource_need: Resource, player: SimPlayerState,
        opponents: List[SimPlayerState], rolls_per_unit: Dict[Resource, float],
    ) -> int:
        """Return a conservative give:take ratio for player trades."""
        give_r = rolls_per_unit.get(resource_give, float("inf"))
        need_r = rolls_per_unit.get(resource_need, float("inf"))

        # If we can't produce the needed resource, assume we must overpay.
        if need_r == float("inf"):
            base_ratio = StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO
        else:
            # Ratio is based on relative scarcity (expected rolls per unit).
            if give_r <= 0.0 or give_r == float("inf"):
                base_ratio = 1
            else:
                base_ratio = math.ceil(need_r / give_r)
                base_ratio = max(1, min(StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO, base_ratio))

        # Slightly more conservative when trading while behind the leader.
        leading = max([player, *opponents], key=lambda p: p.victory_points()) if opponents else player
        if leading is not player and base_ratio < StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO:
            base_ratio = min(StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO, base_ratio + 1)

        return base_ratio

    def estimated_time_to_win(
        self, player: SimPlayerState, sim_game: SimGame, dev_played: bool,
        include_player_trades: bool = True, max_depth_override: Optional[int] = None,
        allow_development_cards: bool = True, use_planning: bool = True,
    ) -> float:
        """Estimate expected turns to reach 10 VP via a greedy forward rollout."""

        # Cache key includes depth override to avoid mixing fast vs full ETW estimates.
        cache_key = (
            player.player_number, dev_played, include_player_trades, max_depth_override,
            allow_development_cards, use_planning,
            len(player.settlements), len(player.cities), len(player.roads),
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

        # Default rollout depth shrinks as we get closer to winning.
        default_depth = max(
            1,
            math.ceil(min(Game.VICTORY_POINTS_TO_WIN + ETW_MAX_DEPTH_OFFSET - points, ETW_MAX_DEPTH_OFFSET)),
        )

        # Optional override for fast, rank-only ETW estimates.
        if max_depth_override is not None:
            max_depth = max(1, int(max_depth_override))
            max_depth = min(max_depth, default_depth)
        else:
            max_depth = default_depth

        # Work on a copied player and overlay so the real state is untouched.
        sim_player = player.copy()
        sim_game_local = _sim_game_with_replaced_player(sim_game, sim_player)

        while points < Game.VICTORY_POINTS_TO_WIN and iterations < max_depth:
            candidate_actions = self._get_candidate_actions(
                sim_player,
                sim_game_local,
                dev_played,
                include_player_trades,
                allow_development_cards=allow_development_cards,
                use_planning=use_planning,
            )

            # No feasible progress → penalise and stop.
            if not candidate_actions:
                etw += StrategyWeights.ETW_NO_ACTION_PENALTY
                break

            actions, etb, _ = candidate_actions[0]

            # Plans that take too long are treated as stalls.
            if etb > ETW_ETB_THRESHOLD:
                etw += StrategyWeights.ETW_NO_ACTION_PENALTY
                break

            etw += etb

            # Apply the full chosen plan step by step.
            self._simulate_plan_until_win(sim_game_local, sim_player, actions)

            # Update points after the rollout step.
            points = sim_player.victory_points()
            iterations += 1

        # Only inflate ETW for missing points in the full (non-fast) estimate.
        if max_depth_override is None and points < Game.VICTORY_POINTS_TO_WIN:
            etw += (Game.VICTORY_POINTS_TO_WIN - points) * StrategyWeights.ETW_MISSING_POINT_PENALTY

        player.etw_cache[cache_key] = etw
        return etw

    def _simulate_plan_until_win(self, sim_game: SimGame, player: SimPlayerState, actions: List[Action]) -> None:
        """Apply actions in order and stop immediately once the simulated player wins."""
        for step in actions:
            self._simulate_step(sim_game, player, step)
            if player.victory_points() >= Game.VICTORY_POINTS_TO_WIN:
                break

    def _calculate_deficits_and_excesses(
        self, current: ResourceCount, target: ResourceCount,
    ) -> Tuple[Dict[Resource, int], Dict[Resource, int]]:
        """Compute deficits and excesses relative to a target."""
        deficits: Dict[Resource, int] = {}
        excesses: Dict[Resource, int] = {}

        for resource in Resource:
            needed = target.get(resource, 0)
            have = current.get(resource, 0)

            # Split each resource into either a shortfall or a surplus.
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

    def _plan_resource_cost(self, actions: List[Action]) -> ResourceCount:
        """Return the total resource cost across all resource-consuming steps in a plan."""
        total_resources: ResourceCount = {res: 0 for res in Resource}

        for action in actions:
            step_resources = calc_step_resources(action)
            for res, cost in step_resources.items():
                total_resources[res] = total_resources.get(res, 0) + cost

        return total_resources

    def _plan_waiting_resources(self, player: SimPlayerState, actions: List[Action]) -> ResourceCount:
        """Return the remaining resources the player still needs to accumulate for a plan."""
        total_resources = self._plan_resource_cost(actions)
        deficits, _ = self._calculate_deficits_and_excesses(player.resources, total_resources)
        return {res: amount for res, amount in deficits.items() if amount > 0}

    def _next_step_waiting_resources(self, player: SimPlayerState, actions: List[Action]) -> ResourceCount:
        """Return the missing resources for the immediate next action in a deferred plan."""
        if not actions:
            return {}
        return self._plan_waiting_resources(player, [actions[0]])

    def _future_plan_fields(self, player: SimPlayerState, actions: List[Action]) -> Tuple[List[Action], ResourceCount]:
        """Build the explanation fields that describe the deferred plan and next-step shortfall."""
        if not actions:
            return [], {}
        return list(actions), self._next_step_waiting_resources(player, actions)

    def _build_end_turn_candidate(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        etw_before: float,
        deferred_candidate: Optional[CandidateExplanation] = None,
        include_player_trades: bool = True,
        allow_development_cards: bool = True,
        use_planning: bool = True,
        use_time_discount: bool = True,
    ) -> CandidateExplanation:
        player_after_wait = player.copy()
        expected_resources = cast(Dict[Resource, float], player_after_wait.resources)
        for resource in Resource:
            expected_resources[resource] = (
                expected_resources.get(resource, 0.0) + player.get_production_rate(resource)
            )

        sim_game_after_wait = _sim_game_with_replaced_player(sim_game, player_after_wait)
        etw_after_wait = 1.0 + self.estimated_time_to_win(
            player_after_wait,
            sim_game_after_wait,
            False,
            max_depth_override=EVAL_UTIL_MAX_DEPTH,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )
        etw_delta = etw_before - etw_after_wait
        u_self = 0.0 if etw_before <= 0 else max(0.0, (etw_delta / etw_before) * 100.0)

        utility_total = self._apply_time_discount(
            StrategyWeights.BUILD_SELF_UTILITY * u_self,
            1.0,
            use_time_discount,
        )

        next_plan: List[Action] = []
        waiting_resources: ResourceCount = {}
        reasons_for: List[Reason] = [
            Reason(type=ReasonType.HEURISTIC_CHOICE, label=ReasonLabel.NO_IMMEDIATE_ACTION, value=max(0.0, u_self))
        ]
        reasons_against: List[Reason] = []
        if deferred_candidate is not None:
            next_plan = list(deferred_candidate.next_plan or deferred_candidate.full_plan)
            waiting_resources = dict(
                deferred_candidate.waiting_resources or self._plan_waiting_resources(player, next_plan)
            )
            reasons_against = list(deferred_candidate.reasons_against)

            immediate_step = next_plan[0] if next_plan else None
            if (
                immediate_step is not None
                and immediate_step.type != ActionType.END_TURN
                and player.can_afford(calc_step_resources(immediate_step))
            ):
                utility_total = min(utility_total, deferred_candidate.utility_total - 1e-6)

        action = Action(ActionType.END_TURN)
        return CandidateExplanation(
            action=action,
            full_plan=[action],
            next_plan=next_plan,
            waiting_resources=waiting_resources,
            etb=1.0,
            etw_before=etw_before,
            etw_after=etw_after_wait,
            etw_delta=etw_delta,
            utility_total=utility_total,
            utility_self=u_self,
            utility_opponent=0.0,
            utility_special=0.0,
            utility_attention=0.0,
            expected_vp_gain=0.0,
            reasons_for=reasons_for,
            reasons_against=reasons_against,
        )

    def _quick_reason_label(self, next_step: Action, final_step: Action) -> Tuple[ReasonLabel, Dict[str, Any]]:
        """Return a concise timing reason key and metadata for the plan outcome."""
        if next_step.type in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER) and final_step != next_step:
            if final_step.type == ActionType.BUILD:
                buildable = final_step.payload[0]
                build_name = getattr(buildable, "name", "build").lower()
                return ReasonLabel.QUICK_PLANNED_BUILD, {"build_name": build_name}
            if final_step.type == ActionType.BUY_DEV_CARD:
                return ReasonLabel.QUICK_PLANNED_DEV_BUY, {}
            if final_step.type == ActionType.PLAY_DEV_CARD:
                return ReasonLabel.QUICK_PLANNED_DEV_PLAY, {}
            return ReasonLabel.QUICK_PLANNED_FOLLOW_UP, {}

        if final_step.type == ActionType.PLAY_DEV_CARD:
            card_type = getattr(final_step, "payload", None)
            if card_type == DevelopmentCardType.KNIGHT:
                return ReasonLabel.QUICK_KNIGHT, {}
            if card_type == DevelopmentCardType.ROAD_BUILDING:
                return ReasonLabel.QUICK_ROAD_BUILDING, {}
            if card_type == DevelopmentCardType.YEAR_OF_PLENTY:
                return ReasonLabel.QUICK_YEAR_OF_PLENTY, {}
            if card_type == DevelopmentCardType.MONOPOLY:
                return ReasonLabel.QUICK_MONOPOLY, {}

        return ReasonLabel.QUICK_GENERIC, {}

    def _estimate_single_action_etb(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        action: Action,
        include_player_trades: bool = True,
    ) -> float:
        cost = calc_step_resources(action)
        if not any(cost.values()):
            return 0.0
        return self.estimated_time_to_build(
            player, sim_game, cost, include_player_trades=include_player_trades,
        )

    @staticmethod
    def _leading_opponent_etw(
        opponents_etw_before: Dict[PlayerNumber, float],
    ) -> Optional[Tuple[PlayerNumber, float]]:
        if not opponents_etw_before:
            return None
        leading_opp_num = min(opponents_etw_before, key=lambda num: opponents_etw_before[num])
        return leading_opp_num, opponents_etw_before[leading_opp_num]

    def _evaluate_action_plan(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        dev_played: bool,
        actions: List[Action],
        etb: float,
        vp_inc: float,
        etw_before: float,
        opponents_etw_before: Dict[PlayerNumber, float],
        include_player_trades: bool = True,
        allow_development_cards: bool = True,
        use_planning: bool = True,
        use_time_discount: bool = True,
    ) -> Optional[CandidateExplanation]:
        if etb > MAX_ETB_THRESHOLD or not actions:
            return None

        next_step = actions[0]
        next_plan, waiting_resources = self._future_plan_fields(player, actions)

        player_copy = player.copy()
        sim_game_copy = _sim_game_with_replaced_player(sim_game, player_copy)

        did_build_road = False
        did_play_knight = False

        for step in actions:
            if step.type == ActionType.BUILD and step.payload[0] == Buildable.ROAD:
                did_build_road = True
            elif step.type == ActionType.PLAY_DEV_CARD and step.payload == DevelopmentCardType.KNIGHT:
                did_play_knight = True

            self._simulate_step(sim_game_copy, player_copy, step)
            if player_copy.victory_points() >= Game.VICTORY_POINTS_TO_WIN:
                break

        etw_after = self.estimated_time_to_win(
            player_copy,
            sim_game_copy,
            dev_played,
            max_depth_override=EVAL_UTIL_MAX_DEPTH,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )

        etw_delta = etw_before - etw_after
        u_self = 0.0 if etw_before <= 0 else max(0.0, etw_delta / etw_before * 100.0)

        affects_board = any(
            step.type == ActionType.BUILD and step.payload[0] in (Buildable.ROAD, Buildable.SETTLEMENT)
            for step in actions
        )

        u_opp = 0.0
        blocks_opponent = False
        leader_etw = self._leading_opponent_etw(opponents_etw_before)
        if affects_board and leader_etw is not None:
            leading_opp_num, opp_etw_before = leader_etw
            if opp_etw_before > 0:
                opp_state = sim_game_copy.overlay.get_sim_player(leading_opp_num).copy()
                sim_game_opp = _sim_game_with_replaced_player(sim_game_copy, opp_state)

                opp_etw_after = self.estimated_time_to_win(
                    opp_state,
                    sim_game_opp,
                    False,
                    max_depth_override=EVAL_UTIL_MAX_DEPTH,
                    include_player_trades=include_player_trades,
                    allow_development_cards=allow_development_cards,
                    use_planning=use_planning,
                )

                delay_caused = (opp_etw_after - opp_etw_before) / opp_etw_before * 100.0
                u_opp = StrategyWeights.OPPONENT_INTERFERENCE_LEADING * delay_caused
                blocks_opponent = delay_caused > 0.0

        u_special = 0.0
        improves_longest_road = False
        improves_largest_army = False

        if did_build_road:
            delta_lr = max(0, player_copy.longest_road_length - player.longest_road_length)
            if delta_lr > 0 and player_copy.longest_road_length >= StrategyWeights.LR_ROAD_THRESHOLD:
                u_special += StrategyWeights.LR_UTILITY_MULTIPLIER * delta_lr
                improves_longest_road = True

        if did_play_knight and player_copy.army_size >= StrategyWeights.LA_ARMY_THRESHOLD:
            u_special += compute_k_la(player_copy, sim_game)
            improves_largest_army = True

        took_lr_now = (not player.has_longest_road) and player_copy.has_longest_road
        vp_after = player_copy.victory_points()

        u_attention = 0.0
        if took_lr_now and vp_after < StrategyWeights.ATTENTION_LR_VP_THRESHOLD:
            u_attention -= StrategyWeights.ATTENTION_LR_EARLY_PENALTY

        utility_total = self._apply_time_discount(
            StrategyWeights.BUILD_SELF_UTILITY * u_self
            + StrategyWeights.BUILD_OPPONENT_UTILITY * u_opp
            + StrategyWeights.BUILD_SPECIAL_UTILITY * u_special
            + u_attention,
            etb,
            use_time_discount,
        )

        reasons_for: List[Reason] = []
        reasons_against: List[Reason] = []
        final_step = actions[-1]

        if final_step.type == ActionType.BUILD:
            building, _ = final_step.payload
            if building == Buildable.SETTLEMENT:
                reasons_for.append(Reason(
                    type=ReasonType.ENABLES_EXPANSION, label=ReasonLabel.PLAN_SETTLEMENT_VALUE,
                    value=max(u_self * 0.9, 1.0),
                ))
            elif building == Buildable.CITY:
                reasons_for.append(Reason(
                    type=ReasonType.IMPROVES_PRODUCTION, label=ReasonLabel.PLAN_CITY_VALUE,
                    value=max(u_self * 0.8, 1.0),
                ))
            elif building == Buildable.ROAD:
                reasons_for.append(Reason(
                    type=ReasonType.ENABLES_EXPANSION, label=ReasonLabel.PLAN_ROAD_VALUE,
                    value=max(u_self * 0.7, 1.0),
                ))

        if etb <= 2.5:
            quick_label, quick_meta = self._quick_reason_label(next_step, final_step)
            reasons_for.append(Reason(
                type=ReasonType.QUICK_TO_EXECUTE, label=quick_label, metadata=quick_meta,
                value=max(0.0, 5.0 - etb),
            ))

        if blocks_opponent and u_opp > 0:
            reasons_for.append(
                Reason(type=ReasonType.SLOWS_LEADING_OPPONENT, label=ReasonLabel.SLOWS_LEADER, value=u_opp)
            )
        if improves_longest_road:
            reasons_for.append(Reason(
                type=ReasonType.ADVANCES_LONGEST_ROAD, label=ReasonLabel.ADVANCES_LONGEST_ROAD, value=u_special,
            ))
        if improves_largest_army:
            reasons_for.append(Reason(
                type=ReasonType.ADVANCES_LARGEST_ARMY, label=ReasonLabel.ADVANCES_LARGEST_ARMY, value=u_special,
            ))
        if next_step.type in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER):
            reasons_for.append(Reason(type=ReasonType.REQUIRES_TRADE, label=ReasonLabel.REQUIRES_TRADE, value=1.0))
        if next_step.type == ActionType.BUY_DEV_CARD and vp_inc > 0:
            reasons_for.append(Reason(type=ReasonType.HIDDEN_VALUE, label=ReasonLabel.HIDDEN_DEV_VALUE, value=vp_inc))
        if u_attention < 0:
            reasons_against.append(Reason(
                type=ReasonType.AVOIDS_EARLY_ATTENTION, label=ReasonLabel.EARLY_ATTENTION_RISK,
                value=abs(u_attention),
            ))

        reasons_for.sort(key=lambda reason: reason.value, reverse=True)
        reasons_against.sort(key=lambda reason: reason.value, reverse=True)

        return CandidateExplanation(
            action=next_step,
            full_plan=actions,
            next_plan=next_plan,
            waiting_resources=waiting_resources,
            etb=etb,
            etw_before=etw_before,
            etw_after=etw_after,
            etw_delta=etw_delta,
            utility_total=utility_total,
            utility_self=u_self,
            utility_opponent=u_opp,
            utility_special=u_special,
            utility_attention=u_attention,
            expected_vp_gain=vp_inc,
            reasons_for=reasons_for,
            reasons_against=reasons_against,
            metadata={
                "blocks_opponent": blocks_opponent,
                "improves_longest_road": improves_longest_road,
                "improves_largest_army": improves_largest_army,
            },
        )

    def _get_candidate_actions(
        self, player: SimPlayerState, sim_game: SimGame, dev_played: bool,
        include_player_trades: bool = True, allow_development_cards: bool = True, use_planning: bool = True,
    ) -> List[Tuple[List[Action], float, float]]:
        """Generate and prune candidates, returning (actions, etb, expected_vp_gain)."""

        # Cache so utility evaluation doesn't regenerate candidates repeatedly.
        cache_key = (
            player.player_number, dev_played, include_player_trades, allow_development_cards, use_planning,
            len(player.settlements), len(player.cities),
            len(player.roads), tuple((r.value, player.resources.get(r, 0)) for r in Resource),
        )

        if cache_key in player.candidate_cache:
            return player.candidate_cache[cache_key][:ETW_SIMULATION_MAX_CANDIDATES]

        candidate_actions: List[Tuple[List[Action], float, float]] = []

        # City upgrades: only consider a few best settlements (highest yield) to keep branching low.
        if len(player.cities) < Buildable.CITY.max_on_board and player.settlements:
            city_etb = self.estimated_time_to_build(
                player, sim_game, Game.BUILDING_COST[Buildable.CITY], include_player_trades=include_player_trades,
            )
            sorted_settlements = sorted(
                player.settlements,
                key=lambda settlement: sum(dice_probability(h.production_number) for h in settlement.hexes),
                reverse=True,
            )[:StrategyWeights.MAX_SETTLEMENTS_FOR_CITY_UPGRADE]
            for s in sorted_settlements:
                candidate_actions.append(([Action(ActionType.BUILD, (Buildable.CITY, s))], city_etb, 1))

        # Settlement expansion: include direct and “reachable with k roads” candidates, ETB-sorted.
        settlement_candidates = distant_settlement_candidates(player, sim_game, self)
        settlement_candidates.sort(key=lambda x: x[1])
        candidate_actions.extend(settlement_candidates[:MAX_SETTLEMENT_CANDIDATES])

        # Dev cards: mainly when close to winning or already investing in army pressure.
        points_needed = Game.VICTORY_POINTS_TO_WIN - player.victory_points()
        if allow_development_cards and (player.army_size >= 2 or points_needed <= 2):
            candidate_actions.extend(purchase_development_card_action(player, sim_game, self))

        # Playing dev cards is free ETB-wise, only allow once per turn.
        if allow_development_cards and not dev_played:
            candidate_actions.extend(play_development_card_action(player, sim_game))

        # If the candidate set is too small, add a cheap road option to avoid “dead-end” turns.
        if len(candidate_actions) < StrategyWeights.MIN_CANDIDATES_FOR_ROAD:
            road_cost = Game.BUILDING_COST[Buildable.ROAD]
            road_etb = self.estimated_time_to_build(
                player, sim_game, road_cost, include_player_trades=include_player_trades,
            )
            if road_etb < ROAD_ETB_THRESHOLD:
                added_road_candidate = False
                for v in player.settlements + player.cities:
                    for edge in v.edges:
                        if not sim_game.overlay.is_edge_taken(edge):
                            candidate_actions.append(([Action(ActionType.BUILD, (Buildable.ROAD, edge))], road_etb, 0))
                            added_road_candidate = True
                            break
                    if added_road_candidate:
                        break

        # Sort by ETB so later stages can prune quickly.
        if not use_planning:
            collapsed_candidates: List[Tuple[List[Action], float, float]] = []
            seen_actions: set[str] = set()
            for actions, _, _ in candidate_actions:
                if not actions:
                    continue
                next_action = actions[0]
                action_key = repr(next_action)
                if action_key in seen_actions:
                    continue
                seen_actions.add(action_key)
                collapsed_candidates.append((
                    [next_action],
                    self._estimate_single_action_etb(
                        player,
                        sim_game,
                        next_action,
                        include_player_trades=include_player_trades,
                    ),
                    self._immediate_vp_gain(next_action),
                ))
            candidate_actions = collapsed_candidates

        candidate_actions.sort(key=lambda x: x[1])
        player.candidate_cache[cache_key] = candidate_actions
        return candidate_actions[:ETW_SIMULATION_MAX_CANDIDATES]

    def evaluate_utilities(
        self, player: SimPlayerState, sim_game: SimGame, dev_played: bool,
        candidates: List[Tuple[List[Action], float, float]], etw_before: float,
        opponents_etw_before: Dict[PlayerNumber, float], include_player_trades: bool = True,
        allow_development_cards: bool = True, use_planning: bool = True, use_time_discount: bool = True,
    ) -> List[Tuple[Action, float]]:
        """Evaluate utility for candidate actions."""
        self._eval_stats["evaluations"] += 1

        utilities: List[Tuple[Action, float]] = []
        candidates.sort(key=lambda x: x[1])  # Cheap plans first (helps pruning)
        max_eval = min(MAX_EVALUATIONS, len(candidates))

        # Use the opponent with the lowest ETW as the "leader" for interference scoring.
        leader_etw = self._leading_opponent_etw(opponents_etw_before)

        for actions, etb, vp_inc in candidates[:max_eval]:
            # Skip very slow plans or empty candidates.
            if etb > MAX_ETB_THRESHOLD or not actions:
                continue

            next_step = actions[0]  # Only the first step is executed this turn

            # Roll out the full plan to estimate downstream ETW impact.
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
                if player_copy.victory_points() >= Game.VICTORY_POINTS_TO_WIN:
                    break

            # Self utility: percent reduction in (approx) ETW after the rollout.
            etw_after = self.estimated_time_to_win(
                player_copy,
                sim_game_copy,
                dev_played,
                max_depth_override=EVAL_UTIL_MAX_DEPTH,
                include_player_trades=include_player_trades,
                allow_development_cards=allow_development_cards,
                use_planning=use_planning,
            )
            u_self = 0.0 if etw_before <= 0 else max(0.0, (etw_before - etw_after) / etw_before * 100.0)

            # Opponent utility: only score interference if this plan changes the board.
            affects_board = any(
                s.type == ActionType.BUILD and s.payload[0] in (Buildable.ROAD, Buildable.SETTLEMENT)
                for s in actions
            )

            u_opp = 0.0
            if affects_board and leader_etw is not None:
                # Evaluate the leader's ETW in the counterfactual world where we executed this plan.
                leading_opp_num, opp_etw_before = leader_etw
                opp_state = sim_game_copy.overlay.get_sim_player(leading_opp_num).copy()
                sim_game_opp = _sim_game_with_replaced_player(sim_game_copy, opp_state)

                if opp_etw_before > 0:
                    opp_etw_after = self.estimated_time_to_win(
                        opp_state,
                        sim_game_opp,
                        False,
                        max_depth_override=EVAL_UTIL_MAX_DEPTH,
                        include_player_trades=include_player_trades,
                        allow_development_cards=allow_development_cards,
                        use_planning=use_planning,
                    )

                    delay_caused = (opp_etw_after - opp_etw_before) / opp_etw_before * 100.0
                    u_opp = StrategyWeights.OPPONENT_INTERFERENCE_LEADING * delay_caused

            # Special utility: explicit incentives for LR / LA progress when a plan advances them.
            u_special = 0.0

            if did_build_road:
                delta_lr = max(0, player_copy.longest_road_length - player.longest_road_length)
                if delta_lr > 0 and player_copy.longest_road_length >= StrategyWeights.LR_ROAD_THRESHOLD:
                    u_special += StrategyWeights.LR_UTILITY_MULTIPLIER * delta_lr

            if did_play_knight:
                if player_copy.army_size >= StrategyWeights.LA_ARMY_THRESHOLD:
                    u_special += compute_k_la(player_copy, sim_game)

            # Attention management: taking LR very early can paint a target on us.
            took_lr_now = (not player.has_longest_road) and player_copy.has_longest_road
            vp_after = player_copy.victory_points()

            u_attention = 0.0
            if took_lr_now and vp_after < StrategyWeights.ATTENTION_LR_VP_THRESHOLD:
                u_attention -= StrategyWeights.ATTENTION_LR_EARLY_PENALTY

            # Discount by ETB so fast gains beat slow gains.
            eu = self._apply_time_discount(
                StrategyWeights.BUILD_SELF_UTILITY * u_self
                + StrategyWeights.BUILD_OPPONENT_UTILITY * u_opp
                + StrategyWeights.BUILD_SPECIAL_UTILITY * u_special
                + u_attention,
                etb,
                use_time_discount,
            )

            utilities.append((next_step, eu))

        end_turn_candidate = self._build_end_turn_candidate(
            player,
            sim_game,
            etw_before,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
            use_time_discount=use_time_discount,
        )
        utilities.append((end_turn_candidate.action, end_turn_candidate.utility_total))

        return utilities

    def _simulate_step(self, sim_game: SimGame, player: SimPlayerState, step: Action):
        """Apply an action to SimPlayerState and BoardOverlay (including resource costs)."""
        overlay = sim_game.overlay

        # Safe payment for rollouts.
        def _pay(cost: ResourceCount) -> None:
            for r, c in cost.items():
                if c <= 0:
                    continue
                player.resources[r] = max(0, player.resources.get(r, 0) - c)

        if step.type == ActionType.BUILD:
            building, loc = step.payload
            _pay(Game.BUILDING_COST[building])

            if building == Buildable.ROAD:
                # Longest Road depends on opponents' best length, so pass that into the update.
                opp_lengths = [
                    p.longest_road_length for num, p in overlay.sim_players.items() if num != player.player_number
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

            # Track expected VP from future VP-card draws without simulating the deck.
            deck = sim_game.game.development_deck
            if not deck.empty():
                vp_prob = deck.get_probability(DevelopmentCardType.VICTORY_POINT, player.dev_cards)
                player.vp_ev_bonus += vp_prob

        elif step.type == ActionType.PLAY_DEV_CARD:
            ctype = step.payload

            # Guard against illegal rollouts (e.g. playing hidden/unknown opponent cards).
            if player.dev_cards.get(ctype, 0) <= 0:
                return

            player.remove_card(ctype)

            if ctype == DevelopmentCardType.KNIGHT:
                # Largest Army is relative, so update using opponents' current army sizes.
                opp_armies = [p.army_size for num, p in overlay.sim_players.items() if num != player.player_number]
                player.add_knight(opp_armies)

        elif step.type == ActionType.TRADE_WITH_BANK:
            # Rollouts treat trades deterministically as a resource conversion.
            selling, buying = step.payload
            player.remove_resources(selling)
            player.add_resources(buying)

        elif step.type == ActionType.TRADE_WITH_PLAYER:
            # Same as bank trade in rollout: we give selling, receive buying.
            selling, buying = step.payload
            player.remove_resources(selling)
            player.add_resources(buying)

    def last_trade_rejected(self, player: SimPlayerState) -> bool:
        """Return True if the last trade was proposed but resources did not change."""
        if not self._last_trade_proposed or self._last_trade_resources is None:
            return False
        return self._last_trade_resources == player.resources

    def _choose_max_utility_action(
        self, player: SimPlayerState, sim_game: SimGame, utilities: List[Tuple[Action, float]],
        ignore_affordability: bool = False, include_player_trades: bool = True,
    ) -> Action:
        """Select the max-utility action, optionally inserting bank/player trades."""
        best_action: Optional[Action] = None
        best_utility = float("-inf")

        for action, utility in utilities:
            cost = calc_step_resources(action)

            # If we can already do it (or we're in a planning mode), just compare utilities.
            if player.can_afford(cost) or ignore_affordability:
                if utility > best_utility:
                    best_utility = utility
                    best_action = action
                continue

            # Otherwise, try a single bank/port trade that would unlock the action.
            bank_trade_action = get_bank_trade_for_action(player, cost)
            if bank_trade_action and utility > best_utility:
                best_utility = utility
                best_action = bank_trade_action

            # If player trades are allowed, propose one missing resource trade (but avoid spamming repeats).
            if include_player_trades and not self.last_trade_rejected(player):
                player_deficit, player_excesses = self._calculate_deficits_and_excesses(player.resources, cost)
                missing = next((r for r, v in player_deficit.items() if v > 0), None)
                if missing is not None:
                    sim_game_for_trade = _sim_game_with_replaced_player(sim_game, player)
                    opponents = get_opponents(sim_game_for_trade, player.player_number)
                    trade_action = propose_trade(player, sim_game_for_trade, missing, player_excesses, opponents, self)
                    if trade_action and utility > best_utility:
                        best_utility = utility
                        best_action = trade_action

        return best_action if best_action is not None else Action(ActionType.END_TURN)

    def _choose_max_utility_action_with_candidate(
        self, player: SimPlayerState, sim_game: SimGame, candidates: List[CandidateExplanation],
        ignore_affordability: bool = False, include_player_trades: bool = True, use_time_discount: bool = True,
    ) -> Tuple[Action, CandidateExplanation]:
        """Select the max-utility action, optionally inserting bank/player trades."""
        best_action: Optional[Action] = None
        best_candidate: Optional[CandidateExplanation] = None
        best_utility = float("-inf")

        for candidate in candidates:
            action = candidate.action
            utility = candidate.utility_total
            cost = calc_step_resources(action)

            # If we can already do it (or we're in a planning mode), just compare utilities.
            if player.can_afford(cost) or ignore_affordability:
                if utility > best_utility:
                    best_utility = utility
                    best_action = action
                    best_candidate = candidate
                continue

            # Otherwise, try a single bank/port trade that would unlock the action.
            bank_trade_action = get_bank_trade_for_action(player, cost)
            if bank_trade_action and utility > best_utility:
                best_utility = utility
                best_action = bank_trade_action
                best_candidate = CandidateExplanation(
                    action=bank_trade_action, full_plan=[bank_trade_action] + candidate.full_plan,
                    next_plan=list(candidate.next_plan), waiting_resources=dict(candidate.waiting_resources),
                    etb=candidate.etb, etw_before=candidate.etw_before, etw_after=candidate.etw_after,
                    etw_delta=candidate.etw_delta, utility_total=candidate.utility_total,
                    utility_self=candidate.utility_self, utility_opponent=candidate.utility_opponent,
                    utility_special=candidate.utility_special, utility_attention=candidate.utility_attention,
                    expected_vp_gain=candidate.expected_vp_gain,
                    reasons_for=[
                        Reason(ReasonType.REQUIRES_TRADE, ReasonLabel.REQUIRES_TRADE, max(1.0, candidate.utility_total))
                    ] + list(candidate.reasons_for),
                    reasons_against=list(candidate.reasons_against),
                    metadata={**candidate.metadata, "trade_inserted": True, "enabled_action": candidate.action},
                )

            # If player trades are allowed, propose one missing resource trade (but avoid spamming repeats).
            if include_player_trades and not self.last_trade_rejected(player):
                player_deficit, player_excesses = self._calculate_deficits_and_excesses(player.resources, cost)
                missing = next((r for r, v in player_deficit.items() if v > 0), None)
                if missing is not None:
                    sim_game_for_trade = _sim_game_with_replaced_player(sim_game, player)
                    opponents = get_opponents(sim_game_for_trade, player.player_number)
                    trade_action = propose_trade(player, sim_game_for_trade, missing, player_excesses, opponents, self)
                    if trade_action and utility > best_utility:
                        best_utility = utility
                        best_action = trade_action
                        best_candidate = CandidateExplanation(
                            action=trade_action, full_plan=[trade_action] + candidate.full_plan,
                            next_plan=list(candidate.next_plan), waiting_resources=dict(candidate.waiting_resources),
                            etb=candidate.etb, etw_before=candidate.etw_before,
                            etw_after=candidate.etw_after, etw_delta=candidate.etw_delta,
                            utility_total=candidate.utility_total, utility_self=candidate.utility_self,
                            utility_opponent=candidate.utility_opponent,
                            utility_special=candidate.utility_special,
                            utility_attention=candidate.utility_attention,
                            expected_vp_gain=candidate.expected_vp_gain,
                            reasons_for=[
                                Reason(
                                    ReasonType.REQUIRES_TRADE, ReasonLabel.REQUIRES_TRADE,
                                    max(1.0, candidate.utility_total),
                                )
                            ] + list(candidate.reasons_for),
                            reasons_against=list(candidate.reasons_against),
                            metadata={**candidate.metadata, "trade_inserted": True, "enabled_action": candidate.action},
                        )

        if best_action is not None and best_candidate is not None:
            return best_action, best_candidate

        fallback = self._build_end_turn_candidate(
            player,
            sim_game,
            max((candidate.etw_before for candidate in candidates), default=0.0),
            max(candidates, key=lambda c: c.utility_total, default=None),
            use_time_discount=use_time_discount,
        )
        return fallback.action, fallback

    def calculate_best_game_action(
        self, sim_game: SimGame, player_number: PlayerNumber, dev_played: bool,
        ignore_affordability: bool = False, ignore_opponents: bool = False, include_player_trades: bool = True,
        use_time_discount: bool = True, allow_development_cards: bool = True, use_planning: bool = True,
    ) -> Action:
        """Return the best next action for the given player number using the SimGame overlay."""
        sim_player = sim_game.overlay.get_sim_player(player_number)

        # Baseline ETW for scoring self-improvement.
        etw_before = self.estimated_time_to_win(
            sim_player.copy(),
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )

        # Opponent ETWs are only needed when we want interference scoring.
        opponents_etw_before: Dict[PlayerNumber, float] = {}
        if not ignore_opponents:
            for opp in get_opponents(sim_game, player_number):
                opponents_etw_before[opp.player_number] = self.estimated_time_to_win(
                    opp.copy(),
                    sim_game,
                    False,
                    include_player_trades=include_player_trades,
                    allow_development_cards=allow_development_cards,
                    use_planning=use_planning,
                )

        # Generate a small, pruned action set to keep rollout evaluation tractable.
        candidates = self._get_candidate_actions(
            sim_player,
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )
        if not candidates:
            return Action(ActionType.END_TURN)

        # Convert candidate plans into (next-step, utility) scores via rollouts + ETW deltas.
        utilities = self.evaluate_utilities(
            sim_player,
            sim_game,
            dev_played,
            candidates,
            etw_before,
            opponents_etw_before,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
            use_time_discount=use_time_discount,
        )
        if not utilities:
            return Action(ActionType.END_TURN)

        # Hidden-information heuristic: favour dev cards when they are "close enough" to the best alternative.
        best_build = max(
            (u for u in utilities if u[0].type != ActionType.BUY_DEV_CARD), default=None, key=lambda x: x[1],
        )
        best_dev = max((u for u in utilities if u[0].type == ActionType.BUY_DEV_CARD), default=None, key=lambda x: x[1])

        if allow_development_cards and (not ignore_affordability) and best_build is not None and best_dev is not None:
            if best_dev[1] >= best_build[1] * (1.0 - StrategyWeights.DEV_CLOSE_THRESHOLD):
                utilities = [best_dev]

        # Final selection can insert a trade step if the top action isn't currently affordable.
        return self._choose_max_utility_action(
            sim_player,
            sim_game,
            utilities,
            ignore_affordability=ignore_affordability,
            include_player_trades=include_player_trades,
        )

    def evaluate_candidates_with_explanations(
        self, player: SimPlayerState, sim_game: SimGame, dev_played: bool,
        candidates: List[Tuple[List[Action], float, float]], etw_before: float,
        opponents_etw_before: Dict[PlayerNumber, float], include_player_trades: bool = True,
        allow_development_cards: bool = True, use_planning: bool = True, use_time_discount: bool = True,
    ) -> List[CandidateExplanation]:
        """Evaluate candidates and return structured explanations."""
        explained: List[CandidateExplanation] = []

        candidates.sort(key=lambda x: x[1])
        max_eval = min(MAX_EVALUATIONS, len(candidates))

        for actions, etb, vp_inc in candidates[:max_eval]:
            candidate = self._evaluate_action_plan(
                player,
                sim_game,
                dev_played,
                actions,
                etb,
                vp_inc,
                etw_before,
                opponents_etw_before,
                include_player_trades=include_player_trades,
                allow_development_cards=allow_development_cards,
                use_planning=use_planning,
                use_time_discount=use_time_discount,
            )
            if candidate is not None:
                explained.append(candidate)

        deferred_candidate = max(explained, key=lambda c: c.utility_total, default=None)
        explained.append(self._build_end_turn_candidate(
            player,
            sim_game,
            etw_before,
            deferred_candidate,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
            use_time_discount=use_time_discount,
        ))
        explained.sort(key=lambda c: c.utility_total, reverse=True)
        return explained

    def explain_action(
        self,
        sim_game: SimGame,
        player_number: PlayerNumber,
        dev_played: bool,
        action: Action,
        ignore_opponents: bool = False,
        include_player_trades: bool = True,
        use_time_discount: bool = True,
        allow_development_cards: bool = True,
        use_planning: bool = True,
    ) -> ActionExplanation:
        sim_player = sim_game.overlay.get_sim_player(player_number)
        etw_before = self.estimated_time_to_win(
            sim_player.copy(),
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )

        opponents_etw_before: Dict[PlayerNumber, float] = {}
        if not ignore_opponents:
            for opp in get_opponents(sim_game, player_number):
                opponents_etw_before[opp.player_number] = self.estimated_time_to_win(
                    opp.copy(),
                    sim_game,
                    False,
                    include_player_trades=include_player_trades,
                    allow_development_cards=allow_development_cards,
                    use_planning=use_planning,
                )

        candidates = self._get_candidate_actions(
            sim_player,
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )
        explained_candidates = self.evaluate_candidates_with_explanations(
            sim_player,
            sim_game,
            dev_played,
            candidates,
            etw_before,
            opponents_etw_before,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
            use_time_discount=use_time_discount,
        ) if candidates else []

        chosen_candidate = next((candidate for candidate in explained_candidates if candidate.action == action), None)
        if chosen_candidate is None:
            chosen_candidate = self._evaluate_action_plan(
                sim_player,
                sim_game,
                dev_played,
                [action],
                self._estimate_single_action_etb(
                    sim_player,
                    sim_game,
                    action,
                    include_player_trades=include_player_trades,
                ),
                0.0,
                etw_before,
                opponents_etw_before,
                include_player_trades=include_player_trades,
                allow_development_cards=allow_development_cards,
                use_planning=use_planning,
                use_time_discount=use_time_discount,
            )

        if chosen_candidate is None:
            chosen_candidate = CandidateExplanation(
                action=action,
                full_plan=[action],
                etw_before=etw_before,
                etw_after=etw_before,
                etw_delta=0.0,
                utility_total=0.0,
                reasons_for=[],
            )

        alternatives = [
            candidate for candidate in explained_candidates
            if candidate.action != chosen_candidate.action
        ][:3]
        worst_utility = (
            explained_candidates[-1].utility_total
            if explained_candidates
            else chosen_candidate.utility_total
        )

        return ActionExplanation(
            chosen_action=chosen_candidate.action,
            chosen_candidate=chosen_candidate,
            alternatives=alternatives,
            move_quality=strategic_turn_move_quality(
                chosen_candidate,
                alternatives[0].utility_total if alternatives else None,
                worst_utility,
            ),
            assumptions=[AssumptionCode.EXPECTED_PRODUCTION, AssumptionCode.LEGALITY_AND_AFFORDABILITY],
            metadata={"player_number": player_number, "etw_before": etw_before},
        )

    def calculate_best_game_action_with_explanation(
        self, sim_game: SimGame, player_number: PlayerNumber, dev_played: bool,
        ignore_affordability: bool = False, ignore_opponents: bool = False, include_player_trades: bool = True,
        use_time_discount: bool = True, allow_development_cards: bool = True, use_planning: bool = True,
    ) -> ActionExplanation:
        sim_player = sim_game.overlay.get_sim_player(player_number)

        etw_before = self.estimated_time_to_win(
            sim_player.copy(),
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )

        opponents_etw_before: Dict[PlayerNumber, float] = {}
        if not ignore_opponents:
            for opp in get_opponents(sim_game, player_number):
                opponents_etw_before[opp.player_number] = self.estimated_time_to_win(
                    opp.copy(),
                    sim_game,
                    False,
                    include_player_trades=include_player_trades,
                    allow_development_cards=allow_development_cards,
                    use_planning=use_planning,
                )

        candidates = self._get_candidate_actions(
            sim_player,
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )
        if not candidates:
            chosen = CandidateExplanation(
                action=Action(ActionType.END_TURN), full_plan=[Action(ActionType.END_TURN)],
                next_plan=[], waiting_resources={}, etw_before=etw_before, etw_after=etw_before,
                etw_delta=0.0, utility_total=0.0, reasons_for=[],
            )
            return ActionExplanation(
                chosen_action=chosen.action,
                chosen_candidate=chosen,
                alternatives=[],
                move_quality=strategic_turn_move_quality(chosen),
                assumptions=[AssumptionCode.NO_CANDIDATE_ACTION],
            )

        explained_candidates = self.evaluate_candidates_with_explanations(
            sim_player,
            sim_game,
            dev_played,
            candidates,
            etw_before,
            opponents_etw_before,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
            use_time_discount=use_time_discount,
        )

        if not explained_candidates:
            next_plan, waiting_resources = (
                self._future_plan_fields(sim_player, candidates[0][0]) if candidates else ([], {})
            )
            chosen = CandidateExplanation(
                action=Action(ActionType.END_TURN), full_plan=[Action(ActionType.END_TURN)],
                next_plan=next_plan, waiting_resources=waiting_resources, etw_before=etw_before,
                etw_after=etw_before, etw_delta=0.0, utility_total=0.0, reasons_for=[],
            )
            return ActionExplanation(
                chosen_action=chosen.action,
                chosen_candidate=chosen,
                alternatives=[],
                move_quality=strategic_turn_move_quality(chosen),
                assumptions=[AssumptionCode.FILTERED_CANDIDATES],
            )

        chosen_action, chosen_candidate = self._choose_max_utility_action_with_candidate(
            sim_player,
            sim_game,
            explained_candidates,
            ignore_affordability=ignore_affordability,
            include_player_trades=include_player_trades,
            use_time_discount=use_time_discount,
        )

        alternatives = [c for c in explained_candidates if c.full_plan != chosen_candidate.full_plan][:3]

        return ActionExplanation(
            chosen_action=chosen_action, chosen_candidate=chosen_candidate, alternatives=alternatives,
            move_quality=strategic_turn_move_quality(
                chosen_candidate,
                alternatives[0].utility_total if alternatives else None,
                explained_candidates[-1].utility_total if explained_candidates else None,
            ),
            assumptions=[AssumptionCode.EXPECTED_PRODUCTION, AssumptionCode.LEGALITY_AND_AFFORDABILITY],
            metadata={"player_number": player_number, "etw_before": etw_before},
        )
