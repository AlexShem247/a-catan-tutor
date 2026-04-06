import math
from typing import Optional, List, Tuple, Dict, TYPE_CHECKING

from ai.simulation.SimGame import SimGame
from ai.simulation.SimPlayerState import SimPlayerState
from ai.actions import Action, ActionType
from ai.utils.resource_utils import expected_rolls_for_resource
from config.StrategyWeights import StrategyWeights
from config.performance_constants import EPSILON, TRADE_ETW_SHORTLIST_K, CHECK_INVALID_TRADES_EARLY
from game.Resources import Resource, ResourceCount

if TYPE_CHECKING:
    from ai.simulation.EtwEstimator import EtwEstimator


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

    # Generate simple "fair" exchange ratios (e.g. 1:1, 2:1, ..., up to a cap).
    fair_ratios: List[Tuple[int, int]] = [(k, 1) for k in range(1, max_ratio + 1)]
    offers: List[Action] = []

    # Only consider resources we actually have in surplus and that are not the target resource.
    sellables = [(r, q) for r, q in surplus.items() if q > 0 and r != R_need]
    if not sellables:
        return offers

    for give_ratio, take_ratio in fair_ratios:
        # Single-resource offers: give k units of one resource for k units of the needed resource.
        for r_give, max_give in sellables:
            max_k = max_give // give_ratio
            for k in range(1, max_k + 1):
                selling: ResourceCount = {r_give: k * give_ratio}
                buying: ResourceCount = {R_need: k * take_ratio}
                offers.append(Action(ActionType.TRADE_WITH_PLAYER, (selling, buying)))

        # Mixed-resource offers (e.g. 1 wood + 1 brick for 1 wheat),
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

    # Evaluate ETW in the counterfactual game state, with trades disabled.
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

    # Compute opponent ETW before the trade.
    selling_by_them, buying_from_us = trade.payload
    etw_before = etw_estimator.estimated_time_to_win(
        opponent,
        sim_game,
        False,
        include_player_trades=False,
    )

    # Apply the trade to a copied opponent state.
    sim_opp = opponent.copy()
    sim_opp.add_resources(selling_by_them)
    sim_opp.remove_resources(buying_from_us)

    # Measure ETW improvement caused by the trade.
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

    # Cost to opponent measured as total resources they give up.
    _, buying_from_them = trade.payload
    opp_cost = sum(buying_from_them.values())

    # Acceptance increases with opponent ETW gain and decreases with resource cost.
    score = (
            StrategyWeights.ACCEPT_ETW_WEIGHT * delta_etw
            - StrategyWeights.ACCEPT_COST_WEIGHT * opp_cost
    )

    # Squash into [0,1] via logistic function.
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

    # Measure how fast the desired resources can be built before the trade.
    _, buying = trade.payload
    target: ResourceCount = {r: q for r, q in buying.items()}
    etb_before = etw_estimator.estimated_time_to_build(
        player,
        sim_game,
        target,
        include_player_trades=False,
    )

    # Apply trade and re-evaluate ETB.
    p2 = _apply_trade_copy(player, trade)
    etb_after = etw_estimator.estimated_time_to_build(
        p2,
        sim_game,
        target,
        include_player_trades=False,
    )

    # Discard trades that do not improve ETB.
    if etb_after >= etb_before:
        return float("inf")

    # Prefer fast ETB improvements that are also likely to be accepted.
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

    # Identify the current "leader" (lowest ETW) to apply stricter risk constraints.
    all_players = [player, *opponents]
    etw_by_player = {
        p: etw_estimator.estimated_time_to_win(p.copy(), sim_game, False, include_player_trades=False)
        for p in all_players
    }
    leading_player = min(etw_by_player, key=etw_by_player.get)

    # BATNA: what we can achieve by waiting/bank trades (no player trades).
    batna_etw = etw_estimator.estimated_time_to_win(
        player,
        sim_game,
        False,
        include_player_trades=False,
    )

    # Generate a bounded set of plausible offers from our surplus.
    candidates = _generate_candidate_offers(R_need, surplus)
    if not candidates:
        return None

    cheap_pool: List[Tuple[float, SimPlayerState, Action, float]] = []

    for opponent in opponents:
        # Opponent-facing acceptance proxy: what they give vs receive in "roll cost" terms.
        rolls_per_unit = {r: expected_rolls_for_resource(opponent, r) for r in Resource}

        for offer in candidates:
            selling_by_us, buying_from_them = offer.payload

            # Skip offers we can't pay.
            if any(player.resources.get(r, 0) < q for r, q in selling_by_us.items()):
                continue

            # Optional early prune: skip offers they clearly can't pay.
            if CHECK_INVALID_TRADES_EARLY:
                if any(opponent.resources.get(r, 0) < q for r, q in buying_from_them.items()):
                    continue

            # Cheap "benefit" proxy for acceptance: receiving roll-expensive resources is good.
            benefit = (
                    sum(q * rolls_per_unit[r] for r, q in selling_by_us.items())
                    - sum(q * rolls_per_unit[r] for r, q in buying_from_them.items())
            )
            benefit = max(0.0, benefit)

            # Acceptance probability gates which offers are worth deeper evaluation.
            p_accept = _predict_acceptance_prob(opponent, benefit, offer)
            if p_accept < StrategyWeights.MIN_TRADE_ACCEPT_PROB:
                continue

            # Cheap score: does this trade speed up getting what we want (ETB), adjusted by acceptance chance?
            cheap_score = _cheap_score_offer(player, sim_game, etw_estimator, offer, p_accept)
            if math.isinf(cheap_score):
                continue

            cheap_pool.append((cheap_score, opponent, offer, p_accept))

    if not cheap_pool:
        return None

    # Only run expensive ETW checks on the best cheap candidates.
    cheap_pool.sort(key=lambda x: x[0])
    shortlisted = cheap_pool[:max(1, TRADE_ETW_SHORTLIST_K)]

    for _, opponent, offer, p_accept in shortlisted:
        lambda_risk = lambda_leader if opponent == leading_player else lambda_base

        # Trade must improve our ETW versus BATNA.
        etw_after = _evaluate_etw_after_trade(player, sim_game, etw_estimator, offer)
        if etw_after >= batna_etw:
            continue

        # Reject offers that help the opponent too much (especially if they're the leader).
        delta_etw_player = batna_etw - etw_after
        delta_etw_opp = _estimate_opponent_benefit_etw(opponent, sim_game, etw_estimator, offer)
        if delta_etw_opp >= lambda_risk * delta_etw_player:
            continue

        # Final ranking: low ETW-after, high acceptance probability.
        score = etw_after / max(p_accept, EPSILON)
        if score < best_score:
            best_score = score
            best_offer = offer

    return best_offer


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

    # Opponent ETW before the trade.
    etw_before = etw_estimator.estimated_time_to_win(
        opponent_sim,
        sim_game,
        False,
        include_player_trades=False,
    )

    # Apply the trade from the opponent's perspective.
    sim_opp_after = opponent_sim.copy()
    sim_opp_after.remove_resources(selling_to_us)
    sim_opp_after.add_resources(buying_from_us)

    # Opponent ETW after the trade.
    sim_game_after = _sim_game_with_replaced_player(sim_game, sim_opp_after)
    etw_after = etw_estimator.estimated_time_to_win(
        sim_opp_after,
        sim_game_after,
        False,
        include_player_trades=False,
    )

    return max(0.0, etw_before - etw_after)


def _is_close_or_leading(opponent: SimPlayerState, us: SimPlayerState,
                         all_players: List[SimPlayerState], sim_game: SimGame, etw_estimator) -> bool:
    """True if opponent is ETW-leader or close by VP."""

    # Identify the current ETW leader (lowest expected time to win).
    etw_by_p = {
        p: etw_estimator.estimated_time_to_win(p.copy(), sim_game, False, include_player_trades=False)
        for p in all_players
    }
    leading = min(etw_by_p, key=etw_by_p.get)
    if opponent == leading:
        return True

    # Otherwise, treat them as a threat if the VP gap is small.
    vp_gap = opponent.victory_points() - us.victory_points()
    return vp_gap >= -StrategyWeights.CLOSE_OPPONENT_VP_GAP


def _generate_counter_payments_keep_offer_fixed(
    rolls_per_unit: Dict[Resource, float],
    selling_to_us: ResourceCount,
    buying_from_us: ResourceCount,
) -> List[ResourceCount]:
    """Return candidate counter-payments from us while keeping their offered selling fixed."""
    counters: List[ResourceCount] = []

    # Nothing to counter if we were offering nothing.
    if sum(buying_from_us.values()) == 0:
        return counters

    # Compare "roll cost" of what we give vs what we get.
    give_rolls, take_rolls = 0.0, 0.0
    for r, q in buying_from_us.items():
        give_rolls += q * rolls_per_unit.get(r, math.inf)
    for r, q in selling_to_us.items():
        take_rolls += q * rolls_per_unit.get(r, math.inf)

    # If we look like we're overpaying, scale our payment down proportionally.
    if give_rolls > 0 and not math.isinf(give_rolls) and not math.isinf(take_rolls):
        overpay_factor = give_rolls / max(take_rolls, EPSILON)
        if overpay_factor > 1.0:
            reduction = min(0.8, max(0.1, 1.0 / overpay_factor))
            scaled = {r: max(0, int(math.floor(q * reduction))) for r, q in buying_from_us.items()}
            if sum(scaled.values()) >= 1:
                counters.append({r: q for r, q in scaled.items() if q > 0})

    # Also try simple local tweaks: reduce one resource by 1.
    for r, q in buying_from_us.items():
        if q <= 0:
            continue
        c = dict(buying_from_us)
        c[r] = q - 1
        c = {rr: qq for rr, qq in c.items() if qq > 0}
        if sum(c.values()) >= 1:
            counters.append(c)

    # And a slightly bigger concession if we were offering a lot of one resource.
    for r, q in buying_from_us.items():
        if q >= 3:
            c = dict(buying_from_us)
            c[r] = q - 2
            c = {rr: qq for rr, qq in c.items() if qq > 0}
            if sum(c.values()) >= 1:
                counters.append(c)

    # Deduplicate counters (same multiset of resources).
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

    # Reject immediately if we can't actually pay our side.
    for r, q in buying_from_us.items():
        if player_sim.resources.get(r, 0) < q:
            return False, None

    # BATNA baseline: ETW if we refuse and continue normally (no player trades).
    etw_before = etw_estimator.estimated_time_to_win(
        player_sim,
        sim_game,
        False,
        include_player_trades=False,
    )

    # Evaluate our ETW if we accept exactly as offered.
    sim_after = player_sim.copy()
    _apply_trade_to_sim(sim_after, selling_to_us, buying_from_us)
    sim_game_after = _sim_game_with_replaced_player(sim_game, sim_after)

    etw_after = etw_estimator.estimated_time_to_win(
        sim_after,
        sim_game_after,
        False,
        include_player_trades=False,
    )
    delta_ai = etw_before - etw_after

    # Reject if it doesn't beat BATNA.
    if delta_ai <= 0:
        return False, None

    # Identify current ETW leader for tighter "don't help the leader" constraints.
    all_players = [player_sim, *opponents]
    etw_by_p = {
        p: etw_estimator.estimated_time_to_win(p.copy(), sim_game, False, include_player_trades=False)
        for p in all_players
    }
    leading = min(etw_by_p, key=etw_by_p.get)

    if opponent_sim is not None:
        lambda_risk = lambda_leader if opponent_sim == leading else lambda_base
        close_or_leading = _is_close_or_leading(opponent_sim, player_sim, all_players, sim_game, etw_estimator)

        # Estimate how much this trade speeds up the opponent.
        delta_opp = _opponent_delta_etw_if_accepts(
            opponent_sim=opponent_sim,
            sim_game=sim_game,
            etw_estimator=etw_estimator,
            selling_to_us=selling_to_us,
            buying_from_us=buying_from_us,
        )

        # If it helps a threat too much, try a counter-offer that keeps their side fixed.
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
                # Skip counters we can't afford.
                feasible = all(player_sim.resources.get(r, 0) >= q for r, q in counter_payment.items())
                if not feasible:
                    continue

                # Check if the counter still improves our ETW.
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

                # Re-check opponent benefit under the counter.
                delta_opp_c = _opponent_delta_etw_if_accepts(
                    opponent_sim=opponent_sim,
                    sim_game=sim_game,
                    etw_estimator=etw_estimator,
                    selling_to_us=selling_to_us,
                    buying_from_us=counter_payment,
                )
                if delta_opp_c >= lambda_risk * delta_ai_c:
                    continue

                # Prefer counters that keep ETW low while still giving a solid improvement.
                score = etw_after_c / max(delta_ai_c, EPSILON)
                if score < best_counter_score:
                    best_counter_score = score
                    best_counter = counter_payment

            if best_counter is not None:
                return True, best_counter

            return False, None

    # Accept as offered if it beats BATNA and doesn't violate risk constraints.
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

        # Identify the current ETW leader for stricter "don't help them" logic.
    all_sims = [player_sim] + [opp for opp, _ in available_players]
    etw_by_p = {
        p: etw_estimator.estimated_time_to_win(p.copy(), sim_game, False, include_player_trades=False)
        for p in all_sims
    }
    leading_sim = min(etw_by_p, key=etw_by_p.get)

    # BATNA baseline: best we can do without a player trade.
    batna_etw = etw_estimator.estimated_time_to_win(
        player_sim,
        sim_game,
        False,
        include_player_trades=False,
    )

    best: Optional[Tuple[SimPlayerState, Optional[ResourceCount]]] = None
    best_score = float("inf")

    for opp_sim, counter in available_players:
        # Use counter-payment if offered, otherwise our original offer.
        selling = counter if counter is not None else selling_orig

        # Skip partners if we can't afford this payment.
        if any(player_sim.resources.get(r, 0) < q for r, q in selling.items()):
            continue

        # Evaluate our ETW after making this trade.
        sim_after = player_sim.copy()
        sim_after.remove_resources(selling)
        sim_after.add_resources(buying)
        sim_game_after = _sim_game_with_replaced_player(sim_game, sim_after)

        etw_after = etw_estimator.estimated_time_to_win(
            sim_after,
            sim_game_after,
            False,
            include_player_trades=False,
        )
        delta_ai = batna_etw - etw_after
        if delta_ai <= 0:
            continue

        # Estimate how much the opponent benefits from the same trade.
        etw_opp_before = etw_estimator.estimated_time_to_win(
            opp_sim,
            sim_game,
            False,
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
            include_player_trades=False,
        )
        delta_opp = max(0.0, etw_opp_before - etw_opp_after)

        # Apply risk constraint more strongly for leaders / close rivals.
        is_leader = (opp_sim == leading_sim)
        vp_gap = opp_sim.victory_points() - player_sim.victory_points()
        is_close = (vp_gap >= -StrategyWeights.CLOSE_OPPONENT_VP_GAP)

        lambda_risk = StrategyWeights.LAMBDA_RISK_LEADER if is_leader else StrategyWeights.LAMBDA_RISK_BASE
        if (is_close or is_leader) and delta_opp >= lambda_risk * delta_ai:
            continue

        # Optional extra bias against trading with the leader even if it's "safe".
        leader_penalty = StrategyWeights.TRADE_LEADER_PENALTY if is_leader else 0.0
        score = etw_after + leader_penalty

        if score < best_score:
            best_score = score
            best = (opp_sim, counter)

    return best
