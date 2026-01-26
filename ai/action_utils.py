from typing import List, Tuple, Optional, TYPE_CHECKING

from ai.SimPlayerState import SimPlayerState, dice_probability, SimGame
from ai.actions import ActionType, Action
from ai.board_sim_utils import legal_settlement_vertex, get_opponents
from ai.resource_utils import calc_step_resources, get_bank_trade_ratio
from config.StrategyWeights import StrategyWeights
from config.performance_constants import MAX_EXTRA_ROADS_FOR_SETTLEMENT, MAX_POTENTIAL_VERTICES, \
    DEV_CARD_ETB_THRESHOLD, EPSILON
from game.Game import Game
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount

if TYPE_CHECKING:
    from ai.EtwEstimator import EtwEstimator


def distant_settlement_candidates(player: SimPlayerState, sim_game: SimGame, etw_estimator: "EtwEstimator") \
        -> List[Tuple[List[Action], float, float]]:
    """Return settlement placement candidates reachable via player's roads with ETB evaluation."""
    if len(player.settlements) >= Buildable.SETTLEMENT.max_on_board:
        return []

    max_extra_roads = min(Buildable.ROAD.max_on_board - len(player.roads), MAX_EXTRA_ROADS_FOR_SETTLEMENT)
    candidate_actions = []

    # Fast lookup structures
    player_roads_set = set(player.roads)
    player_settlement_vertices = {s for s in player.settlements}
    player_city_vertices = {c for c in player.cities}
    all_player_vertices = player_settlement_vertices | player_city_vertices

    # Collect all vertices connected to player's road network
    network_vertices = set()
    for road in player.roads:
        network_vertices.update(road.vertices)

    # Pre-filter: only consider vertices that aren't occupied
    all_vertices = set()
    for v in network_vertices:
        all_vertices.update([v])
        for edge in v.edges:
            if edge not in player_roads_set and edge.owner is None and edge not in sim_game.player_state.roads:
                all_vertices.add(edge.get_other_vertex(v))

    # Phase 1: Check immediate network vertices (0 roads)
    for vertex in network_vertices:
        if vertex in all_player_vertices:
            continue

        if legal_settlement_vertex(player, vertex):
            actions = [Action(ActionType.BUILD, (Buildable.SETTLEMENT, vertex))]
            etb = etw_estimator.calc_etb_actions(player, actions)
            candidate_actions.append((actions, etb, 1))

    if max_extra_roads == 0:
        return candidate_actions

    # Phase 2: Check vertices reachable with 1 road (limited to top N by heuristic)
    potential_vertices = []
    for vertex in all_vertices - network_vertices - all_player_vertices:
        if not legal_settlement_vertex(sim_game.player_state, vertex):
            continue

        # Simple heuristic: number of adjacent hexes with good production
        score = 0
        for h in vertex.hexes:
            if h.resource:
                score += dice_probability(h.production_number)
        potential_vertices.append((vertex, score))

    # Sort by heuristic and take top N
    potential_vertices.sort(key=lambda x: x[1], reverse=True)
    potential_vertices = potential_vertices[:MAX_POTENTIAL_VERTICES]

    for vertex, _ in potential_vertices:
        # Find the closest road connection
        for start_vertex in network_vertices:
            for edge in start_vertex.edges:
                if edge.get_other_vertex(start_vertex) == vertex:
                    if edge.owner is None and edge not in player_roads_set and edge not in sim_game.player_state.roads:
                        # This is a direct connection
                        actions = [
                            Action(ActionType.BUILD, (Buildable.ROAD, edge)),
                            Action(ActionType.BUILD, (Buildable.SETTLEMENT, vertex))
                        ]
                        etb = etw_estimator.calc_etb_actions(player, actions)
                        candidate_actions.append((actions, etb, 1))
                        break
            else:
                continue
            break

    return candidate_actions


def play_development_card_action(player: SimPlayerState, game: Game) -> \
        List[Tuple[List[Action], float, float]]:
    """Return playable development card actions and expected VP gains."""
    actions: List[Tuple[List[Action], float, float]] = []
    etb = 0.0
    for card_type, qty in player.dev_cards.items():
        if qty <= 0 or card_type == DevelopmentCardType.VICTORY_POINT:
            continue
        for _ in range(qty):
            action = Action(ActionType.PLAY_DEV_CARD, payload=card_type)
            # ETB = 0 because card is already in hand
            if card_type == DevelopmentCardType.KNIGHT:
                expected_vp = expected_vp_from_knight(player, game)
            else:
                expected_vp = 0.0
            actions.append(([action], etb, expected_vp))

    return actions


def purchase_development_card_action(player: SimPlayerState, game: Game, etw_estimator: "EtwEstimator") -> \
        List[Tuple[List[Action], float, float]]:
    """Return candidate actions for buying development cards with ETB and expected VP consideration."""
    deck = game.development_deck
    if deck.empty():
        return []

    deck_actions: List[Tuple[List[Action], float, float]] = []
    card_purchase_etb = etw_estimator.estimated_time_to_build(player, Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD])

    if card_purchase_etb > DEV_CARD_ETB_THRESHOLD:
        return deck_actions

    actions = [Action(ActionType.BUY_DEV_CARD)]

    # Chance of getting VP card
    vp_prob = deck.get_probability(DevelopmentCardType.VICTORY_POINT, player.dev_cards)
    if vp_prob > 0:
        deck_actions.append((actions, card_purchase_etb, vp_prob))

    # Chance of drawing a Knight card (only if we need knights)
    if player.army_size < StrategyWeights.MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE:
        knight_prob = deck.get_probability(DevelopmentCardType.KNIGHT, player.dev_cards)
        vp_gain_knight = expected_vp_from_knight(player, game)
        if knight_prob * vp_gain_knight > StrategyWeights.MIN_EXPECTED_VP_FOR_KNIGHT:
            deck_actions.append(
                (actions + [Action(ActionType.END_TURN), Action(ActionType.PLAY_DEV_CARD, DevelopmentCardType.KNIGHT)],
                 card_purchase_etb + 1, knight_prob * vp_gain_knight))

    return deck_actions


def choose_max_utility_action(player: SimPlayerState, utilities: List[Tuple[Action, float]],
                              ignore_affordability: bool = False) -> Action:
    """Select the action with maximum utility, considering affordability and bank trades."""
    best_action = None
    best_utility = float("-inf")

    for action, utility in utilities:
        # Check if player can afford this action directly
        cost = calc_step_resources(action)

        if player.can_afford(cost) or ignore_affordability:
            # Directly affordable
            if utility > best_utility:
                best_utility = utility
                best_action = action
        else:
            # Check if we can afford it with bank trades
            bank_trade_action = _get_bank_trade_for_action(player, cost)
            if bank_trade_action:
                # The action + bank trade is affordable
                if utility > best_utility:
                    best_utility = utility
                    best_action = bank_trade_action

    if best_action:
        return best_action

    # No affordable actions even with bank trades
    return Action(ActionType.END_TURN)


def _get_bank_trade_for_action(player: SimPlayerState, cost: ResourceCount) -> Optional[Action]:
    """Return a single bank trade action to make an unaffordable action feasible, or None."""

    # Find first resource we're short on
    for needed_resource, needed_amount in cost.items():
        have = player.resources.get(needed_resource, 0)
        if have < needed_amount:
            # Try to find a resource to sell
            for sell_resource in Resource:
                if sell_resource == needed_resource:
                    continue

                have_sell = player.resources.get(sell_resource, 0)
                if have_sell <= 0:
                    continue

                # Get trade ratio for the SELL resource
                trade_ratio = get_bank_trade_ratio(player.settlements + player.cities, sell_resource)

                # Can we get at least 1 of the needed resource?
                if have_sell >= trade_ratio:
                    # Create a trade for exactly 1 of the needed resource
                    return Action(
                        ActionType.TRADE_WITH_BANK,
                        payload=(
                            {sell_resource: trade_ratio},
                            {needed_resource: 1}
                        )
                    )

    return None


def compute_k_lr(player: SimPlayerState, game: Game) -> float:
    """Calculate Longest Road scaling factor for utility computations."""
    vp = player.victory_points()
    f_phase = min(vp / 10.0, 1.0)
    my_len = player.longest_road_length
    opponent_best = max([p.longest_road_length for p in get_opponents(player, game)], default=0)

    # Target length needed to claim / retain Longest Road
    longest_road = max(my_len, opponent_best)
    target = max(StrategyWeights.LR_MIN_ROAD_LENGTH, longest_road + 1)
    dist = max(0, target - my_len)
    f_dist = 1.0 / (1.0 + dist)
    gap = my_len - opponent_best
    f_contest = 1.0 / (1.0 + max(gap, 0) + EPSILON)

    k = (StrategyWeights.LR_BASE + StrategyWeights.LR_PHASE * f_phase + StrategyWeights.LR_DISTANCE * f_dist +
         StrategyWeights.LR_CONTEST * f_contest)
    return max(k, 0.0)


def compute_k_la(player: SimPlayerState, game: Game) -> float:
    """Calculate Largest Army scaling factor for utility computations."""
    vp = player.victory_points()
    f_phase = min(vp / 10.0, 1.0)

    my_knights = player.army_size
    opponent_best = max([p.army_size for p in get_opponents(player, game)], default=0)

    # Target number of knights needed to claim / retain Largest Army
    largest_army = max(my_knights, opponent_best)
    target = max(StrategyWeights.LA_MIN_KNIGHTS, largest_army + 1)
    dist = max(0, target - my_knights)
    f_dist = 1.0 / (1.0 + dist)

    gap = my_knights - opponent_best
    f_contest = 1.0 / (1.0 + max(gap, 0) + EPSILON)

    k = (StrategyWeights.LA_BASE + StrategyWeights.LA_PHASE * f_phase + StrategyWeights.LA_KNIGHT_DIST * f_dist +
         StrategyWeights.LA_CONTEST * f_contest)
    return max(k, 0.0)


def expected_vp_from_knight(player: SimPlayerState, game: Game) -> float:
    """Estimate expected victory points from playing a Knight card based on army comparison."""
    my_knights = player.army_size
    opponents = get_opponents(player, game)
    opponent_best = max([p.army_size for p in opponents], default=0)

    # If we're at least N knights behind, knight has lower value
    if my_knights + StrategyWeights.KNIGHT_DEFICIT_THRESHOLD < opponent_best:
        return StrategyWeights.LOW_KNIGHT_VALUE  # Small chance to catch up

    # If playing a Knight gives Largest Army
    target = max(3, opponent_best + 1)  # 3 is game rule for minimum knights
    if my_knights + 1 >= target and not player.has_largest_army:
        return StrategyWeights.HIGH_KNIGHT_VALUE  # Definitely get the largest army

    # If we're maintaining the largest army
    if player.has_largest_army and my_knights + 1 > opponent_best:
        return StrategyWeights.MEDIUM_KNIGHT_VALUE  # Maintain advantage

    return 0.0
