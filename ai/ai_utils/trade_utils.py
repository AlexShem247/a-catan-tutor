import math
from typing import Optional, List, Tuple, Dict, TYPE_CHECKING

from ai.ai_utils.SimPlayerState import SimPlayerState, SimGame
from ai.ai_utils.actions import Action, ActionType
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


def _predict_acceptance_prob(opponent: SimPlayerState, delta_etw: float, trade: Action) -> float:
    """Estimate probability that an opponent accepts a proposed trade."""
    selling_by_us, buying_from_them = trade.payload

    # 1. Hard feasibility: opponent must be able to pay
    for r, q in buying_from_them.items():
        if opponent.resources.get(r, 0) < q:
            return 0.0

    # 2. Cost proxy: total cards opponent gives up
    opp_cost = sum(buying_from_them.values())

    # 3. Historical receptiveness (default neutral = 0)
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

    for opponent in opponents:
        lambda_risk = lambda_leader if opponent == leading_player else lambda_base
        # Generate candidate offers to j from surplus S towards R_need
        candidates = _generate_candidate_offers(R_need, surplus)

        for offer in candidates:
            surplus_offering, R_requesting = offer.payload
            assert all(player.resources.get(r, 0) >= q for r, q in surplus_offering.items())

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
