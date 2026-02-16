from dataclasses import dataclass
from typing import List, Tuple, Optional, TYPE_CHECKING, Dict, Any

from ai.ai_utils.SimGame import SimGame, BoardOverlay
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
        weights: StrategyWeights,
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

    player_roads_list = list(player.roads)
    all_player_vertices: List[Vertex] = list(player.settlements)
    for v in player.cities:
        if v not in all_player_vertices:
            all_player_vertices.append(v)

    network_vertices = _get_network_vertices(player)
    if not network_vertices:
        return []

    _, vertex_score = _vertex_score_fn()

    road_edge_available = _road_edge_available_fn(player_roads_list, ov)

    start_vertices = _select_start_vertices(
        network_vertices,
        vertex_score,
        road_edge_available,
        weights,
    )

    direct_candidates = _direct_settlement_candidates(
        player=player,
        sim_game=sim_game,
        network_vertices=network_vertices,
        all_player_vertices=all_player_vertices,
        vertex_score=vertex_score,
        etw_estimator=etw_estimator,
        weights=weights,
    )

    if max_extra_roads <= 0:
        direct_candidates.sort(key=lambda x: x[1])
        return direct_candidates[:MAX_SETTLEMENT_CANDIDATES]

    bfs_candidates = _beam_search_settlement_candidates(
        player=player,
        sim_game=sim_game,
        start_vertices=start_vertices,
        all_player_vertices=all_player_vertices,
        max_extra_roads=max_extra_roads,
        vertex_score=vertex_score,
        road_edge_available=road_edge_available,
        etw_estimator=etw_estimator,
        weights=weights,
    )

    all_candidates = direct_candidates + bfs_candidates
    if not all_candidates:
        return []

    all_candidates.sort(key=lambda x: x[1])
    return all_candidates[:MAX_SETTLEMENT_CANDIDATES]


def play_development_card_action(
        player: SimPlayerState,
        sim_game: SimGame,
        weights: StrategyWeights,
) -> List[Tuple[List[Action], float, float]]:
    """Return playable development card actions and expected VP gains."""
    actions: List[Tuple[List[Action], float, float]] = []
    etb = 0.0

    for card_type, qty in player.dev_cards.items():
        if qty <= 0 or card_type == DevelopmentCardType.VICTORY_POINT:
            continue

        for _ in range(qty):
            action = Action(ActionType.PLAY_DEV_CARD, payload=card_type)

            if card_type == DevelopmentCardType.KNIGHT:
                expected_vp = expected_vp_from_knight(player, sim_game, weights)
            else:
                expected_vp = 0.0

            actions.append(([action], etb, expected_vp))

    return actions


def purchase_development_card_action(
        player: SimPlayerState,
        sim_game: SimGame,
        etw_estimator: "EtwEstimator",
        weights: StrategyWeights,
) -> List[Tuple[List[Action], float, float]]:
    """Return candidate actions for buying development cards with ETB and expected VP consideration."""
    deck = sim_game.game.development_deck
    if deck.empty():
        return []

    card_purchase_etb = etw_estimator.estimated_time_to_build(
        player,
        sim_game,
        Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD],
        weights,
    )
    if card_purchase_etb > DEV_CARD_ETB_THRESHOLD:
        return []

    actions = [Action(ActionType.BUY_DEV_CARD)]

    vp_prob = deck.get_probability(DevelopmentCardType.VICTORY_POINT, player.dev_cards)
    expected_vp = vp_prob * 1.0

    if player.army_size < weights.MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE:
        knight_prob = deck.get_probability(DevelopmentCardType.KNIGHT, player.dev_cards)
        expected_vp += knight_prob * expected_vp_from_knight(player, sim_game, weights)

    return [(actions, card_purchase_etb, expected_vp)]


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


def compute_k_lr(player: SimPlayerState, sim_game: SimGame, weights: StrategyWeights) -> float:
    """Calculate Longest Road scaling factor for utility computations."""
    vp = player.victory_points()
    f_phase = min(vp / 10.0, 1.0)

    my_len = player.longest_road_length
    opponent_best = max(
        (p.longest_road_length for p in get_opponents(sim_game, player.player_number)),
        default=0,
    )

    longest_road = max(my_len, opponent_best)
    target = max(weights.LR_MIN_ROAD_LENGTH, longest_road + 1)

    dist = max(0, target - my_len)
    f_dist = 1.0 / (1.0 + dist)

    gap = my_len - opponent_best
    f_contest = 1.0 / (1.0 + max(gap, 0) + EPSILON)

    k = (
            weights.LR_BASE
            + weights.LR_PHASE * f_phase
            + weights.LR_DISTANCE * f_dist
            + weights.LR_CONTEST * f_contest
    )
    return max(k, 0.0)


def compute_k_la(player: SimPlayerState, sim_game: SimGame, weights: StrategyWeights) -> float:
    """Calculate Largest Army scaling factor for utility computations."""
    vp = player.victory_points()
    f_phase = min(vp / 10.0, 1.0)

    my_knights = player.army_size
    opponent_best = max(
        (p.army_size for p in get_opponents(sim_game, player.player_number)),
        default=0,
    )

    largest_army = max(my_knights, opponent_best)
    target = max(weights.LA_MIN_KNIGHTS, largest_army + 1)

    dist = max(0, target - my_knights)
    f_dist = 1.0 / (1.0 + dist)

    gap = my_knights - opponent_best
    f_contest = 1.0 / (1.0 + max(gap, 0) + EPSILON)

    k = (
            weights.LA_BASE
            + weights.LA_PHASE * f_phase
            + weights.LA_KNIGHT_DIST * f_dist
            + weights.LA_CONTEST * f_contest
    )
    return max(k, 0.0)


def expected_vp_from_knight(player: SimPlayerState, sim_game: SimGame, weights: StrategyWeights) -> float:
    """Estimate expected victory points from playing a Knight card based on army comparison."""
    my_knights = player.army_size
    opponents = get_opponents(sim_game, player.player_number)
    opponent_best = max((p.army_size for p in opponents), default=0)

    if my_knights + weights.KNIGHT_DEFICIT_THRESHOLD < opponent_best:
        return weights.LOW_KNIGHT_VALUE

    target = max(3, opponent_best + 1)
    if my_knights + 1 >= target and not player.has_largest_army:
        return weights.HIGH_KNIGHT_VALUE

    if player.has_largest_army and my_knights + 1 > opponent_best:
        return weights.MEDIUM_KNIGHT_VALUE

    return 0.0


def _get_network_vertices(player: SimPlayerState) -> List[Vertex]:
    """Vertices we can expand from (road endpoints + existing structures)."""
    network: List[Vertex] = []
    for road in player.roads:
        for v in road.vertices:
            if v not in network:
                network.append(v)
    for v in player.settlements + player.cities:
        if v not in network:
            network.append(v)
    return network


def _vertex_score_fn() -> Tuple[Dict[Vertex, float], Any]:
    """Return (cache, fn) where fn(vertex) is a cheap yield score."""
    cache: Dict[Vertex, float] = {}

    def score(vertex: Vertex) -> float:
        if vertex in cache:
            return cache[vertex]

        s = 0.0
        for h in vertex.hexes:
            if h.resource:
                s += dice_probability(h.production_number)

        cache[vertex] = s
        return s

    return cache, score


def _road_edge_available_fn(player_roads_list: List, ov: BoardOverlay):
    """Return a predicate for whether an edge is available for building."""

    def ok(edge) -> bool:
        if edge in player_roads_list:
            return False
        if ov.is_edge_taken(edge):
            return False
        return True

    return ok


def _calc_etb_actions_fast(
        etw_estimator: "EtwEstimator",
        player: SimPlayerState,
        sim_game: SimGame,
        actions: List[Action],
        weights: StrategyWeights,
) -> float:
    """ETB for an action list using bank/port trades only (no player trades)."""
    total_resources: ResourceCount = {res: 0 for res in Resource}

    for a in actions:
        step_resources = calc_step_resources(a)
        for res, cost in step_resources.items():
            total_resources[res] = total_resources.get(res, 0) + cost

    return etw_estimator.estimated_time_to_build(
        player,
        sim_game,
        total_resources,
        weights,
        include_player_trades=False,
    )


def _select_start_vertices(
        network_vertices: List[Vertex],
        vertex_score,
        road_edge_available,
        weights: StrategyWeights,
) -> List[Vertex]:
    """Pick a small set of promising vertices to start beam expansion from."""
    start_scored: List[Tuple[float, Vertex]] = []

    for v in network_vertices:
        free_out = sum(1 for e in v.edges if road_edge_available(e))
        if free_out > 0:
            start_scored.append((vertex_score(v) + weights.START_VERTEX_EXPANSION_BONUS * free_out, v))

    if not start_scored:
        return sorted(network_vertices, key=lambda ve: (ve.pos[0], ve.pos[1], int(ve.pos[2])))

    start_scored.sort(key=lambda x: x[0], reverse=True)
    return [v for _, v in start_scored[:START_LIMIT]]


def _direct_settlement_candidates(
        player: SimPlayerState,
        sim_game: SimGame,
        network_vertices: List[Vertex],
        all_player_vertices: List[Vertex],
        vertex_score,
        etw_estimator: "EtwEstimator",
        weights: StrategyWeights,
) -> List[Tuple[List[Action], float, float]]:
    """Candidate settlements already on the connected network (no extra roads)."""
    direct_vertices: List[Tuple[float, Vertex]] = []

    for v in network_vertices:
        if v in all_player_vertices:
            continue
        if legal_settlement_vertex(player, v, sim_game):
            direct_vertices.append((vertex_score(v), v))

    direct_vertices.sort(key=lambda x: x[0], reverse=True)

    direct_candidates: List[Tuple[List[Action], float, float]] = []
    for _, v in direct_vertices[:DIRECT_LIMIT]:
        actions = [Action(ActionType.BUILD, (Buildable.SETTLEMENT, v))]
        etb = _calc_etb_actions_fast(etw_estimator, player, sim_game, actions, weights)
        direct_candidates.append((actions, etb, 1.0))

    return direct_candidates


@dataclass(frozen=True)
class _PathState:
    vertex: Vertex
    edges: Tuple


def _beam_search_settlement_candidates(
        player: SimPlayerState,
        sim_game: SimGame,
        start_vertices: List[Vertex],
        all_player_vertices: List[Vertex],
        max_extra_roads: int,
        vertex_score,
        road_edge_available,
        etw_estimator: "EtwEstimator",
        weights: StrategyWeights,
) -> List[Tuple[List[Action], float, float]]:
    """Beam BFS over road expansions, ETB-evaluate only top cheap candidates."""
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

    if not cheap_pool:
        return []

    shortlisted = sorted(
        cheap_pool.items(),
        key=lambda kv: kv[1],
        reverse=True,
    )[:K_ETB_EVAL]

    bfs_candidates: List[Tuple[List[Action], float, float]] = []
    for (v, edges), _ in shortlisted:
        actions = [Action(ActionType.BUILD, (Buildable.ROAD, e)) for e in edges]
        actions.append(Action(ActionType.BUILD, (Buildable.SETTLEMENT, v)))
        etb = _calc_etb_actions_fast(etw_estimator, player, sim_game, actions, weights)
        bfs_candidates.append((actions, etb, 1.0))

    return bfs_candidates
