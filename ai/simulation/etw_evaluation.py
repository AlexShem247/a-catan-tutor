import math
from typing import Any, Dict, List, Optional, Tuple, cast

from ai.actions import Action, ActionType
from ai.simulation.SimGame import SimGame
from ai.simulation.SimPlayerState import SimPlayerState
from ai.tutor.explanations import (
    CandidateExplanation,
    Reason,
    ReasonLabel,
    ReasonType,
)
from ai.utils.action_utils import compute_k_la
from ai.utils.resource_utils import calc_step_resources
from config.StrategyWeights import StrategyWeights
from config.performance_constants import (
    ETW_ETB_THRESHOLD,
    ETW_MAX_DEPTH_OFFSET,
    EVAL_UTIL_MAX_DEPTH,
    MAX_ETB_THRESHOLD,
    MAX_EVALUATIONS,
)
from game.Game import Game
from game.Player import PlayerNumber
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount


def sim_game_with_replaced_player(sim_game: SimGame, sim_player: SimPlayerState) -> SimGame:
    overlay = sim_game.overlay.copy()
    overlay.set_sim_player(sim_player)
    return SimGame(game=sim_game.game, overlay=overlay)


class EtwEvaluation:
    def __init__(self, timing, candidates, eval_stats: Dict[str, int]):
        self.timing = timing
        self.candidates = candidates
        self._eval_stats = eval_stats
        self.estimator = None

    @staticmethod
    def _apply_time_discount(utility: float, etb: float, use_time_discount: bool) -> float:
        if not use_time_discount:
            return utility
        discount_rate = StrategyWeights.TIME_DISCOUNT_RATE
        return utility / ((1.0 + discount_rate) ** max(1.0, etb))

    def estimated_time_to_win(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        dev_played: bool,
        include_player_trades: bool = True,
        max_depth_override: Optional[int] = None,
        allow_development_cards: bool = True,
        use_planning: bool = True,
    ) -> float:
        cache_key = (
            player.player_number,
            dev_played,
            include_player_trades,
            max_depth_override,
            allow_development_cards,
            use_planning,
            len(player.settlements),
            len(player.cities),
            len(player.roads),
            tuple((resource.value, player.resources.get(resource, 0)) for resource in Resource),
        )
        if cache_key in player.etw_cache:
            return player.etw_cache[cache_key]

        points = player.victory_points()
        if points >= Game.VICTORY_POINTS_TO_WIN:
            player.etw_cache[cache_key] = 0.0
            return 0.0

        etw = 0.0
        iterations = 0
        default_depth = max(
            1,
            math.ceil(min(Game.VICTORY_POINTS_TO_WIN + ETW_MAX_DEPTH_OFFSET - points, ETW_MAX_DEPTH_OFFSET)),
        )
        if max_depth_override is not None:
            max_depth = max(1, int(max_depth_override))
            max_depth = min(max_depth, default_depth)
        else:
            max_depth = default_depth

        sim_player = player.copy()
        sim_game_local = sim_game_with_replaced_player(sim_game, sim_player)
        while points < Game.VICTORY_POINTS_TO_WIN and iterations < max_depth:
            candidate_actions = self.candidates.get_candidate_actions(
                sim_player,
                sim_game_local,
                dev_played,
                include_player_trades,
                allow_development_cards=allow_development_cards,
                use_planning=use_planning,
            )
            if not candidate_actions:
                etw += StrategyWeights.ETW_NO_ACTION_PENALTY
                break

            actions, etb_step, _ = candidate_actions[0]
            if etb_step > ETW_ETB_THRESHOLD:
                etw += StrategyWeights.ETW_NO_ACTION_PENALTY
                break

            etw += etb_step
            self._simulate_plan_until_win(sim_game_local, sim_player, actions)
            points = sim_player.victory_points()
            iterations += 1

        if max_depth_override is None and points < Game.VICTORY_POINTS_TO_WIN:
            etw += (Game.VICTORY_POINTS_TO_WIN - points) * StrategyWeights.ETW_MISSING_POINT_PENALTY

        player.etw_cache[cache_key] = etw
        return etw

    def _estimate_time_to_win(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        dev_played: bool,
        include_player_trades: bool = True,
        max_depth_override: Optional[int] = None,
        allow_development_cards: bool = True,
        use_planning: bool = True,
    ) -> float:
        if self.estimator is not None:
            return self.estimator.estimated_time_to_win(
                player,
                sim_game,
                dev_played,
                include_player_trades=include_player_trades,
                max_depth_override=max_depth_override,
                allow_development_cards=allow_development_cards,
                use_planning=use_planning,
            )
        return self.estimated_time_to_win(
            player,
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            max_depth_override=max_depth_override,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )

    def _simulate_plan_until_win(self, sim_game: SimGame, player: SimPlayerState, actions: List[Action]) -> None:
        for step in actions:
            self._simulate_step(sim_game, player, step)
            if player.victory_points() >= Game.VICTORY_POINTS_TO_WIN:
                break

    def simulate_step(self, sim_game: SimGame, player: SimPlayerState, step: Action) -> None:
        self._simulate_step(sim_game, player, step)

    @staticmethod
    def _plan_resource_cost(actions: List[Action]) -> ResourceCount:
        total_resources: ResourceCount = {resource: 0 for resource in Resource}
        for action in actions:
            step_resources = calc_step_resources(action)
            for resource, cost in step_resources.items():
                total_resources[resource] = total_resources.get(resource, 0) + cost
        return total_resources

    def _plan_waiting_resources(self, player: SimPlayerState, actions: List[Action]) -> ResourceCount:
        total_resources = self._plan_resource_cost(actions)
        deficits, _ = self.timing.calculate_deficits_and_excesses(player.resources, total_resources)
        return {resource: amount for resource, amount in deficits.items() if amount > 0}

    def _next_step_waiting_resources(self, player: SimPlayerState, actions: List[Action]) -> ResourceCount:
        if not actions:
            return {}
        return self._plan_waiting_resources(player, [actions[0]])

    def _future_plan_fields(self, player: SimPlayerState, actions: List[Action]) -> Tuple[List[Action], ResourceCount]:
        if not actions:
            return [], {}
        return list(actions), self._next_step_waiting_resources(player, actions)

    def future_plan_fields(self, player: SimPlayerState, actions: List[Action]) -> Tuple[List[Action], ResourceCount]:
        return self._future_plan_fields(player, actions)

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
            expected_resources[resource] = expected_resources.get(resource, 0.0) + player.get_production_rate(resource)

        sim_game_after_wait = sim_game_with_replaced_player(sim_game, player_after_wait)
        etw_after_wait = 1.0 + self._estimate_time_to_win(
            player_after_wait,
            sim_game_after_wait,
            False,
            max_depth_override=EVAL_UTIL_MAX_DEPTH,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )
        etw_delta = etw_before - etw_after_wait
        utility_self = 0.0 if etw_before <= 0 else max(0.0, (etw_delta / etw_before) * 100.0)
        utility_total = self._apply_time_discount(
            StrategyWeights.BUILD_SELF_UTILITY * utility_self,
            1.0,
            use_time_discount,
        )

        next_plan: List[Action] = []
        waiting_resources: ResourceCount = {}
        reasons_for: List[Reason] = [
            Reason(
                type=ReasonType.HEURISTIC_CHOICE,
                label=ReasonLabel.NO_IMMEDIATE_ACTION,
                value=max(0.0, utility_self),
            )
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
            utility_self=utility_self,
            utility_opponent=0.0,
            utility_special=0.0,
            utility_attention=0.0,
            expected_vp_gain=0.0,
            reasons_for=reasons_for,
            reasons_against=reasons_against,
        )

    def build_end_turn_candidate(
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
        return self._build_end_turn_candidate(
            player,
            sim_game,
            etw_before,
            deferred_candidate,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
            use_time_discount=use_time_discount,
        )

    @staticmethod
    def _quick_reason_label(next_step: Action, final_step: Action) -> Tuple[ReasonLabel, Dict[str, Any]]:
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

    @staticmethod
    def _leading_opponent_etw(opponents_etw_before: Dict[PlayerNumber, float]) -> Optional[Tuple[PlayerNumber, float]]:
        if not opponents_etw_before:
            return None
        leading_opp_num = min(opponents_etw_before, key=lambda player_number: opponents_etw_before[player_number])
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
        sim_game_copy = sim_game_with_replaced_player(sim_game, player_copy)
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

        etw_after = self._estimate_time_to_win(
            player_copy,
            sim_game_copy,
            dev_played,
            max_depth_override=EVAL_UTIL_MAX_DEPTH,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )
        etw_delta = etw_before - etw_after
        utility_self = 0.0 if etw_before <= 0 else max(0.0, etw_delta / etw_before * 100.0)
        affects_board = any(
            step.type == ActionType.BUILD and step.payload[0] in (Buildable.ROAD, Buildable.SETTLEMENT)
            for step in actions
        )

        utility_opponent = 0.0
        blocks_opponent = False
        leader_etw = self._leading_opponent_etw(opponents_etw_before)
        if affects_board and leader_etw is not None:
            leading_opp_num, opp_etw_before = leader_etw
            if opp_etw_before > 0:
                opp_state = sim_game_copy.overlay.get_sim_player(leading_opp_num).copy()
                sim_game_opp = sim_game_with_replaced_player(sim_game_copy, opp_state)
                opp_etw_after = self._estimate_time_to_win(
                    opp_state,
                    sim_game_opp,
                    False,
                    max_depth_override=EVAL_UTIL_MAX_DEPTH,
                    include_player_trades=include_player_trades,
                    allow_development_cards=allow_development_cards,
                    use_planning=use_planning,
                )
                delay_caused = (opp_etw_after - opp_etw_before) / opp_etw_before * 100.0
                utility_opponent = StrategyWeights.OPPONENT_INTERFERENCE_LEADING * delay_caused
                blocks_opponent = delay_caused > 0.0

        utility_special = 0.0
        improves_longest_road = False
        improves_largest_army = False
        if did_build_road:
            delta_lr = max(0, player_copy.longest_road_length - player.longest_road_length)
            if delta_lr > 0 and player_copy.longest_road_length >= StrategyWeights.LR_ROAD_THRESHOLD:
                utility_special += StrategyWeights.LR_UTILITY_MULTIPLIER * delta_lr
                improves_longest_road = True
        if did_play_knight and player_copy.army_size >= StrategyWeights.LA_ARMY_THRESHOLD:
            utility_special += compute_k_la(player_copy, sim_game)
            improves_largest_army = True

        took_lr_now = (not player.has_longest_road) and player_copy.has_longest_road
        vp_after = player_copy.victory_points()
        utility_attention = 0.0
        if took_lr_now and vp_after < StrategyWeights.ATTENTION_LR_VP_THRESHOLD:
            utility_attention -= StrategyWeights.ATTENTION_LR_EARLY_PENALTY

        utility_total = self._apply_time_discount(
            StrategyWeights.BUILD_SELF_UTILITY * utility_self
            + StrategyWeights.BUILD_OPPONENT_UTILITY * utility_opponent
            + StrategyWeights.BUILD_SPECIAL_UTILITY * utility_special
            + utility_attention,
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
                    type=ReasonType.ENABLES_EXPANSION,
                    label=ReasonLabel.PLAN_SETTLEMENT_VALUE,
                    value=max(utility_self * 0.9, 1.0),
                ))
            elif building == Buildable.CITY:
                reasons_for.append(Reason(
                    type=ReasonType.IMPROVES_PRODUCTION,
                    label=ReasonLabel.PLAN_CITY_VALUE,
                    value=max(utility_self * 0.8, 1.0),
                ))
            elif building == Buildable.ROAD:
                reasons_for.append(Reason(
                    type=ReasonType.ENABLES_EXPANSION,
                    label=ReasonLabel.PLAN_ROAD_VALUE,
                    value=max(utility_self * 0.7, 1.0),
                ))

        if etb <= 2.5:
            quick_label, quick_meta = self._quick_reason_label(next_step, final_step)
            reasons_for.append(Reason(
                type=ReasonType.QUICK_TO_EXECUTE,
                label=quick_label,
                metadata=quick_meta,
                value=max(0.0, 5.0 - etb),
            ))
        if blocks_opponent and utility_opponent > 0:
            reasons_for.append(Reason(
                type=ReasonType.SLOWS_LEADING_OPPONENT,
                label=ReasonLabel.SLOWS_LEADER,
                value=utility_opponent,
            ))
        if improves_longest_road:
            reasons_for.append(Reason(
                type=ReasonType.ADVANCES_LONGEST_ROAD,
                label=ReasonLabel.ADVANCES_LONGEST_ROAD,
                value=utility_special,
            ))
        if improves_largest_army:
            reasons_for.append(Reason(
                type=ReasonType.ADVANCES_LARGEST_ARMY,
                label=ReasonLabel.ADVANCES_LARGEST_ARMY,
                value=utility_special,
            ))
        if next_step.type in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER):
            reasons_for.append(Reason(type=ReasonType.REQUIRES_TRADE, label=ReasonLabel.REQUIRES_TRADE, value=1.0))
        if next_step.type == ActionType.BUY_DEV_CARD and vp_inc > 0:
            reasons_for.append(Reason(type=ReasonType.HIDDEN_VALUE, label=ReasonLabel.HIDDEN_DEV_VALUE, value=vp_inc))
        if utility_attention < 0:
            reasons_against.append(Reason(
                type=ReasonType.AVOIDS_EARLY_ATTENTION,
                label=ReasonLabel.EARLY_ATTENTION_RISK,
                value=abs(utility_attention),
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
            utility_self=utility_self,
            utility_opponent=utility_opponent,
            utility_special=utility_special,
            utility_attention=utility_attention,
            expected_vp_gain=vp_inc,
            reasons_for=reasons_for,
            reasons_against=reasons_against,
            metadata={
                "blocks_opponent": blocks_opponent,
                "improves_longest_road": improves_longest_road,
                "improves_largest_army": improves_largest_army,
            },
        )

    def evaluate_action_plan(
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
        return self._evaluate_action_plan(
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

    def evaluate_utilities(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        dev_played: bool,
        candidates: List[Tuple[List[Action], float, float]],
        etw_before: float,
        opponents_etw_before: Dict[PlayerNumber, float],
        include_player_trades: bool = True,
        allow_development_cards: bool = True,
        use_planning: bool = True,
        use_time_discount: bool = True,
    ) -> List[Tuple[Action, float]]:
        self._eval_stats["evaluations"] += 1
        utilities: List[Tuple[Action, float]] = []
        candidates.sort(key=lambda candidate_item: candidate_item[1])
        max_eval = min(MAX_EVALUATIONS, len(candidates))
        leader_etw = self._leading_opponent_etw(opponents_etw_before)

        for action_plan, etb, _vp_inc in candidates[:max_eval]:
            if etb > MAX_ETB_THRESHOLD or not action_plan:
                continue

            next_step = action_plan[0]
            player_copy = player.copy()
            sim_game_copy = sim_game_with_replaced_player(sim_game, player_copy)
            did_build_road = False
            did_play_knight = False
            for step in action_plan:
                if step.type == ActionType.BUILD and step.payload[0] == Buildable.ROAD:
                    did_build_road = True
                elif step.type == ActionType.PLAY_DEV_CARD and step.payload == DevelopmentCardType.KNIGHT:
                    did_play_knight = True
                self._simulate_step(sim_game_copy, player_copy, step)
                if player_copy.victory_points() >= Game.VICTORY_POINTS_TO_WIN:
                    break

            etw_after = self._estimate_time_to_win(
                player_copy,
                sim_game_copy,
                dev_played,
                max_depth_override=EVAL_UTIL_MAX_DEPTH,
                include_player_trades=include_player_trades,
                allow_development_cards=allow_development_cards,
                use_planning=use_planning,
            )
            utility_self = 0.0 if etw_before <= 0 else max(0.0, (etw_before - etw_after) / etw_before * 100.0)
            affects_board = any(
                step.type == ActionType.BUILD and step.payload[0] in (Buildable.ROAD, Buildable.SETTLEMENT)
                for step in action_plan
            )

            utility_opponent = 0.0
            if affects_board and leader_etw is not None:
                leading_opp_num, opp_etw_before = leader_etw
                opp_state = sim_game_copy.overlay.get_sim_player(leading_opp_num).copy()
                sim_game_opp = sim_game_with_replaced_player(sim_game_copy, opp_state)
                if opp_etw_before > 0:
                    opp_etw_after = self._estimate_time_to_win(
                        opp_state,
                        sim_game_opp,
                        False,
                        max_depth_override=EVAL_UTIL_MAX_DEPTH,
                        include_player_trades=include_player_trades,
                        allow_development_cards=allow_development_cards,
                        use_planning=use_planning,
                    )
                    delay_caused = (opp_etw_after - opp_etw_before) / opp_etw_before * 100.0
                    utility_opponent = StrategyWeights.OPPONENT_INTERFERENCE_LEADING * delay_caused

            utility_special = 0.0
            if did_build_road:
                delta_lr = max(0, player_copy.longest_road_length - player.longest_road_length)
                if delta_lr > 0 and player_copy.longest_road_length >= StrategyWeights.LR_ROAD_THRESHOLD:
                    utility_special += StrategyWeights.LR_UTILITY_MULTIPLIER * delta_lr
            if did_play_knight and player_copy.army_size >= StrategyWeights.LA_ARMY_THRESHOLD:
                utility_special += compute_k_la(player_copy, sim_game)

            took_lr_now = (not player.has_longest_road) and player_copy.has_longest_road
            vp_after = player_copy.victory_points()
            utility_attention = 0.0
            if took_lr_now and vp_after < StrategyWeights.ATTENTION_LR_VP_THRESHOLD:
                utility_attention -= StrategyWeights.ATTENTION_LR_EARLY_PENALTY

            utility_total = self._apply_time_discount(
                StrategyWeights.BUILD_SELF_UTILITY * utility_self
                + StrategyWeights.BUILD_OPPONENT_UTILITY * utility_opponent
                + StrategyWeights.BUILD_SPECIAL_UTILITY * utility_special
                + utility_attention,
                etb,
                use_time_discount,
            )
            utilities.append((next_step, utility_total))

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

    def evaluate_candidates_with_explanations(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        dev_played: bool,
        candidates: List[Tuple[List[Action], float, float]],
        etw_before: float,
        opponents_etw_before: Dict[PlayerNumber, float],
        include_player_trades: bool = True,
        allow_development_cards: bool = True,
        use_planning: bool = True,
        use_time_discount: bool = True,
    ) -> List[CandidateExplanation]:
        explained: List[CandidateExplanation] = []
        candidates.sort(key=lambda candidate_item: candidate_item[1])
        max_eval = min(MAX_EVALUATIONS, len(candidates))
        for action_plan, etb, vp_inc in candidates[:max_eval]:
            candidate_explanation = self._evaluate_action_plan(
                player,
                sim_game,
                dev_played,
                action_plan,
                etb,
                vp_inc,
                etw_before,
                opponents_etw_before,
                include_player_trades=include_player_trades,
                allow_development_cards=allow_development_cards,
                use_planning=use_planning,
                use_time_discount=use_time_discount,
            )
            if candidate_explanation is not None:
                explained.append(candidate_explanation)

        deferred_candidate = max(
            explained,
            key=lambda explained_candidate: explained_candidate.utility_total,
            default=None,
        )
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
        explained.sort(key=lambda explained_candidate: explained_candidate.utility_total, reverse=True)
        return explained

    def _simulate_step(self, sim_game: SimGame, player: SimPlayerState, step: Action) -> None:
        overlay = sim_game.overlay

        def _pay(cost: ResourceCount) -> None:
            for resource, count in cost.items():
                if count <= 0:
                    continue
                player.resources[resource] = max(0, player.resources.get(resource, 0) - count)

        if step.type == ActionType.BUILD:
            building, location = step.payload
            _pay(Game.BUILDING_COST[building])
            if building == Buildable.ROAD:
                opponent_lengths = [
                    other_player.longest_road_length
                    for number, other_player in overlay.sim_players.items()
                    if number != player.player_number
                ]
                player.build_road(location, opponent_lengths)
                overlay.claim_edge(location, player.player_number)
            elif building == Buildable.SETTLEMENT:
                player.build_settlement(location)
                overlay.claim_vertex(location, player.player_number)
            elif building == Buildable.CITY:
                player.build_city(location)
                overlay.claim_vertex(location, player.player_number)
        elif step.type == ActionType.BUY_DEV_CARD:
            _pay(Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD])
            deck = sim_game.game.development_deck
            if not deck.empty():
                vp_prob = deck.get_probability(DevelopmentCardType.VICTORY_POINT, player.dev_cards)
                player.vp_ev_bonus += vp_prob
        elif step.type == ActionType.PLAY_DEV_CARD:
            card_type = step.payload
            if player.dev_cards.get(card_type, 0) <= 0:
                return
            player.remove_card(card_type)
            if card_type == DevelopmentCardType.KNIGHT:
                opponent_armies = [
                    other_player.army_size
                    for number, other_player in overlay.sim_players.items()
                    if number != player.player_number
                ]
                player.add_knight(opponent_armies)
        elif step.type == ActionType.TRADE_WITH_BANK:
            selling, buying = step.payload
            player.remove_resources(selling)
            player.add_resources(buying)
        elif step.type == ActionType.TRADE_WITH_PLAYER:
            selling, buying = step.payload
            player.remove_resources(selling)
            player.add_resources(buying)
