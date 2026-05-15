from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from ai.actions import Action, ActionType
from ai.simulation.board_sim_utils import get_opponents, legal_settlement_vertex
from ai.simulation.SimGame import BoardOverlay, SimGame
from ai.simulation.SimPlayerState import SimPlayerState, dice_probability
from ai.utils.resource_utils import calc_step_resources, get_bank_trade_ratio
from config.performance_constants import (DEV_CARD_ETB_THRESHOLD, DIRECT_LIMIT, EPSILON, K_ETB_EVAL, MAX_BEAM_PER_DEPTH,
                                          MAX_CHEAP_CANDIDATES_TOTAL, MAX_EXPANSIONS_PER_STATE,
                                          MAX_EXTRA_ROADS_FOR_SETTLEMENT, MAX_SETTLEMENT_CANDIDATES, ROAD_LEN_PENALTY,
                                          START_LIMIT)
from config.StrategyWeights import StrategyWeights
from game.Game import Game
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex

if TYPE_CHECKING:
    from ai.simulation.EtwEstimator import EtwEstimator


def distant_settlement_candidates(
    player: SimPlayerState,
    sim_game: SimGame,
    etw_estimator: "EtwEstimator",
    max_extra_roads_override: Optional[int] = None,
) -> List[Tuple[List[Action], float, float]]:
    """Return promising distant settlement candidates."""

    # Can't build more settlements.
    if len(player.settlements) >= Buildable.SETTLEMENT.max_on_board:
        return []

    ov = sim_game.overlay

    # Limit how many extra roads we are willing to consider for expansion.
    max_extra_roads = min(
        Buildable.ROAD.max_on_board - len(player.roads),
        MAX_EXTRA_ROADS_FOR_SETTLEMENT,
    )
    if max_extra_roads_override is not None:
        max_extra_roads = min(max_extra_roads, max_extra_roads_override)

    player_roads_set = set(player.roads)
    all_player_vertices = set(player.settlements) | set(player.cities)

    # Vertices we can expand from: road endpoints and existing structures.
    network_vertices = _get_network_vertices(player)
    if not network_vertices:
        return []

    # Cheap yield heuristic (cached) used to guide search without ETB calls.
    _, vertex_score = _vertex_score_fn()

    # Predicate for whether a road edge is buildable.
    road_edge_available = _road_edge_available_fn(player_roads_set, ov)

    # Pick a small set of good starting points for expansion to keep the search bounded.
    start_vertices = _select_start_vertices(
        network_vertices,
        vertex_score,
        road_edge_available,
    )

    # First, consider settlements that are already directly reachable
    # (i.e. no extra roads required).
    direct_candidates = _direct_settlement_candidates(
        player=player,
        sim_game=sim_game,
        network_vertices=network_vertices,
        all_player_vertices=all_player_vertices,
        vertex_score=vertex_score,
        etw_estimator=etw_estimator,
    )

    # If we are not allowed to extend the road network, stop here.
    if max_extra_roads <= 0:
        direct_candidates.sort(key=lambda x: x[1])
        return direct_candidates[:MAX_SETTLEMENT_CANDIDATES]

    # Otherwise, explore road extensions using a bounded beam search.
    bfs_candidates = _beam_search_settlement_candidates(
        player=player,
        sim_game=sim_game,
        start_vertices=start_vertices,
        all_player_vertices=all_player_vertices,
        max_extra_roads=max_extra_roads,
        vertex_score=vertex_score,
        road_edge_available=road_edge_available,
        etw_estimator=etw_estimator,
    )

    # Merge direct and distant candidates and keep only the fastest to build.
    all_candidates = direct_candidates + bfs_candidates
    if not all_candidates:
        return []

    all_candidates.sort(key=lambda x: x[1])
    return all_candidates[:MAX_SETTLEMENT_CANDIDATES]


def play_development_card_action(player: SimPlayerState, sim_game: SimGame) -> List[Tuple[List[Action], float, float]]:
    """Generate simulated development-card actions."""
    actions: List[Tuple[List[Action], float, float]] = []
    etb = 0.0  # Playing a dev card is instantaneous (no build time)

    for card_type, qty in player.dev_cards.items():
        # Skip unavailable cards and hidden VP cards (they are scored passively).
        if qty <= 0 or card_type == DevelopmentCardType.VICTORY_POINT:
            continue

        # Each copy of a dev card is treated as a separate playable action.
        for _ in range(qty):
            action = Action(ActionType.PLAY_DEV_CARD, payload=card_type)

            # Knights may yield future VP via Largest Army, others have no direct VP value.
            if card_type == DevelopmentCardType.KNIGHT:
                expected_vp = expected_vp_from_knight(player, sim_game)
            else:
                expected_vp = 0.0

            actions.append(([action], etb, expected_vp))

    return actions


def purchase_development_card_action(
    player: SimPlayerState,
    sim_game: SimGame,
    etw_estimator: "EtwEstimator",
) -> List[Tuple[List[Action], float, float]]:
    """Generate the simulated development-card purchase action."""
    deck = sim_game.game.development_deck
    if deck.empty():
        return []

    # Only consider dev cards if they are reasonably quick to acquire (keeps search cheap and realistic).
    card_purchase_etb = etw_estimator.estimated_time_to_build(
        player,
        sim_game,
        Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD],
    )
    if card_purchase_etb > DEV_CARD_ETB_THRESHOLD:
        return []

    actions = [Action(ActionType.BUY_DEV_CARD)]

    # Expected hidden VP from the probability of drawing a VP card.
    vp_prob = deck.get_probability(DevelopmentCardType.VICTORY_POINT, player.dev_cards)
    expected_vp = vp_prob * 1.0

    # Also credit some expected value for Knights via progress toward Largest Army.
    if player.army_size < StrategyWeights.MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE:
        knight_prob = deck.get_probability(DevelopmentCardType.KNIGHT, player.dev_cards)
        expected_vp += knight_prob * expected_vp_from_knight(player, sim_game)

    return [(actions, card_purchase_etb, expected_vp)]


def get_bank_trade_for_action(player: SimPlayerState, cost: ResourceCount) -> Optional[Action]:
    """Return a bank trade that enables the target cost."""

    # Find the first resource we are short on, then see if we can convert a surplus via bank/ports.
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

            # Use the best available trade ratio (2:1/3:1 port, otherwise 4:1 bank).
            trade_ratio = get_bank_trade_ratio(player.settlements + player.cities, sell_resource)
            if have_sell >= trade_ratio:
                return Action(
                    ActionType.TRADE_WITH_BANK,
                    payload=(
                        {
                            sell_resource: trade_ratio
                        },
                        {
                            needed_resource: 1
                        },
                    ),
                )

    # No single trade can fix affordability.
    return None


def compute_k_lr(player: SimPlayerState, sim_game: SimGame) -> float:
    """Estimate the largest-road value contribution."""

    # As we get closer to 10 VP, Longest Road becomes more valuable.
    vp = player.victory_points()
    f_phase = min(vp / 10.0, 1.0)

    my_len = player.longest_road_length
    opponent_best = max(
        (p.longest_road_length for p in get_opponents(sim_game, player.player_number)),
        default=0,
    )

    # Aim to (at least) reach the current best + 1, or a minimum LR-relevant length.
    longest_road = max(my_len, opponent_best)
    target = max(StrategyWeights.LR_MIN_ROAD_LENGTH, longest_road + 1)

    # Reward being close to the target length (fewer roads needed).
    dist = max(0, target - my_len)
    f_dist = 1.0 / (1.0 + dist)

    # Reward contested situations: if we're not clearly ahead, LR is more "worth fighting for".
    gap = my_len - opponent_best
    f_contest = 1.0 / (1.0 + max(gap, 0) + EPSILON)

    # Weighted combination of phase / distance-to-target / contest.
    k = (StrategyWeights.LR_BASE + StrategyWeights.LR_PHASE * f_phase + StrategyWeights.LR_DISTANCE * f_dist +
         StrategyWeights.LR_CONTEST * f_contest)
    return max(k, 0.0)


def compute_k_la(player: SimPlayerState, sim_game: SimGame) -> float:
    """Estimate the largest-army value contribution."""

    # As we approach 10 VP, Largest Army becomes more valuable as a fast +2 VP swing.
    vp = player.victory_points()
    f_phase = min(vp / 10.0, 1.0)

    my_knights = player.army_size
    opponent_best = max(
        (p.army_size for p in get_opponents(sim_game, player.player_number)),
        default=0,
    )

    # Aim to (at least) reach the current best + 1, or the minimum LA threshold.
    largest_army = max(my_knights, opponent_best)
    target = max(StrategyWeights.LA_MIN_KNIGHTS, largest_army + 1)

    # Reward being close to the target (fewer knights needed).
    dist = max(0, target - my_knights)
    f_dist = 1.0 / (1.0 + dist)

    # Reward contested situations: if we aren't safely ahead, LA is more worth pursuing.
    gap = my_knights - opponent_best
    f_contest = 1.0 / (1.0 + max(gap, 0) + EPSILON)

    # Weighted combination of phase / distance-to-target / contest.
    k = (StrategyWeights.LA_BASE + StrategyWeights.LA_PHASE * f_phase + StrategyWeights.LA_KNIGHT_DIST * f_dist +
         StrategyWeights.LA_CONTEST * f_contest)
    return max(k, 0.0)


def expected_vp_from_knight(player: SimPlayerState, sim_game: SimGame) -> float:
    """Estimate the expected victory-point value of a knight."""
    my_knights = player.army_size
    opponents = get_opponents(sim_game, player.player_number)
    opponent_best = max((p.army_size for p in opponents), default=0)

    # If we're far behind in knights, a single Knight has low immediate value.
    if my_knights + StrategyWeights.KNIGHT_DEFICIT_THRESHOLD < opponent_best:
        return StrategyWeights.LOW_KNIGHT_VALUE

    # Check whether playing a Knight would immediately secure Largest Army.
    target = max(3, opponent_best + 1)
    if my_knights + 1 >= target and not player.has_largest_army:
        return StrategyWeights.HIGH_KNIGHT_VALUE

    # If we already have the Largest Army, extra Knights help maintain the lead.
    if player.has_largest_army and my_knights + 1 > opponent_best:
        return StrategyWeights.MEDIUM_KNIGHT_VALUE

    # Otherwise, the Knight provides no direct VP benefit right now.
    return 0.0


def _get_network_vertices(player: SimPlayerState) -> Set[Vertex]:
    """Return the vertices connected to the player's network."""
    network: Set[Vertex] = set()
    for road in player.roads:
        network.update(road.vertices)
    network.update(player.settlements)
    network.update(player.cities)
    return network


def _vertex_score_fn() -> Tuple[Dict[Vertex, float], Any]:
    """Build the cached settlement scoring function."""
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


def _road_edge_available_fn(player_roads_set: Set, ov: BoardOverlay):
    """Build the road-availability predicate for the overlay."""

    def ok(edge) -> bool:
        if edge in player_roads_set:
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
) -> float:
    """Estimate settlement paths and ETB values efficiently."""

    # Aggregate total resources required for the full action sequence.
    total_resources: ResourceCount = {res: 0 for res in Resource}

    for a in actions:
        step_resources = calc_step_resources(a)
        for res, cost in step_resources.items():
            total_resources[res] = total_resources.get(res, 0) + cost

    # Use bank/port trades only to avoid expensive opponent trade modelling here.
    return etw_estimator.estimated_time_to_build(
        player,
        sim_game,
        total_resources,
        include_player_trades=False,
    )


def _select_start_vertices(
    network_vertices: Set[Vertex],
    vertex_score,
    road_edge_available,
) -> List[Vertex]:
    """Select starting vertices for the path search."""

    # Rank starting points by local yield and how many directions they can expand.
    start_scored: List[Tuple[float, Vertex]] = []

    for v in network_vertices:
        free_out = sum(1 for e in v.edges if road_edge_available(e))
        if free_out > 0:
            # Slight bonus for vertices with multiple expansion options.
            start_scored.append((vertex_score(v) + StrategyWeights.START_VERTEX_EXPANSION_BONUS * free_out, v))

    # Fallback: if everything is blocked, expand from anywhere.
    if not start_scored:
        return list(network_vertices)

    start_scored.sort(key=lambda x: x[0], reverse=True)
    return [v for _, v in start_scored[:START_LIMIT]]


def _direct_settlement_candidates(
    player: SimPlayerState,
    sim_game: SimGame,
    network_vertices: Set[Vertex],
    all_player_vertices: Set[Vertex],
    vertex_score,
    etw_estimator: "EtwEstimator",
) -> List[Tuple[List[Action], float, float]]:
    """Return directly reachable settlement candidates."""

    # First consider settlements that can be placed immediately without road extensions.
    direct_vertices: List[Tuple[float, Vertex]] = []

    for v in network_vertices:
        if v in all_player_vertices:
            continue
        if legal_settlement_vertex(player, v, sim_game):
            direct_vertices.append((vertex_score(v), v))

    # Prefer high-yield spots.
    direct_vertices.sort(key=lambda x: x[0], reverse=True)

    direct_candidates: List[Tuple[List[Action], float, float]] = []
    for _, v in direct_vertices[:DIRECT_LIMIT]:
        actions = [Action(ActionType.BUILD, (Buildable.SETTLEMENT, v))]
        etb = _calc_etb_actions_fast(etw_estimator, player, sim_game, actions)
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
    all_player_vertices: Set[Vertex],
    max_extra_roads: int,
    vertex_score,
    road_edge_available,
    etw_estimator: "EtwEstimator",
) -> List[Tuple[List[Action], float, float]]:
    """Search settlement candidates with beam search."""

    # Track the shallowest depth at which each vertex has been reached.
    visited_best_depth: Dict[Vertex, int] = {}

    # Store promising endpoints keyed by (vertex, road_path).
    cheap_pool: Dict[Tuple[Vertex, Tuple], float] = {}

    # Initialise beam frontier from selected starting vertices.
    frontier: List[_PathState] = [_PathState(v, tuple()) for v in start_vertices]

    for depth in range(1, max_extra_roads + 1):
        next_states_scored: List[Tuple[float, _PathState]] = []

        for state in frontier:
            from_v = state.vertex
            possible_moves: List[Tuple[float, Vertex, Any]] = []

            # Expand along available road edges.
            for edge in from_v.edges:
                if not road_edge_available(edge):
                    continue

                to_v = edge.get_other_vertex(from_v)
                if to_v in all_player_vertices:
                    continue

                # Prune paths that reach a vertex no better than before.
                prev_depth = visited_best_depth.get(to_v)
                if prev_depth is not None and prev_depth <= depth:
                    continue

                possible_moves.append((vertex_score(to_v), to_v, edge))

            if not possible_moves:
                continue

            # Keep only the best few expansions per state.
            possible_moves.sort(key=lambda x: x[0], reverse=True)
            possible_moves = possible_moves[:MAX_EXPANSIONS_PER_STATE]

            for score, to_v, edge in possible_moves:
                visited_best_depth[to_v] = depth
                new_edges = state.edges + (edge, )
                # Penalise longer road chains to avoid overextension.
                beam_score = score - ROAD_LEN_PENALTY * len(new_edges)
                next_states_scored.append((-beam_score, _PathState(to_v, new_edges)))

        if not next_states_scored:
            break

        # Keep only the strongest beam states.
        next_states_scored.sort(key=lambda x: x[0])
        frontier = [st for _, st in next_states_scored[:MAX_BEAM_PER_DEPTH]]

        # From the frontier, collect legal settlement endpoints.
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

            # Stop once we have enough candidates to evaluate precisely.
            if len(cheap_pool) >= MAX_CHEAP_CANDIDATES_TOTAL:
                break

        if len(cheap_pool) >= MAX_CHEAP_CANDIDATES_TOTAL:
            break
        if depth == 1 and len(cheap_pool) >= 6:
            break

    if not cheap_pool:
        return []

    # Perform expensive ETB evaluation only on the best cheap candidates.
    shortlisted = sorted(
        cheap_pool.items(),
        key=lambda kv: kv[1],
        reverse=True,
    )[:K_ETB_EVAL]

    bfs_candidates: List[Tuple[List[Action], float, float]] = []
    for (v, edges), _ in shortlisted:
        actions = [Action(ActionType.BUILD, (Buildable.ROAD, e)) for e in edges]
        actions.append(Action(ActionType.BUILD, (Buildable.SETTLEMENT, v)))
        etb = _calc_etb_actions_fast(etw_estimator, player, sim_game, actions)
        bfs_candidates.append((actions, etb, 1.0))

    return bfs_candidates
