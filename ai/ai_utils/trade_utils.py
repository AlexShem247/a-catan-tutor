import math
from typing import Optional, List, Tuple, Dict, TYPE_CHECKING

from ai.ai_utils.SimPlayerState import SimPlayerState, SimGame
from ai.ai_utils.actions import Action, ActionType
from ai.ai_utils.resource_utils import expected_rolls_for_resource
from config.StrategyWeights import StrategyWeights
from config.performance_constants import EPSILON
from game.Resources import Resource, ResourceCount

if TYPE_CHECKING:
    from ai.ai_utils.EtwEstimator import EtwEstimator


def _generate_candidate_offers(R_need: Resource, surplus: ResourceCount,
                               max_ratio=StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO) -> List[Action]:
    """Generate plausible trade offers exchanging surplus resources for a needed resource."""
    fair_ratios: List[Tuple[int, int]] = [(k, 1) for k in range(1, max_ratio + 1)]

    offers: List[Action] = []

    # Resources the agent can credibly offer without harming its plan
    sellables = [(r, q) for r, q in surplus.items() if q > 0 and r != R_need]
    if not sellables:
        return offers

    for give_ratio, take_ratio in fair_ratios:

        # Single-resource offers (e.g. 2 WOOD → 1 BRICK)
        for r_give, max_give in sellables:
            max_k = max_give // give_ratio
            for k in range(1, max_k + 1):
                selling: ResourceCount = {r_give: k * give_ratio}
                buying: ResourceCount = {R_need: k * take_ratio}
                offers.append(Action(ActionType.TRADE_WITH_PLAYER, (selling, buying)))

        # Mixed-resource bundles capture flexible trades such as
        # "any two cards for one", which are common in practice
        if give_ratio > 1:
            for i in range(len(sellables)):
                r1, q1 = sellables[i]
                for x in range(1, min(q1, give_ratio - 1) + 1):
                    y = give_ratio - x
                    for j in range(i + 1, len(sellables)):
                        r2, q2 = sellables[j]
                        if q2 < y:
                            continue
                        selling: ResourceCount = {r1: x, r2: y}
                        buying: ResourceCount = {R_need: take_ratio}
                        offers.append(Action(ActionType.TRADE_WITH_PLAYER, (selling, buying)))

    return offers


def _evaluate_etw_after_trade(player: SimPlayerState, sim_game: SimGame, etw_estimator: "EtwEstimator",
                              trade: Action) -> float:
    """Estimate ETW after applying a specific trade, without crediting additional player trades."""
    selling, buying = trade.payload
    sim_player = player.copy()

    # Simulate trade
    sim_player.remove_resources(selling)
    sim_player.add_resources(buying)

    return etw_estimator.estimated_time_to_win(sim_player, SimGame(sim_player, sim_game.game), False,
                                               include_player_trades=False)


def _estimate_opponent_benefit_etw(opponent: SimPlayerState, sim_game: SimGame, etw_estimator: "EtwEstimator",
                                   trade: Action) -> float:
    """Estimate opponent ETW improvement if they accept the trade (no further player trades credited)."""
    selling_by_them, buying_from_us = trade.payload

    etw_before = etw_estimator.estimated_time_to_win(opponent, sim_game, False, include_player_trades=False, )
    sim_opp = opponent.copy()

    # Simulate acceptance from opponent's perspective: they receive what we are selling and give what we are buying
    sim_opp.add_resources(selling_by_them)
    sim_opp.remove_resources(buying_from_us)

    etw_after = etw_estimator.estimated_time_to_win(sim_opp, sim_game, False, include_player_trades=False)

    return max(0.0, etw_before - etw_after)


def _predict_acceptance_prob(_: SimPlayerState, delta_etw: float, trade: Action) -> float:
    """Estimate probability that an opponent accepts a proposed trade."""
    selling_by_us, buying_from_them = trade.payload

    # 1. Cost proxy: total cards opponent gives up
    opp_cost = sum(buying_from_them.values())

    # 2. Historical receptiveness (default neutral = 0)
    history_bias = 0.0

    # Linear score
    score = (
            StrategyWeights.ACCEPT_ETW_WEIGHT * delta_etw
            - StrategyWeights.ACCEPT_COST_WEIGHT * opp_cost
            + StrategyWeights.ACCEPT_HISTORY_WEIGHT * history_bias
    )

    # Logistic squash to [0, 1]
    return 1.0 / (1.0 + math.exp(-score))


def propose_trade(player: SimPlayerState, sim_game: SimGame, R_need: Resource, surplus: ResourceCount,
                  opponents: List[SimPlayerState], etw_estimator: "EtwEstimator",
                  lambda_leader: float = StrategyWeights.LAMBDA_RISK_LEADER,
                  lambda_base: float = StrategyWeights.LAMBDA_RISK_BASE) -> Optional[Action]:
    """BATNA-based trade module. Returns best trade if exists"""
    best_offer = None
    best_score = float("inf")  # We minimise expected net ETW (or ETW reduction is maximised)
    leading_player = max([player, *opponents], key=lambda p: p.victory_points())
    batna_etw = etw_estimator.estimated_time_to_win(player, sim_game, False, include_player_trades=False)

    # Generate candidate offers to j from surplus S towards R_need
    candidates = _generate_candidate_offers(R_need, surplus)

    for opponent in opponents:
        lambda_risk = lambda_leader if opponent == leading_player else lambda_base

        for offer in candidates:
            surplus_offering, R_requesting = offer.payload
            assert all(player.resources.get(r, 0) >= q for r, q in surplus_offering.items())

            # Opponent must have the cards we request
            if any(opponent.resources.get(r, 0) < q for r, q in R_requesting.items()):
                continue

            # Must beat BATNA for player
            etw_after = _evaluate_etw_after_trade(player, sim_game, etw_estimator, offer)
            if etw_after >= batna_etw:
                continue  # Reject: not better than BATNA

            # Estimate opponent impact - avoid helping too much
            delta_etw_player = batna_etw - etw_after
            delta_etw_opp = _estimate_opponent_benefit_etw(opponent, sim_game, etw_estimator, offer)

            # Reject if opponent benefits "too much" relative to agent
            if delta_etw_opp >= lambda_risk * delta_etw_player:
                continue

            # Likely acceptable? (opponent model from history + observed resources)
            p_accept = _predict_acceptance_prob(opponent, delta_etw_opp, offer)
            if p_accept < StrategyWeights.MIN_TRADE_ACCEPT_PROB:
                continue

            # Score: best net ETW reduction, adjusted by accept likelihood
            # Lower score is better
            score = etw_after / max(p_accept, EPSILON)

            if score < best_score:
                best_score = score
                best_offer = offer

    return best_offer


def player_trade_ratio_func(resource_give: Resource, resource_need: Resource, player: SimPlayerState,
                            opponents: List[SimPlayerState], production_rates: Dict[Resource, float],
                            max_ratio: int = StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO,
                            lambda_leader: float = StrategyWeights.LAMBDA_RISK_LEADER,
                            lambda_base: float = StrategyWeights.LAMBDA_RISK_BASE,
                            ) -> int:
    """Return an offered give:take ratio for resource_give -> resource_need based on scarcity and risk."""
    # production_rates[r] is "expected rolls per 1 unit" in your codebase (higher => slower/rarer)
    give_r = production_rates.get(resource_give, math.inf)
    need_r = production_rates.get(resource_need, math.inf)

    # If the needed resource is not producible (infinite rolls), we treat it as maximally scarce
    if math.isinf(need_r):
        base_ratio = max_ratio
    else:
        # If what we're giving is not producible, we should never "overpay" with it;
        # fall back to the most favourable ratio (1:1).
        if give_r <= 0 or math.isinf(give_r):
            base_ratio = 1
        else:
            base_ratio = int(math.ceil(need_r / give_r))
            base_ratio = max(1, min(max_ratio, base_ratio))

    # Be less generous when dealing with the leading opponent (raise ratio)
    leading = max([player, *opponents], key=lambda p: p.victory_points())
    if leading is not player and base_ratio < max_ratio:
        bump = 1 if lambda_leader < lambda_base else 0
        base_ratio = min(max_ratio, max(base_ratio, 1 + bump))

    return base_ratio


def _apply_trade_to_sim(sim_p: SimPlayerState, selling_to_us: ResourceCount, buying_from_us: ResourceCount) -> None:
    """Apply the trade from OUR perspective: we receive `selling_to_us` and pay `buying_from_us`."""
    sim_p.add_resources(selling_to_us)
    sim_p.remove_resources(buying_from_us)


def _opponent_delta_etw_if_accepts(opponent_sim: SimPlayerState, sim_game: SimGame, etw_estimator,
                                   selling_to_us: ResourceCount, buying_from_us: ResourceCount) -> float:
    """Opponent perspective if they accept: ΔETW = ETW_before - ETW_after (positive means they improved)"""
    etw_before = etw_estimator.estimated_time_to_win(opponent_sim, sim_game, False, include_player_trades=False)

    sim_opp_after = opponent_sim.copy()
    sim_opp_after.remove_resources(selling_to_us)
    sim_opp_after.add_resources(buying_from_us)

    etw_after = etw_estimator.estimated_time_to_win(sim_opp_after, sim_game, False, include_player_trades=False)
    return max(0.0, etw_before - etw_after)


def _is_close_or_leading(opponent: SimPlayerState, us: SimPlayerState, all_players: List[SimPlayerState]) -> bool:
    """Close opponent heuristic."""
    leading = max(all_players, key=lambda p: p.victory_points())
    if opponent == leading:
        return True

    vp_gap = opponent.victory_points() - us.victory_points()
    return vp_gap >= -StrategyWeights.CLOSE_OPPONENT_VP_GAP  # e.g. allow small negative gap; tune weight


def _generate_counter_payments_keep_offer_fixed(production_rates: Dict[Resource, float], selling_to_us: ResourceCount,
                                                buying_from_us: ResourceCount) -> List[ResourceCount]:
    """Produce counter payments from us while keeping their offered selling_to_us fixed."""
    counters: List[ResourceCount] = []

    # No payment requested → nothing to counter
    if sum(buying_from_us.values()) == 0:
        return counters

    # Estimate scarcity-weighted value of what we give vs receive
    give_rolls = 0.0
    take_rolls = 0.0

    for r, q in buying_from_us.items():
        give_rolls += q * production_rates.get(r, math.inf)
    for r, q in selling_to_us.items():
        take_rolls += q * production_rates.get(r, math.inf)

    # If defined and we appear to overpay, scale payment down
    if give_rolls > 0 and not math.isinf(give_rolls) and not math.isinf(take_rolls):
        overpay_factor = give_rolls / max(take_rolls, EPSILON)
        if overpay_factor > 1.0:
            reduction = min(0.8, max(0.1, 1.0 / overpay_factor))
            scaled = {
                r: max(0, int(math.floor(q * reduction)))
                for r, q in buying_from_us.items()
            }
            if sum(scaled.values()) >= 1:
                counters.append({r: q for r, q in scaled.items() if q > 0})

    # Local adjustments: reduce one requested resource by 1
    for r, q in buying_from_us.items():
        if q <= 0:
            continue
        c = dict(buying_from_us)
        c[r] = q - 1
        c = {rr: qq for rr, qq in c.items() if qq > 0}
        if sum(c.values()) >= 1:
            counters.append(c)

    # More aggressive local reduction: reduce by 2 where possible
    for r, q in buying_from_us.items():
        if q >= 3:
            c = dict(buying_from_us)
            c[r] = q - 2
            c = {rr: qq for rr, qq in c.items() if qq > 0}
            if sum(c.values()) >= 1:
                counters.append(c)

    # Remove duplicates
    uniq = {}
    for c in counters:
        key = tuple(sorted((rr.value, qq) for rr, qq in c.items()))
        uniq[key] = c

    return list(uniq.values())


def respond_to_trade_batna(player_sim: SimPlayerState, opponent_sim: Optional[SimPlayerState], sim_game: SimGame,
                           etw_estimator, selling_to_us: ResourceCount, buying_from_us: ResourceCount,
                           opponents: List[SimPlayerState],
                           lambda_leader: float = StrategyWeights.LAMBDA_RISK_LEADER,
                           lambda_base: float = StrategyWeights.LAMBDA_RISK_BASE,
                           ) -> Tuple[bool, Optional[ResourceCount]]:
    """Responding to Trade Offers"""

    # 0) Feasibility: we must be able to pay what they request
    for r, q in buying_from_us.items():
        if player_sim.resources.get(r, 0) < q:
            return False, None

    # 1) Compute ΔETW_AI if accepted
    etw_before = etw_estimator.estimated_time_to_win(player_sim, sim_game, False, include_player_trades=False)

    sim_after = player_sim.copy()
    _apply_trade_to_sim(sim_after, selling_to_us, buying_from_us)

    etw_after = etw_estimator.estimated_time_to_win(sim_after, sim_game, False, include_player_trades=False)
    delta_ai = etw_before - etw_after  # positive is good

    # 2) If ΔETW_AI ≤ 0 reject
    if delta_ai <= 0:
        return False, None

    # 3) Estimate ΔETW_opponent; if it helps a close/leading opponent too much, reject or counter
    all_players = [player_sim, *opponents]
    leading = max(all_players, key=lambda p: p.victory_points())

    if opponent_sim is not None:
        # Determine risk aversion weight based on whether they are leading / close
        lambda_risk = lambda_leader if opponent_sim == leading else lambda_base
        close_or_leading = _is_close_or_leading(opponent_sim, player_sim, all_players)

        delta_opp = _opponent_delta_etw_if_accepts(
            opponent_sim=opponent_sim,
            sim_game=sim_game,
            etw_estimator=etw_estimator,
            selling_to_us=selling_to_us,
            buying_from_us=buying_from_us
        )

        # “Too helpful” condition (your Eq 2.14 style)
        if close_or_leading and delta_opp >= lambda_risk * delta_ai:
            # Try counter-offers that keep overlap but improve our side.
            production_rates = {r: expected_rolls_for_resource(player_sim, r) for r in Resource}

            counters = _generate_counter_payments_keep_offer_fixed(
                production_rates=production_rates,
                selling_to_us=selling_to_us,
                buying_from_us=buying_from_us
            )

            best_counter = None
            best_counter_score = float("inf")

            for counter_payment in counters:
                # Must still be feasible for us
                feasible = all(player_sim.resources.get(r, 0) >= q for r, q in counter_payment.items())
                if not feasible:
                    continue

                # Recompute ETW for us under counter
                sim_after_c = player_sim.copy()
                _apply_trade_to_sim(sim_after_c, selling_to_us, counter_payment)
                etw_after_c = etw_estimator.estimated_time_to_win(sim_after_c, sim_game, False,
                                                                  include_player_trades=False)
                delta_ai_c = etw_before - etw_after_c
                if delta_ai_c <= 0:
                    continue  # don’t counter into a bad deal

                # Recheck opponent benefit
                delta_opp_c = _opponent_delta_etw_if_accepts(
                    opponent_sim=opponent_sim,
                    sim_game=sim_game,
                    etw_estimator=etw_estimator,
                    selling_to_us=selling_to_us,
                    buying_from_us=counter_payment
                )

                if delta_opp_c >= lambda_risk * delta_ai_c:
                    continue  # still too generous

                # Score counters: minimise our ETW after (more benefit) while staying less helpful
                score = etw_after_c / max(delta_ai_c, EPSILON)
                if score < best_counter_score:
                    best_counter_score = score
                    best_counter = counter_payment

            if best_counter is not None:
                return True, best_counter

            # No safe counter found -> reject
            return False, None

    # 4) Beneficial and not too helpful -> accept
    return True, None


def select_best_trade_partner(
    player_sim: SimPlayerState,
    sim_game: SimGame,
    etw_estimator,
    selling_orig: ResourceCount,
    buying: ResourceCount,
    available_players: List[Tuple[SimPlayerState, Optional[ResourceCount]]],
) -> Optional[Tuple[SimPlayerState, Optional[ResourceCount]]]:
    """Pick the partner (and optional counter) that yields the lowest ETW-after, subject to risk constraints."""
    if not available_players:
        return None

    # Identify current leader (by VP)
    all_sims = [player_sim] + [opp for opp, _ in available_players]
    leading_sim = max(all_sims, key=lambda ps: ps.victory_points())

    batna_etw = etw_estimator.estimated_time_to_win(
        player_sim, sim_game, False, include_player_trades=False
    )

    best: Optional[Tuple[SimPlayerState, Optional[ResourceCount]]] = None
    best_score = float("inf")

    for opp_sim, counter in available_players:
        selling = counter if counter is not None else selling_orig

        # Must be able to pay what we'd give
        if any(player_sim.resources.get(r, 0) < q for r, q in selling.items()):
            continue

        # 1–2) Only accept if it improves our ETW vs BATNA
        sim_after = player_sim.copy()
        sim_after.remove_resources(selling)  # we pay
        sim_after.add_resources(buying)      # we receive

        etw_after = etw_estimator.estimated_time_to_win(
            sim_after, sim_game, False, include_player_trades=False
        )
        delta_ai = batna_etw - etw_after
        if delta_ai <= 0:
            continue

        # 3) Reject if it helps a close/leading opponent too much
        etw_opp_before = etw_estimator.estimated_time_to_win(
            opp_sim, sim_game, False, include_player_trades=False
        )
        sim_opp_after = opp_sim.copy()
        sim_opp_after.add_resources(selling)   # they receive what we pay
        sim_opp_after.remove_resources(buying) # they pay what we receive

        etw_opp_after = etw_estimator.estimated_time_to_win(
            sim_opp_after, sim_game, False, include_player_trades=False
        )
        delta_opp = max(0.0, etw_opp_before - etw_opp_after)

        is_leader = (opp_sim == leading_sim)
        vp_gap = opp_sim.victory_points() - player_sim.victory_points()
        is_close = (vp_gap >= -StrategyWeights.CLOSE_OPPONENT_VP_GAP)

        lambda_risk = StrategyWeights.LAMBDA_RISK_LEADER if is_leader else StrategyWeights.LAMBDA_RISK_BASE
        if (is_close or is_leader) and delta_opp >= lambda_risk * delta_ai:
            continue

        # 4) Choose best remaining option
        leader_penalty = StrategyWeights.TRADE_LEADER_PENALTY if is_leader else 0.0
        score = etw_after + leader_penalty

        if score < best_score:
            best_score = score
            best = (opp_sim, counter)

    return best
