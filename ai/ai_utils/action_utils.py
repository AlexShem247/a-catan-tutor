from dataclasses import dataclass
from typing import List, Tuple, Optional, TYPE_CHECKING, Set, Dict, Any

from ai.ai_utils.SimGame import SimGame
from ai.ai_utils.SimPlayerState import SimPlayerState, dice_probability
from ai.ai_utils.actions import ActionType, Action
from ai.ai_utils.board_sim_utils import legal_settlement_vertex, get_opponents
from ai.ai_utils.resource_utils import get_bank_trade_ratio, calc_step_resources
from config.StrategyWeights import StrategyWeights
from config.performance_constants import (
    MAX_EXTRA_ROADS_FOR_SETTLEMENT,
    DEV_CARD_ETB_THRESHOLD,
    EPSILON, MAX_SETTLEMENT_CANDIDATES, MAX_EXPANSIONS_PER_STATE, MAX_BEAM_PER_DEPTH, DIRECT_LIMIT, ROAD_LEN_PENALTY,
    MAX_CHEAP_CANDIDATES_TOTAL, K_ETB_EVAL, START_LIMIT)
from game.Game import Game
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex

if TYPE_CHECKING:
    from ai.ai_utils.EtwEstimator import EtwEstimator


def distant_settlement_candidates(
        player: SimPlayerState,
        sim_game: SimGame,
        etw_estimator: "EtwEstimator",
        max_extra_roads_override: Optional[int] = None,
) -> List[Tuple[List[Action], float, float]]:
    """Return settlement candidates reachable via up to k extra roads using a bounded beam search."""
    if len(player.settlements) >= Buildable.SETTLEMENT.max_on_board:
        return []

    ov = sim_game.overlay

    max_extra_roads = min(
        Buildable.ROAD.max_on_board - len(player.roads),
        MAX_EXTRA_ROADS_FOR_SETTLEMENT,
    )
    if max_extra_roads_override is not None:
        max_extra_roads = min(max_extra_roads, max_extra_roads_override)

    player_roads_set = set(player.roads)
    all_player_vertices = set(player.settlements) | set(player.cities)

    # Vertices from which we can expand (road endpoints and existing structures)
    network_vertices: Set[Vertex] = set()
    for road in player.roads:
        network_vertices.update(road.vertices)
    for v in player.settlements + player.cities:
        network_vertices.add(v)

    if not network_vertices:
        return []

    # Cache for cheap vertex yield scores (no ETB calls)
    vertex_score_cache: Dict[Vertex, float] = {}

    def vertex_score(vertex: Vertex) -> float:
        """Return a cheap yield heuristic based on dice probabilities."""
        if vertex in vertex_score_cache:
            return vertex_score_cache[vertex]

        s = 0.0
        for h in vertex.hexes:
            if h.resource:
                s += dice_probability(h.production_number)

        vertex_score_cache[vertex] = s
        return s

    def road_edge_available(road_edge) -> bool:
        """Return True if a road can be built on this edge."""
        if road_edge in player_roads_set:
            return False
        if ov.is_edge_taken(road_edge):
            return False
        return True

    def calc_etb_actions_fast(etb_actions: List[Action]) -> float:
        """Compute ETB for an action sequence using bank/port trades only."""
        total_resources: ResourceCount = {res: 0 for res in Resource}
        for action in etb_actions:
            step_resources = calc_step_resources(action)
            for res, cost in step_resources.items():
                total_resources[res] = total_resources.get(res, 0) + cost

        return etw_estimator.estimated_time_to_build(
            player,
            sim_game,
            total_resources,
            include_player_trades=False,
        )

    @dataclass(frozen=True)
    class _PathState:
        vertex: Vertex
        edges: Tuple  # Tuple[Edge, ...]

    # Select a small set of good starting vertices to expand from
    start_scored: List[Tuple[float, Vertex]] = []
    for v in network_vertices:
        free_out = sum(1 for e in v.edges if road_edge_available(e))
        if free_out > 0:
            start_scored.append((vertex_score(v) + 0.05 * free_out, v))

    if start_scored:
        start_scored.sort(key=lambda x: x[0], reverse=True)
        start_vertices = [v for _, v in start_scored[:START_LIMIT]]
    else:
        start_vertices = list(network_vertices)

    # Direct settlement placements on the existing network
    direct_candidates: List[Tuple[List[Action], float, float]] = []
    direct_vertices: List[Tuple[float, Vertex]] = []

    for v in network_vertices:
        if v in all_player_vertices:
            continue
        if legal_settlement_vertex(player, v, sim_game):
            direct_vertices.append((vertex_score(v), v))

    direct_vertices.sort(key=lambda x: x[0], reverse=True)
    for _, v in direct_vertices[:DIRECT_LIMIT]:
        actions = [Action(ActionType.BUILD, (Buildable.SETTLEMENT, v))]
        etb = calc_etb_actions_fast(actions)
        direct_candidates.append((actions, etb, 1.0))

    if max_extra_roads <= 0:
        direct_candidates.sort(key=lambda x: x[1])
        return direct_candidates[:MAX_SETTLEMENT_CANDIDATES]

    # Beam BFS over road expansions using cheap heuristics
    visited_best_depth: Dict[Vertex, int] = {}
    cheap_pool: Dict[Tuple[Vertex, Tuple], float] = {}

    frontier: List[_PathState] = [_PathState(v, tuple()) for v in start_vertices]

    for depth in range(1, max_extra_roads + 1):
        next_states_scored: List[Tuple[float, _PathState]] = []

        for state in frontier:
            from_v = state.vertex
            possible_moves: List[Tuple[float, Vertex, Any]] = []

            for edge in from_v.edges:
                if not road_edge_available(edge):
                    continue

                to_v = edge.get_other_vertex(from_v)
                if to_v in all_player_vertices:
                    continue

                prev_depth = visited_best_depth.get(to_v)
                if prev_depth is not None and prev_depth <= depth:
                    continue

                possible_moves.append((vertex_score(to_v), to_v, edge))

            if not possible_moves:
                continue

            possible_moves.sort(key=lambda x: x[0], reverse=True)
            possible_moves = possible_moves[:MAX_EXPANSIONS_PER_STATE]

            for score, to_v, edge in possible_moves:
                visited_best_depth[to_v] = depth
                new_edges = state.edges + (edge,)
                beam_score = score - ROAD_LEN_PENALTY * len(new_edges)
                next_states_scored.append((-beam_score, _PathState(to_v, new_edges)))

        if not next_states_scored:
            break

        next_states_scored.sort(key=lambda x: x[0])
        frontier = [st for _, st in next_states_scored[:MAX_BEAM_PER_DEPTH]]

        for st in frontier:
            v = st.vertex
            if v in all_player_vertices:
                continue
            if not legal_settlement_vertex(player, v, sim_game):
                continue

            key = (v, st.edges)
            cheap_score = vertex_score(v) - ROAD_LEN_PENALTY * len(st.edges)
            prev = cheap_pool.get(key)
            if prev is None or cheap_score > prev:
                cheap_pool[key] = cheap_score

            if len(cheap_pool) >= MAX_CHEAP_CANDIDATES_TOTAL:
                break

        if len(cheap_pool) >= MAX_CHEAP_CANDIDATES_TOTAL:
            break

        if depth == 1 and len(cheap_pool) >= 6:
            break

    # Evaluate ETB only for the best cheap candidates
    shortlisted = sorted(
        cheap_pool.items(),
        key=lambda kv: kv[1],
        reverse=True,
    )[:K_ETB_EVAL]

    bfs_candidates: List[Tuple[List[Action], float, float]] = []
    for (v, edges), _ in shortlisted:
        actions = [Action(ActionType.BUILD, (Buildable.ROAD, e)) for e in edges]
        actions.append(Action(ActionType.BUILD, (Buildable.SETTLEMENT, v)))
        etb = calc_etb_actions_fast(actions)
        bfs_candidates.append((actions, etb, 1.0))

    all_candidates = direct_candidates + bfs_candidates
    if not all_candidates:
        return []

    all_candidates.sort(key=lambda x: x[1])
    return all_candidates[:MAX_SETTLEMENT_CANDIDATES]


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

    card_purchase_etb = etw_estimator.estimated_time_to_build(
        player, sim_game, Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD]
    )
    if card_purchase_etb > DEV_CARD_ETB_THRESHOLD:
        return []

    actions = [Action(ActionType.BUY_DEV_CARD)]

    # Expected VP from drawing a VP card
    vp_prob = deck.get_probability(DevelopmentCardType.VICTORY_POINT, player.dev_cards)
    expected_vp = vp_prob * 1.0  # VP card is worth +1 VP

    # Optional EV: value of drawing a Knight in terms of expected VP progress toward LA
    # (This is still interpretable, and does not require stochastic simulation.)
    if player.army_size < StrategyWeights.MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE:
        knight_prob = deck.get_probability(DevelopmentCardType.KNIGHT, player.dev_cards)
        expected_vp += knight_prob * expected_vp_from_knight(player, sim_game)

    return [(actions, card_purchase_etb, 0.0)]


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
