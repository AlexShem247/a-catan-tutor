import math
from typing import Optional, List, Tuple, Dict, TYPE_CHECKING

from ai.ai_utils.SimGame import SimGame
from ai.ai_utils.SimPlayerState import SimPlayerState
from ai.ai_utils.actions import Action, ActionType
from ai.ai_utils.resource_utils import expected_rolls_for_resource
from config.StrategyWeights import StrategyWeights
from config.performance_constants import EPSILON, TRADE_ETW_SHORTLIST_K, CHECK_INVALID_TRADES_EARLY
from game.Resources import Resource, ResourceCount

if TYPE_CHECKING:
    from ai.ai_utils.EtwEstimator import EtwEstimator


def _sim_game_with_replaced_player(sim_game: SimGame, sim_player: SimPlayerState) -> SimGame:
    ov2 = sim_game.overlay.copy()
    ov2.set_sim_player(sim_player)
    return SimGame(game=sim_game.game, overlay=ov2)


def _generate_candidate_offers(
    R_need: Resource,
    surplus: ResourceCount,
    weights: StrategyWeights,
) -> List[Action]:
    fair_ratios: List[Tuple[int, int]] = [(k, 1) for k in range(1, weights.MAX_PLAYER_TRADE_GIVE_RATIO + 1)]
    offers: List[Action] = []

    sellables = [(r, q) for r, q in surplus.items() if q > 0 and r != R_need]
    if not sellables:
        return offers

    for give_ratio, take_ratio in fair_ratios:
        for r_give, max_give in sellables:
            max_k = max_give // give_ratio
            for k in range(1, max_k + 1):
                selling: ResourceCount = {r_give: k * give_ratio}
                buying: ResourceCount = {R_need: k * take_ratio}
                offers.append(Action(ActionType.TRADE_WITH_PLAYER, (selling, buying)))

        if give_ratio > 1:
            for i in range(len(sellables)):
                r1, q1 = sellables[i]
                for x in range(1, min(q1, give_ratio - 1) + 1):
                    y = give_ratio - x
                    for j in range(i + 1, len(sellables)):
                        r2, q2 = sellables[j]
                        if q2 < y:
                            continue

                        selling = {r1: x, r2: y}
                        buying = {R_need: take_ratio}
                        offers.append(Action(ActionType.TRADE_WITH_PLAYER, (selling, buying)))

    return offers


def _evaluate_etw_after_trade(
    player: SimPlayerState,
    sim_game: SimGame,
    etw_estimator: "EtwEstimator",
    trade: Action,
    weights: StrategyWeights,
) -> float:
    selling, buying = trade.payload
    sim_player = player.copy()
    sim_player.remove_resources(selling)
    sim_player.add_resources(buying)

    sim_game_after = _sim_game_with_replaced_player(sim_game, sim_player)
    return etw_estimator.estimated_time_to_win(
        sim_player,
        sim_game_after,
        False,
        weights,
        include_player_trades=False,
    )


def _estimate_opponent_benefit_etw(
    opponent: SimPlayerState,
    sim_game: SimGame,
    etw_estimator: "EtwEstimator",
    trade: Action,
    weights: StrategyWeights,
) -> float:
    selling_by_them, buying_from_us = trade.payload
    etw_before = etw_estimator.estimated_time_to_win(
        opponent,
        sim_game,
        False,
        weights,
        include_player_trades=False,
    )

    sim_opp = opponent.copy()
    sim_opp.add_resources(selling_by_them)
    sim_opp.remove_resources(buying_from_us)

    sim_game_after = _sim_game_with_replaced_player(sim_game, sim_opp)
    etw_after = etw_estimator.estimated_time_to_win(
        sim_opp,
        sim_game_after,
        False,
        weights,
        include_player_trades=False,
    )

    return max(0.0, etw_before - etw_after)


def _predict_acceptance_prob(_: SimPlayerState, delta_etw: float, trade: Action, weights: StrategyWeights) -> float:
    _, buying_from_them = trade.payload
    opp_cost = sum(buying_from_them.values())

    score = (
        weights.ACCEPT_ETW_WEIGHT * delta_etw
        - weights.ACCEPT_COST_WEIGHT * opp_cost
    )

    return 1.0 / (1.0 + math.exp(-score))


def _apply_trade_copy(player: SimPlayerState, trade: Action) -> SimPlayerState:
    selling, buying = trade.payload
    p2 = player.copy()
    p2.remove_resources(selling)
    p2.add_resources(buying)
    return p2


def _cheap_score_offer(
    player: SimPlayerState,
    sim_game: SimGame,
    etw_estimator: "EtwEstimator",
    trade: Action,
    p_accept: float,
    weights: StrategyWeights,
) -> float:
    _, buying = trade.payload
    target: ResourceCount = {r: q for r, q in buying.items()}
    etb_before = etw_estimator.estimated_time_to_build(
        player,
        sim_game,
        target,
        weights,
        include_player_trades=False,
    )

    p2 = _apply_trade_copy(player, trade)
    etb_after = etw_estimator.estimated_time_to_build(
        p2,
        sim_game,
        target,
        weights,
        include_player_trades=False,
    )

    if etb_after >= etb_before:
        return float("inf")

    return etb_after / max(p_accept, EPSILON)


def propose_trade(
    player: SimPlayerState,
    sim_game: SimGame,
    R_need: Resource,
    surplus: ResourceCount,
    opponents: List[SimPlayerState],
    etw_estimator: "EtwEstimator",
    weights: StrategyWeights,
) -> Optional[Action]:
    best_offer = None
    best_score = float("inf")

    all_players = [player, *opponents]
    etw_by_player = {
        p: etw_estimator.estimated_time_to_win(p.copy(), sim_game, False, weights, include_player_trades=False)
        for p in all_players
    }
    leading_player = min(etw_by_player, key=etw_by_player.get)

    batna_etw = etw_estimator.estimated_time_to_win(
        player,
        sim_game,
        False,
        weights,
        include_player_trades=False,
    )

    candidates = _generate_candidate_offers(R_need, surplus, weights)
    if not candidates:
        return None

    cheap_pool: List[Tuple[float, SimPlayerState, Action, float]] = []

    for opponent in opponents:
        rolls_per_unit = {r: expected_rolls_for_resource(opponent, r) for r in Resource}

        for offer in candidates:
            selling_by_us, buying_from_them = offer.payload

            if any(player.resources.get(r, 0) < q for r, q in selling_by_us.items()):
                continue

            if CHECK_INVALID_TRADES_EARLY:
                if any(opponent.resources.get(r, 0) < q for r, q in buying_from_them.items()):
                    continue

            benefit = (
                sum(q * rolls_per_unit[r] for r, q in selling_by_us.items())
                - sum(q * rolls_per_unit[r] for r, q in buying_from_them.items())
            )
            benefit = max(0.0, benefit)

            p_accept = _predict_acceptance_prob(opponent, benefit, offer, weights)
            if p_accept < weights.MIN_TRADE_ACCEPT_PROB:
                continue

            cheap_score = _cheap_score_offer(player, sim_game, etw_estimator, offer, p_accept, weights)
            if math.isinf(cheap_score):
                continue

            cheap_pool.append((cheap_score, opponent, offer, p_accept))

    if not cheap_pool:
        return None

    cheap_pool.sort(key=lambda x: x[0])
    shortlisted = cheap_pool[:max(1, TRADE_ETW_SHORTLIST_K)]

    for _, opponent, offer, p_accept in shortlisted:
        lambda_risk = weights.LAMBDA_RISK_LEADER if opponent == leading_player else weights.LAMBDA_RISK_BASE

        etw_after = _evaluate_etw_after_trade(player, sim_game, etw_estimator, offer, weights)
        if etw_after >= batna_etw:
            continue

        delta_etw_player = batna_etw - etw_after
        delta_etw_opp = _estimate_opponent_benefit_etw(opponent, sim_game, etw_estimator, offer, weights)
        if delta_etw_opp >= lambda_risk * delta_etw_player:
            continue

        score = etw_after / max(p_accept, EPSILON)
        if score < best_score:
            best_score = score
            best_offer = offer

    return best_offer


def _apply_trade_to_sim(sim_p: SimPlayerState, selling_to_us: ResourceCount, buying_from_us: ResourceCount) -> None:
    sim_p.add_resources(selling_to_us)
    sim_p.remove_resources(buying_from_us)


def _opponent_delta_etw_if_accepts(
    opponent_sim: SimPlayerState,
    sim_game: SimGame,
    etw_estimator,
    selling_to_us: ResourceCount,
    buying_from_us: ResourceCount,
    weights: StrategyWeights,
) -> float:
    etw_before = etw_estimator.estimated_time_to_win(
        opponent_sim,
        sim_game,
        False,
        weights,
        include_player_trades=False,
    )

    sim_opp_after = opponent_sim.copy()
    sim_opp_after.remove_resources(selling_to_us)
    sim_opp_after.add_resources(buying_from_us)

    sim_game_after = _sim_game_with_replaced_player(sim_game, sim_opp_after)
    etw_after = etw_estimator.estimated_time_to_win(
        sim_opp_after,
        sim_game_after,
        False,
        weights,
        include_player_trades=False,
    )

    return max(0.0, etw_before - etw_after)


def _is_close_or_leading(
    opponent: SimPlayerState,
    us: SimPlayerState,
    all_players: List[SimPlayerState],
    sim_game: SimGame,
    etw_estimator,
    weights: StrategyWeights,
) -> bool:
    etw_by_p = {
        p: etw_estimator.estimated_time_to_win(p.copy(), sim_game, False, weights, include_player_trades=False)
        for p in all_players
    }
    leading = min(etw_by_p, key=etw_by_p.get)
    if opponent == leading:
        return True

    vp_gap = opponent.victory_points() - us.victory_points()
    return vp_gap >= -weights.CLOSE_OPPONENT_VP_GAP


def _generate_counter_payments_keep_offer_fixed(
    rolls_per_unit: Dict[Resource, float],
    selling_to_us: ResourceCount,
    buying_from_us: ResourceCount,
) -> List[ResourceCount]:
    counters: List[ResourceCount] = []

    if sum(buying_from_us.values()) == 0:
        return counters

    give_rolls, take_rolls = 0.0, 0.0
    for r, q in buying_from_us.items():
        give_rolls += q * rolls_per_unit.get(r, math.inf)
    for r, q in selling_to_us.items():
        take_rolls += q * rolls_per_unit.get(r, math.inf)

    if give_rolls > 0 and not math.isinf(give_rolls) and not math.isinf(take_rolls):
        overpay_factor = give_rolls / max(take_rolls, EPSILON)
        if overpay_factor > 1.0:
            reduction = min(0.8, max(0.1, 1.0 / overpay_factor))
            scaled = {r: max(0, int(math.floor(q * reduction))) for r, q in buying_from_us.items()}
            if sum(scaled.values()) >= 1:
                counters.append({r: q for r, q in scaled.items() if q > 0})

    for r, q in buying_from_us.items():
        if q <= 0:
            continue
        c = dict(buying_from_us)
        c[r] = q - 1
        c = {rr: qq for rr, qq in c.items() if qq > 0}
        if sum(c.values()) >= 1:
            counters.append(c)

    for r, q in buying_from_us.items():
        if q >= 3:
            c = dict(buying_from_us)
            c[r] = q - 2
            c = {rr: qq for rr, qq in c.items() if qq > 0}
            if sum(c.values()) >= 1:
                counters.append(c)

    uniq: Dict[Tuple[Tuple[int, int], ...], ResourceCount] = {}
    for c in counters:
        key = tuple(sorted((rr.value, qq) for rr, qq in c.items()))
        uniq[key] = c

    return list(uniq.values())


def respond_to_trade_batna(
    player_sim: SimPlayerState,
    opponent_sim: Optional[SimPlayerState],
    sim_game: SimGame,
    etw_estimator,
    selling_to_us: ResourceCount,
    buying_from_us: ResourceCount,
    opponents: List[SimPlayerState],
    weights: StrategyWeights,
) -> Tuple[bool, Optional[ResourceCount]]:
    for r, q in buying_from_us.items():
        if player_sim.resources.get(r, 0) < q:
            return False, None

    etw_before = etw_estimator.estimated_time_to_win(
        player_sim,
        sim_game,
        False,
        weights,
        include_player_trades=False,
    )

    sim_after = player_sim.copy()
    _apply_trade_to_sim(sim_after, selling_to_us, buying_from_us)
    sim_game_after = _sim_game_with_replaced_player(sim_game, sim_after)

    etw_after = etw_estimator.estimated_time_to_win(
        sim_after,
        sim_game_after,
        False,
        weights,
        include_player_trades=False,
    )
    delta_ai = etw_before - etw_after

    if delta_ai <= 0:
        return False, None

    all_players = [player_sim, *opponents]
    etw_by_p = {
        p: etw_estimator.estimated_time_to_win(p.copy(), sim_game, False, weights, include_player_trades=False)
        for p in all_players
    }
    leading = min(etw_by_p, key=etw_by_p.get)

    if opponent_sim is not None:
        lambda_risk = weights.LAMBDA_RISK_LEADER if opponent_sim == leading else weights.LAMBDA_RISK_BASE
        close_or_leading = _is_close_or_leading(opponent_sim, player_sim, all_players, sim_game, etw_estimator, weights)

        delta_opp = _opponent_delta_etw_if_accepts(
            opponent_sim=opponent_sim,
            sim_game=sim_game,
            etw_estimator=etw_estimator,
            selling_to_us=selling_to_us,
            buying_from_us=buying_from_us,
            weights=weights,
        )

        if close_or_leading and delta_opp >= lambda_risk * delta_ai:
            rolls_per_unit = {r: expected_rolls_for_resource(player_sim, r) for r in Resource}
            counters = _generate_counter_payments_keep_offer_fixed(
                rolls_per_unit=rolls_per_unit,
                selling_to_us=selling_to_us,
                buying_from_us=buying_from_us,
            )

            best_counter = None
            best_counter_score = float("inf")

            for counter_payment in counters:
                feasible = all(player_sim.resources.get(r, 0) >= q for r, q in counter_payment.items())
                if not feasible:
                    continue

                sim_after_c = player_sim.copy()
                _apply_trade_to_sim(sim_after_c, selling_to_us, counter_payment)
                sim_game_c = _sim_game_with_replaced_player(sim_game, sim_after_c)

                etw_after_c = etw_estimator.estimated_time_to_win(
                    sim_after_c,
                    sim_game_c,
                    False,
                    weights,
                    include_player_trades=False,
                )
                delta_ai_c = etw_before - etw_after_c
                if delta_ai_c <= 0:
                    continue

                delta_opp_c = _opponent_delta_etw_if_accepts(
                    opponent_sim=opponent_sim,
                    sim_game=sim_game,
                    etw_estimator=etw_estimator,
                    selling_to_us=selling_to_us,
                    buying_from_us=counter_payment,
                    weights=weights,
                )
                if delta_opp_c >= lambda_risk * delta_ai_c:
                    continue

                score = etw_after_c / max(delta_ai_c, EPSILON)
                if score < best_counter_score:
                    best_counter_score = score
                    best_counter = counter_payment

            if best_counter is not None:
                return True, best_counter

            return False, None

    return True, None


def select_best_trade_partner(
    player_sim: SimPlayerState,
    sim_game: SimGame,
    etw_estimator,
    selling_orig: ResourceCount,
    buying: ResourceCount,
    available_players: List[Tuple[SimPlayerState, Optional[ResourceCount]]],
    weights: StrategyWeights,
) -> Optional[Tuple[SimPlayerState, Optional[ResourceCount]]]:
    if not available_players:
        return None

    all_sims = [player_sim] + [opp for opp, _ in available_players]
    etw_by_p = {
        p: etw_estimator.estimated_time_to_win(p.copy(), sim_game, False, weights, include_player_trades=False)
        for p in all_sims
    }
    leading_sim = min(etw_by_p, key=etw_by_p.get)

    batna_etw = etw_estimator.estimated_time_to_win(
        player_sim,
        sim_game,
        False,
        weights,
        include_player_trades=False,
    )

    best: Optional[Tuple[SimPlayerState, Optional[ResourceCount]]] = None
    best_score = float("inf")

    for opp_sim, counter in available_players:
        selling = counter if counter is not None else selling_orig

        if any(player_sim.resources.get(r, 0) < q for r, q in selling.items()):
            continue

        sim_after = player_sim.copy()
        sim_after.remove_resources(selling)
        sim_after.add_resources(buying)
        sim_game_after = _sim_game_with_replaced_player(sim_game, sim_after)

        etw_after = etw_estimator.estimated_time_to_win(
            sim_after,
            sim_game_after,
            False,
            weights,
            include_player_trades=False,
        )
        delta_ai = batna_etw - etw_after
        if delta_ai <= 0:
            continue

        etw_opp_before = etw_estimator.estimated_time_to_win(
            opp_sim,
            sim_game,
            False,
            weights,
            include_player_trades=False,
        )

        sim_opp_after = opp_sim.copy()
        sim_opp_after.add_resources(selling)
        sim_opp_after.remove_resources(buying)
        sim_game_opp_after = _sim_game_with_replaced_player(sim_game, sim_opp_after)

        etw_opp_after = etw_estimator.estimated_time_to_win(
            sim_opp_after,
            sim_game_opp_after,
            False,
            weights,
            include_player_trades=False,
        )
        delta_opp = max(0.0, etw_opp_before - etw_opp_after)

        is_leader = (opp_sim == leading_sim)
        vp_gap = opp_sim.victory_points() - player_sim.victory_points()
        is_close = (vp_gap >= -weights.CLOSE_OPPONENT_VP_GAP)

        lambda_risk = weights.LAMBDA_RISK_LEADER if is_leader else weights.LAMBDA_RISK_BASE
        if (is_close or is_leader) and delta_opp >= lambda_risk * delta_ai:
            continue

        leader_penalty = weights.TRADE_LEADER_PENALTY if is_leader else 0.0
        score = etw_after + leader_penalty

        if score < best_score:
            best_score = score
            best = (opp_sim, counter)

    return best
