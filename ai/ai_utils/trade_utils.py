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
    """Return a SimGame with the given player state replaced in the overlay."""
    ov2 = sim_game.overlay.copy()
    ov2.set_sim_player(sim_player)
    return SimGame(game=sim_game.game, overlay=ov2)


def _generate_candidate_offers(
    R_need: Resource,
    surplus: ResourceCount,
    max_ratio: int = StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO,
) -> List[Action]:
    """Generate plausible trade offers exchanging surplus resources for a needed resource."""
    fair_ratios: List[Tuple[int, int]] = [(k, 1) for k in range(1, max_ratio + 1)]
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
) -> float:
    """Estimate ETW after applying a trade, without crediting additional player trades."""
    selling, buying = trade.payload
    sim_player = player.copy()
    sim_player.remove_resources(selling)
    sim_player.add_resources(buying)

    sim_game_after = _sim_game_with_replaced_player(sim_game, sim_player)

    return etw_estimator.estimated_time_to_win(
        sim_player,
        sim_game_after,
        False,
        include_player_trades=False,
    )


def _estimate_opponent_benefit_etw(
    opponent: SimPlayerState,
    sim_game: SimGame,
    etw_estimator: "EtwEstimator",
    trade: Action,
) -> float:
    """Estimate opponent ETW improvement if they accept the trade."""
    selling_by_them, buying_from_us = trade.payload

    etw_before = etw_estimator.estimated_time_to_win(
        opponent,
        sim_game,
        False,
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
        include_player_trades=False,
    )

    return max(0.0, etw_before - etw_after)


def _predict_acceptance_prob(_: SimPlayerState, delta_etw: float, trade: Action) -> float:
    """Estimate probability that an opponent accepts a proposed trade."""
    _, buying_from_them = trade.payload
    opp_cost = sum(buying_from_them.values())
    history_bias = 0.0

    score = (
        StrategyWeights.ACCEPT_ETW_WEIGHT * delta_etw
        - StrategyWeights.ACCEPT_COST_WEIGHT * opp_cost
        + StrategyWeights.ACCEPT_HISTORY_WEIGHT * history_bias
    )
    return 1.0 / (1.0 + math.exp(-score))


def _apply_trade_copy(player: SimPlayerState, trade: Action) -> SimPlayerState:
    """Return a copy of player state with the trade applied."""
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
) -> float:
    """Return a cheap ETB-based proxy score for an offer, adjusted by acceptance probability."""
    _, buying = trade.payload
    target: ResourceCount = {r: q for r, q in buying.items()}

    etb_before = etw_estimator.estimated_time_to_build(
        player,
        sim_game,
        target,
        include_player_trades=False,
    )

    p2 = _apply_trade_copy(player, trade)

    etb_after = etw_estimator.estimated_time_to_build(
        p2,
        sim_game,
        target,
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
    lambda_leader: float = StrategyWeights.LAMBDA_RISK_LEADER,
    lambda_base: float = StrategyWeights.LAMBDA_RISK_BASE,
) -> Optional[Action]:
    """Return best trade proposal if it beats BATNA and is not too helpful to the opponent."""
    best_offer = None
    best_score = float("inf")

    leading_player = max([player, *opponents], key=lambda p: p.victory_points())
    batna_etw = etw_estimator.estimated_time_to_win(
        player,
        sim_game,
        False,
        include_player_trades=False,
    )

    candidates = _generate_candidate_offers(R_need, surplus)
    if not candidates:
        return None

    cheap_pool: List[Tuple[float, SimPlayerState, Action, float]] = []

    for opponent in opponents:
        for offer in candidates:
            surplus_offering, requesting = offer.payload
            if any(player.resources.get(r, 0) < q for r, q in surplus_offering.items()):
                continue

            if CHECK_INVALID_TRADES_EARLY:
                if any(opponent.resources.get(r, 0) < q for r, q in requesting.items()):
                    continue

            p_accept = _predict_acceptance_prob(opponent, 0.0, offer)
            if p_accept < StrategyWeights.MIN_TRADE_ACCEPT_PROB:
                continue

            cheap_score = _cheap_score_offer(player, sim_game, etw_estimator, offer, p_accept)
            if math.isinf(cheap_score):
                continue

            cheap_pool.append((cheap_score, opponent, offer, p_accept))

    if not cheap_pool:
        return None

    cheap_pool.sort(key=lambda x: x[0])
    shortlisted = cheap_pool[:max(1, TRADE_ETW_SHORTLIST_K)]

    for _, opponent, offer, p_accept in shortlisted:
        lambda_risk = lambda_leader if opponent == leading_player else lambda_base

        etw_after = _evaluate_etw_after_trade(player, sim_game, etw_estimator, offer)
        if etw_after >= batna_etw:
            continue

        delta_etw_player = batna_etw - etw_after
        delta_etw_opp = _estimate_opponent_benefit_etw(opponent, sim_game, etw_estimator, offer)

        if delta_etw_opp >= lambda_risk * delta_etw_player:
            continue

        score = etw_after / max(p_accept, EPSILON)
        if score < best_score:
            best_score = score
            best_offer = offer

    return best_offer


def player_trade_ratio_func(
    resource_give: Resource,
    resource_need: Resource,
    player: SimPlayerState,
    opponents: List[SimPlayerState],
    rolls_per_unit: Dict[Resource, float],
    max_ratio: int = StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO,
    lambda_leader: float = StrategyWeights.LAMBDA_RISK_LEADER,
    lambda_base: float = StrategyWeights.LAMBDA_RISK_BASE,
) -> int:
    """Return give:take ratio for resource_give -> resource_need based on scarcity and risk."""
    give_r = rolls_per_unit.get(resource_give, math.inf)
    need_r = rolls_per_unit.get(resource_need, math.inf)

    if math.isinf(need_r):
        base_ratio = max_ratio
    else:
        if give_r <= 0 or math.isinf(give_r):
            base_ratio = 1
        else:
            base_ratio = int(math.ceil(need_r / give_r))
            base_ratio = max(1, min(max_ratio, base_ratio))

    leading = max([player, *opponents], key=lambda p: p.victory_points())
    if leading is not player and base_ratio < max_ratio:
        bump = 1 if lambda_leader < lambda_base else 0
        base_ratio = min(max_ratio, max(base_ratio, 1 + bump))

    return base_ratio


def _apply_trade_to_sim(sim_p: SimPlayerState, selling_to_us: ResourceCount, buying_from_us: ResourceCount) -> None:
    """Apply the trade from our perspective."""
    sim_p.add_resources(selling_to_us)
    sim_p.remove_resources(buying_from_us)


def _opponent_delta_etw_if_accepts(
    opponent_sim: SimPlayerState,
    sim_game: SimGame,
    etw_estimator,
    selling_to_us: ResourceCount,
    buying_from_us: ResourceCount,
) -> float:
    """Return opponent ETW improvement if they accept a trade."""
    etw_before = etw_estimator.estimated_time_to_win(
        opponent_sim,
        sim_game,
        False,
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
        include_player_trades=False,
    )
    return max(0.0, etw_before - etw_after)


def _is_close_or_leading(opponent: SimPlayerState, us: SimPlayerState, all_players: List[SimPlayerState]) -> bool:
    """Return True if opponent is leading or close by victory points."""
    leading = max(all_players, key=lambda p: p.victory_points())
    if opponent == leading:
        return True
    vp_gap = opponent.victory_points() - us.victory_points()
    return vp_gap >= -StrategyWeights.CLOSE_OPPONENT_VP_GAP


def _generate_counter_payments_keep_offer_fixed(
    rolls_per_unit: Dict[Resource, float],
    selling_to_us: ResourceCount,
    buying_from_us: ResourceCount,
) -> List[ResourceCount]:
    """Return candidate counter-payments from us while keeping their offered selling fixed."""
    counters: List[ResourceCount] = []

    if sum(buying_from_us.values()) == 0:
        return counters

    give_rolls = 0.0
    take_rolls = 0.0

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
    lambda_leader: float = StrategyWeights.LAMBDA_RISK_LEADER,
    lambda_base: float = StrategyWeights.LAMBDA_RISK_BASE,
) -> Tuple[bool, Optional[ResourceCount]]:
    """Return (accept, counter_payment) for an incoming trade offer."""
    for r, q in buying_from_us.items():
        if player_sim.resources.get(r, 0) < q:
            return False, None

    etw_before = etw_estimator.estimated_time_to_win(player_sim, sim_game, False, include_player_trades=False)

    sim_after = player_sim.copy()
    _apply_trade_to_sim(sim_after, selling_to_us, buying_from_us)

    sim_game_after = _sim_game_with_replaced_player(sim_game, sim_after)

    etw_after = etw_estimator.estimated_time_to_win(sim_after, sim_game_after, False, include_player_trades=False)
    delta_ai = etw_before - etw_after

    if delta_ai <= 0:
        return False, None

    all_players = [player_sim, *opponents]
    leading = max(all_players, key=lambda p: p.victory_points())

    if opponent_sim is not None:
        lambda_risk = lambda_leader if opponent_sim == leading else lambda_base
        close_or_leading = _is_close_or_leading(opponent_sim, player_sim, all_players)

        delta_opp = _opponent_delta_etw_if_accepts(
            opponent_sim=opponent_sim,
            sim_game=sim_game,
            etw_estimator=etw_estimator,
            selling_to_us=selling_to_us,
            buying_from_us=buying_from_us,
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
) -> Optional[Tuple[SimPlayerState, Optional[ResourceCount]]]:
    """Return best partner (and optional counter) that yields lowest ETW-after subject to risk constraints."""
    if not available_players:
        return None

    all_sims = [player_sim] + [opp for opp, _ in available_players]
    leading_sim = max(all_sims, key=lambda ps: ps.victory_points())

    batna_etw = etw_estimator.estimated_time_to_win(player_sim, sim_game, False, include_player_trades=False)

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

        etw_after = etw_estimator.estimated_time_to_win(sim_after, sim_game_after, False, include_player_trades=False)
        delta_ai = batna_etw - etw_after
        if delta_ai <= 0:
            continue

        etw_opp_before = etw_estimator.estimated_time_to_win(opp_sim, sim_game, False, include_player_trades=False)

        sim_opp_after = opp_sim.copy()
        sim_opp_after.add_resources(selling)
        sim_opp_after.remove_resources(buying)

        sim_game_opp_after = _sim_game_with_replaced_player(sim_game, sim_opp_after)

        etw_opp_after = etw_estimator.estimated_time_to_win(
            sim_opp_after,
            sim_game_opp_after,
            False,
            include_player_trades=False,
        )
        delta_opp = max(0.0, etw_opp_before - etw_opp_after)

        is_leader = (opp_sim == leading_sim)
        vp_gap = opp_sim.victory_points() - player_sim.victory_points()
        is_close = (vp_gap >= -StrategyWeights.CLOSE_OPPONENT_VP_GAP)

        lambda_risk = StrategyWeights.LAMBDA_RISK_LEADER if is_leader else StrategyWeights.LAMBDA_RISK_BASE
        if (is_close or is_leader) and delta_opp >= lambda_risk * delta_ai:
            continue

        leader_penalty = StrategyWeights.TRADE_LEADER_PENALTY if is_leader else 0.0
        score = etw_after + leader_penalty

        if score < best_score:
            best_score = score
            best = (opp_sim, counter)

    return best
