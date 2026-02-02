from typing import List, Tuple, Optional, TYPE_CHECKING

from ai.ai_utils.SimGame import SimGame
from ai.ai_utils.SimPlayerState import SimPlayerState, dice_probability
from ai.ai_utils.actions import ActionType, Action
from ai.ai_utils.board_sim_utils import legal_settlement_vertex, get_opponents
from ai.ai_utils.resource_utils import get_bank_trade_ratio
from config.StrategyWeights import StrategyWeights
from config.performance_constants import (
    MAX_EXTRA_ROADS_FOR_SETTLEMENT,
    MAX_POTENTIAL_VERTICES,
    DEV_CARD_ETB_THRESHOLD,
    EPSILON,
)
from game.Game import Game
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex

if TYPE_CHECKING:
    from ai.ai_utils.EtwEstimator import EtwEstimator


def distant_settlement_candidates(player: SimPlayerState, sim_game: SimGame, etw_estimator: "EtwEstimator") \
        -> List[Tuple[List[Action], float, float]]:
    """Return settlement placement candidates reachable via player's roads with ETB evaluation."""
    if len(player.settlements) >= Buildable.SETTLEMENT.max_on_board:
        return []

    ov = sim_game.overlay
    max_extra_roads = min(Buildable.ROAD.max_on_board - len(player.roads), MAX_EXTRA_ROADS_FOR_SETTLEMENT)
    candidate_actions: List[Tuple[List[Action], float, float]] = []

    player_roads_set = set(player.roads)
    player_settlement_vertices = set(player.settlements)
    player_city_vertices = set(player.cities)
    all_player_vertices = player_settlement_vertices | player_city_vertices

    network_vertices: set = set()
    for road in player.roads:
        network_vertices.update(road.vertices)

    all_vertices: set = set()
    for v in network_vertices:
        all_vertices.add(v)
        for edge in v.edges:
            if edge in player_roads_set:
                continue
            if ov.is_edge_taken(edge):
                continue
            all_vertices.add(edge.get_other_vertex(v))

    for vertex in network_vertices:
        if vertex in all_player_vertices:
            continue
        if legal_settlement_vertex(player, vertex, sim_game):
            actions = [Action(ActionType.BUILD, (Buildable.SETTLEMENT, vertex))]
            etb = etw_estimator.calc_etb_actions(player, sim_game, actions)
            candidate_actions.append((actions, etb, 1))

    if max_extra_roads == 0:
        return candidate_actions

    potential_vertices: List[Tuple[Vertex, float]] = []
    for vertex in all_vertices - network_vertices - all_player_vertices:
        if not legal_settlement_vertex(player, vertex, sim_game):
            continue

        score = 0.0
        for h in vertex.hexes:
            if h.resource:
                score += dice_probability(h.production_number)
        potential_vertices.append((vertex, score))

    potential_vertices.sort(key=lambda x: x[1], reverse=True)
    potential_vertices = potential_vertices[:MAX_POTENTIAL_VERTICES]

    for vertex, _ in potential_vertices:
        for start_vertex in network_vertices:
            for edge in start_vertex.edges:
                if edge.get_other_vertex(start_vertex) != vertex:
                    continue
                if edge in player_roads_set:
                    continue
                if ov.is_edge_taken(edge):
                    continue

                actions = [
                    Action(ActionType.BUILD, (Buildable.ROAD, edge)),
                    Action(ActionType.BUILD, (Buildable.SETTLEMENT, vertex)),
                ]
                etb = etw_estimator.calc_etb_actions(player, sim_game, actions)
                candidate_actions.append((actions, etb, 1))
                break
            else:
                continue
            break

    return candidate_actions


def play_development_card_action(player: SimPlayerState, sim_game: SimGame) -> List[Tuple[List[Action], float, float]]:
    """Return playable development card actions and expected VP gains."""
    actions: List[Tuple[List[Action], float, float]] = []
    etb = 0.0
    for card_type, qty in player.dev_cards.items():
        if qty <= 0 or card_type == DevelopmentCardType.VICTORY_POINT:
            continue
        for _ in range(qty):
            action = Action(ActionType.PLAY_DEV_CARD, payload=card_type)
            if card_type == DevelopmentCardType.KNIGHT:
                expected_vp = expected_vp_from_knight(player, sim_game)
            else:
                expected_vp = 0.0
            actions.append(([action], etb, expected_vp))
    return actions


def purchase_development_card_action(player: SimPlayerState, sim_game: SimGame, etw_estimator: "EtwEstimator") \
        -> List[Tuple[List[Action], float, float]]:
    """Return candidate actions for buying development cards with ETB and expected VP consideration."""
    deck = sim_game.game.development_deck
    if deck.empty():
        return []

    deck_actions: List[Tuple[List[Action], float, float]] = []
    card_purchase_etb = etw_estimator.estimated_time_to_build(
        player, sim_game, Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD]
    )

    if card_purchase_etb > DEV_CARD_ETB_THRESHOLD:
        return deck_actions

    actions = [Action(ActionType.BUY_DEV_CARD)]

    vp_prob = deck.get_probability(DevelopmentCardType.VICTORY_POINT, player.dev_cards)
    if vp_prob > 0:
        deck_actions.append((actions, card_purchase_etb, vp_prob))

    if player.army_size < StrategyWeights.MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE:
        knight_prob = deck.get_probability(DevelopmentCardType.KNIGHT, player.dev_cards)
        vp_gain_knight = expected_vp_from_knight(player, sim_game)
        if knight_prob * vp_gain_knight > StrategyWeights.MIN_EXPECTED_VP_FOR_KNIGHT:
            deck_actions.append(
                (
                    actions + [Action(ActionType.END_TURN),
                               Action(ActionType.PLAY_DEV_CARD, DevelopmentCardType.KNIGHT)],
                    card_purchase_etb + 1,
                    knight_prob * vp_gain_knight,
                )
            )

    return deck_actions


def get_bank_trade_for_action(player: SimPlayerState, cost: ResourceCount) -> Optional[Action]:
    """Return a single bank trade action to make an unaffordable action feasible, or None."""
    for needed_resource, needed_amount in cost.items():
        have = player.resources.get(needed_resource, 0)
        if have >= needed_amount:
            continue

        for sell_resource in Resource:
            if sell_resource == needed_resource:
                continue

            have_sell = player.resources.get(sell_resource, 0)
            if have_sell <= 0:
                continue

            trade_ratio = get_bank_trade_ratio(player.settlements + player.cities, sell_resource)
            if have_sell >= trade_ratio:
                return Action(
                    ActionType.TRADE_WITH_BANK,
                    payload=(
                        {sell_resource: trade_ratio},
                        {needed_resource: 1},
                    ),
                )

    return None


def compute_k_lr(player: SimPlayerState, sim_game: SimGame) -> float:
    """Calculate Longest Road scaling factor for utility computations."""
    vp = player.victory_points()
    f_phase = min(vp / 10.0, 1.0)

    my_len = player.longest_road_length
    opponent_best = max((p.longest_road_length for p in get_opponents(sim_game, player.player_number)), default=0)

    longest_road = max(my_len, opponent_best)
    target = max(StrategyWeights.LR_MIN_ROAD_LENGTH, longest_road + 1)
    dist = max(0, target - my_len)
    f_dist = 1.0 / (1.0 + dist)

    gap = my_len - opponent_best
    f_contest = 1.0 / (1.0 + max(gap, 0) + EPSILON)

    k = (
        StrategyWeights.LR_BASE
        + StrategyWeights.LR_PHASE * f_phase
        + StrategyWeights.LR_DISTANCE * f_dist
        + StrategyWeights.LR_CONTEST * f_contest
    )
    return max(k, 0.0)


def compute_k_la(player: SimPlayerState, sim_game: SimGame) -> float:
    """Calculate Largest Army scaling factor for utility computations."""
    vp = player.victory_points()
    f_phase = min(vp / 10.0, 1.0)

    my_knights = player.army_size
    opponent_best = max((p.army_size for p in get_opponents(sim_game, player.player_number)), default=0)

    largest_army = max(my_knights, opponent_best)
    target = max(StrategyWeights.LA_MIN_KNIGHTS, largest_army + 1)
    dist = max(0, target - my_knights)
    f_dist = 1.0 / (1.0 + dist)

    gap = my_knights - opponent_best
    f_contest = 1.0 / (1.0 + max(gap, 0) + EPSILON)

    k = (
        StrategyWeights.LA_BASE
        + StrategyWeights.LA_PHASE * f_phase
        + StrategyWeights.LA_KNIGHT_DIST * f_dist
        + StrategyWeights.LA_CONTEST * f_contest
    )
    return max(k, 0.0)


def expected_vp_from_knight(player: SimPlayerState, sim_game: SimGame) -> float:
    """Estimate expected victory points from playing a Knight card based on army comparison."""
    my_knights = player.army_size
    opponents = get_opponents(sim_game, player.player_number)
    opponent_best = max((p.army_size for p in opponents), default=0)

    if my_knights + StrategyWeights.KNIGHT_DEFICIT_THRESHOLD < opponent_best:
        return StrategyWeights.LOW_KNIGHT_VALUE

    target = max(3, opponent_best + 1)
    if my_knights + 1 >= target and not player.has_largest_army:
        return StrategyWeights.HIGH_KNIGHT_VALUE

    if player.has_largest_army and my_knights + 1 > opponent_best:
        return StrategyWeights.MEDIUM_KNIGHT_VALUE

    return 0.0
