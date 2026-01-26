from typing import List, Set, Tuple, Dict, Optional

from ai.SimPlayerState import SimPlayerState, dice_probability, SimGame
from ai.actions import ActionType, Action
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex, Port

# Small value to avoid division by zero
EPSILON = 1e-6

# Performance tuning constants
# These limit search space to maintain acceptable runtime

# Settlement candidate search limits
MAX_EXTRA_ROADS_FOR_SETTLEMENT = 1  # Max roads to build to reach a settlement location
MAX_POTENTIAL_VERTICES = 10  # Max vertices to consider in heuristic pre-filtering
MAX_SETTLEMENTS_FOR_CITY_UPGRADE = 2  # Max settlements to consider for city upgrade
MAX_SETTLEMENT_CANDIDATES = 3  # Max settlement candidates to include in action list

# Candidate action generation thresholds
MIN_CANDIDATES_FOR_ROAD = 3  # Minimum candidate count before considering road building
ROAD_ETB_THRESHOLD = 10.0  # Max ETB to consider building a road
DEV_CARD_ETB_THRESHOLD = 15.0  # Max ETB to consider buying development cards
MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE = 5  # Don't buy knights if army size exceeds this

# Expected VP thresholds for knight evaluation
KNIGHT_DEFICIT_THRESHOLD = 2  # Knight deficit for reduced value
LOW_KNIGHT_VALUE = 0.1  # Value when far from the largest army
HIGH_KNIGHT_VALUE = 2.0  # Value when claiming the largest army
MEDIUM_KNIGHT_VALUE = 0.5  # Value when maintaining the largest army
MIN_EXPECTED_VP_FOR_KNIGHT = 0.2  # Minimum expected VP to consider knight purchase

# ETW simulation performance limits
ETW_SIMULATION_MAX_CANDIDATES = 5  # Max candidates to evaluate during ETW simulation
ETW_ETB_THRESHOLD = 20.0  # ETB threshold to abort ETW simulation
ETW_NO_ACTION_PENALTY = 50.0  # Penalty added when no actions available
ETW_MISSING_POINT_PENALTY = 10.0  # Penalty per missing victory point
WIN_POINTS = 10  # Victory points needed to win
ETW_MAX_DEPTH_OFFSET = 5  # Offset added to WIN_POINTS for simulation depth limit
MAX_EVALUATIONS = 5  # Maximum number of candidate actions to evaluate per turn
MAX_ETB_THRESHOLD = 15.0  # Maximum ETB value to consider an action (higher = ignore)


def get_reachable_vertices(start_vertex: Vertex, player: Player, available_vertices: List[Vertex]) -> Set[Vertex]:
    """Return vertices reachable by the player from start_vertex via their roads."""
    visited: Set[Vertex] = set()
    stack: List[Vertex] = [start_vertex]

    while stack:
        v = stack.pop()
        if v in visited:
            continue
        visited.add(v)

        # Check neighbouring vertices connected by player's roads
        for edge in v.edges:
            if edge.owner == player:
                neighbour = edge.get_other_vertex(v)
                # Must be empty and obey distance rule
                if neighbour not in visited and neighbour in available_vertices:
                    stack.append(neighbour)

    return visited


def get_bank_trade_ratio(buildings: List[Vertex], resource: Resource) -> int:
    """Returns the best available trade ratio for a resource (2:1, 3:1, or 4:1)."""
    # Get all ports the player controls
    controlled_ports = {v.port for v in buildings if v.port}

    # Check for specific 2:1 port for this resource
    specific_port = Port.resource_to_port(resource)
    if specific_port in controlled_ports:
        return 2

    # Check for generic 3:1 port
    if Port.THREE_TO_ONE in controlled_ports:
        return 3

    # Default bank rate
    return 4


def expected_rolls_for_resource(player: SimPlayerState, resource: Resource) -> float:
    """Estimate the expected number of dice rolls to gather one unit of the given resource."""
    fr = player.get_production_rate(resource)

    if fr <= EPSILON:
        return float("inf")  # Cannot produce this resource

    # Expected rolls to get one unit
    return 1 / fr


def _calculate_deficits_and_excesses(current: ResourceCount, target: ResourceCount) \
        -> Tuple[Dict[Resource, int], Dict[Resource, int]]:
    """Calculate resource deficits and excesses relative to target."""
    deficits, excesses = {}, {}

    for resource in Resource:
        needed = target.get(resource, 0)
        have = current.get(resource, 0)

        if have >= needed:
            excesses[resource] = have - needed
            deficits[resource] = 0
        else:
            excesses[resource] = 0
            deficits[resource] = needed - have

    return deficits, excesses


def _calculate_trade_adjusted_rolls(
        deficits: Dict[Resource, int],
        excesses: Dict[Resource, int],
        production_rates: Dict[Resource, float],
        trade_ratio_func
) -> Dict[Resource, float]:
    """Calculate trade-adjusted rolls for each resource."""
    trade_adjusted = {}

    for resource_i in Resource:
        if deficits[resource_i] <= 0:
            trade_adjusted[resource_i] = 0.0
            continue

        # Direct production time
        direct_rolls = deficits[resource_i] * production_rates[resource_i]

        # Get trade ratio for converting to this resource
        trade_ratio = trade_ratio_func(resource_i)

        # Calculate Σ excess_rj / tradeRatio_j→i
        trade_savings = 0.0
        for resource_j in Resource:
            if resource_j == resource_i:
                continue

            excess = excesses.get(resource_j, 0)
            if excess > 0:
                # Convert excess of resource_j to resource_i via trading
                resource_i_from_trade = excess / trade_ratio
                time_saved = resource_i_from_trade * production_rates[resource_i]
                trade_savings += time_saved

        # Apply formula: max(0, direct - savings)
        trade_adjusted[resource_i] = max(0.0, direct_rolls - trade_savings)

    return trade_adjusted


def estimated_time_to_build(player: SimPlayerState, R_target: ResourceCount) -> float:
    """Optimised ETB calculation using expected values with caching."""
    target_key = tuple((r.value, R_target.get(r, 0)) for r in Resource)
    player_key = (
        player.player_number,
        tuple(v for v in player.settlements),
        tuple(v for v in player.cities)
    )
    cache_key = (player_key, target_key)

    if cache_key in player.etb_cache:
        return player.etb_cache[cache_key]

    # Get current resources
    current = {r: player.resources.get(r, 0) for r in Resource}

    # Calculate production rates
    production_rates = {
        r: expected_rolls_for_resource(player, r)
        for r in Resource
    }

    # Calculate deficits and excesses
    deficits, excesses = _calculate_deficits_and_excesses(current, R_target)

    # Calculate trade-adjusted rolls
    trade_adjusted_rolls = _calculate_trade_adjusted_rolls(
        deficits=deficits,
        excesses=excesses,
        production_rates=production_rates,
        trade_ratio_func=lambda r: get_bank_trade_ratio(player.settlements + player.cities, r)
    )

    # ETB = max of all resource times (parallel production)
    etb = max(trade_adjusted_rolls.values())

    # Cache result
    player.etb_cache[cache_key] = etb

    return etb


def legal_settlement_vertex(player: SimPlayerState, vertex: Vertex) -> bool:
    """Checks if settlement placement is legal"""
    if vertex in (player.settlements + player.cities) or vertex.owner is not None:
        # Vertex already built on
        return False

    # Check 2-distance rule: no neighbor of this vertex has a building
    for edge in vertex.edges:
        neighbour = edge.get_other_vertex(vertex)
        if neighbour in [player.settlements + player.cities] or neighbour.owner is not None:
            # Neighbour owned
            return False

    return True


def calc_etb_actions(player: SimPlayerState, total_actions: List[Action]) -> float:
    total_resources: ResourceCount = {res: 0 for res in Resource}

    for action in total_actions:
        step_resources = calc_step_resources(action)
        for res, cost in step_resources.items():
            total_resources[res] = total_resources.get(res, 0) + cost

    # Compute ETB based on total resources
    return estimated_time_to_build(player, total_resources)


def calc_step_resources(step: Action) -> ResourceCount:
    total_resources = {res: 0 for res in Resource}
    if step.type == ActionType.BUILD:
        building: Buildable = step.payload[0]
        for res, cost in Game.BUILDING_COST[building].items():
            total_resources[res] = total_resources.get(res, 0) + cost
    elif step.type == ActionType.BUY_DEV_CARD:
        total_resources = Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD]

    return total_resources


def distant_settlement_candidates(player: SimPlayerState, sim_game: SimGame) \
        -> List[Tuple[List[Action], float, float]]:
    """Find settlement candidates with optimised search and pruning."""
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
            etb = calc_etb_actions(player, actions)
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
                        etb = calc_etb_actions(player, actions)
                        candidate_actions.append((actions, etb, 1))
                        break
            else:
                continue
            break

    return candidate_actions


def get_candidate_actions(player: SimPlayerState, sim_game: SimGame, dev_played: bool, max_candidates: int = 8) \
        -> List[Tuple[List[Action], float, float]]:
    """Generate candidate actions with intelligent pruning and caching."""

    # Cache key
    cache_key = (
        player.player_number,
        dev_played,
        len(player.settlements),
        len(player.cities),
        len(player.roads),
        tuple((r.value, player.resources.get(r, 0)) for r in Resource)
    )

    if cache_key in player.candidate_cache:
        return player.candidate_cache[cache_key][:max_candidates]

    candidate_actions: List[Tuple[List[Action], float, float]] = []

    # 1. Always consider city upgrades first (high impact, low ETB)
    if len(player.cities) < Buildable.CITY.max_on_board and player.settlements:
        city_etb = estimated_time_to_build(player, Game.BUILDING_COST[Buildable.CITY])
        # Only consider best N settlement locations for cities (by production)
        sorted_settlements = sorted(
            player.settlements,
            key=lambda settlement: sum(dice_probability(h.production_number) for h in settlement.hexes),
            reverse=True
        )[:MAX_SETTLEMENTS_FOR_CITY_UPGRADE]
        for s in sorted_settlements:
            candidate_actions.append(([Action(ActionType.BUILD, (Buildable.CITY, s))], city_etb, 1))

    # 2. Settlement candidates with distance limit
    settlement_candidates = distant_settlement_candidates(player, sim_game)
    # Sort by ETB and take top N
    settlement_candidates.sort(key=lambda x: x[1])
    candidate_actions.extend(settlement_candidates[:MAX_SETTLEMENT_CANDIDATES])

    # 3. Development cards - only consider if we're close to the largest army or need VP
    points_needed = WIN_POINTS - player.victory_points()
    if player.army_size >= 2 or points_needed <= 2:
        dev_card_actions = purchase_development_card_action(player, sim_game.game)
        candidate_actions.extend(dev_card_actions)

    # 4. Play development cards if available (only if not already played this turn)
    if not dev_played:
        play_cards = play_development_card_action(player, sim_game.game)
        candidate_actions.extend(play_cards)

    # 5. Consider buying roads only if we have excess resources or need for settlements
    if len(candidate_actions) < MIN_CANDIDATES_FOR_ROAD:
        road_cost = Game.BUILDING_COST[Buildable.ROAD]
        road_etb = estimated_time_to_build(player, road_cost)
        # Only add road if we can build it relatively quickly
        if road_etb < ROAD_ETB_THRESHOLD:
            # Find a legal road edge
            for v in player.settlements + player.cities:
                for edge in v.edges:
                    if edge.owner is None:
                        candidate_actions.append((
                            [Action(ActionType.BUILD, (Buildable.ROAD, edge))],
                            road_etb,
                            0
                        ))
                        break
                if candidate_actions and len(candidate_actions[-1][0]) > 0:
                    break

    # Sort by ETB and limit
    candidate_actions.sort(key=lambda x: x[1])

    # Cache result
    player.candidate_cache[cache_key] = candidate_actions

    return candidate_actions[:max_candidates]


def expected_vp_from_knight(player: SimPlayerState, game: Game) -> float:
    """Estimate expected VP gain from buying and playing a Knight card."""
    my_knights = player.army_size
    opponents = get_opponents(player, game)
    opponent_best = max([p.army_size for p in opponents], default=0)

    # If we're at least N knights behind, knight has lower value
    if my_knights + KNIGHT_DEFICIT_THRESHOLD < opponent_best:
        return LOW_KNIGHT_VALUE  # Small chance to catch up

    # If playing a Knight gives Largest Army
    target = max(3, opponent_best + 1)  # 3 is game rule for minimum knights
    if my_knights + 1 >= target and not player.has_largest_army:
        return HIGH_KNIGHT_VALUE  # Definitely get the largest army

    # If we're maintaining the largest army
    if player.has_largest_army and my_knights + 1 > opponent_best:
        return MEDIUM_KNIGHT_VALUE  # Maintain advantage

    return 0.0


def play_development_card_action(player: SimPlayerState, game: Game) -> \
        List[Tuple[List[Action], float, float]]:
    """Generate all development card play actions to increase VP given ETB"""
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


def purchase_development_card_action(player: SimPlayerState, game: Game) -> \
        List[Tuple[List[Action], float, float]]:
    """Generate buying new development card actions."""
    deck = game.development_deck
    if deck.empty():
        return []

    deck_actions: List[Tuple[List[Action], float, float]] = []
    card_purchase_etb = estimated_time_to_build(player, Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD])

    if card_purchase_etb > DEV_CARD_ETB_THRESHOLD:
        return deck_actions

    actions = [Action(ActionType.BUY_DEV_CARD)]

    # Chance of getting VP card
    vp_prob = deck.get_probability(DevelopmentCardType.VICTORY_POINT, player.dev_cards)
    if vp_prob > 0:
        deck_actions.append((actions, card_purchase_etb, vp_prob))

    # Chance of drawing a Knight card (only if we need knights)
    if player.army_size < MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE:
        knight_prob = deck.get_probability(DevelopmentCardType.KNIGHT, player.dev_cards)
        vp_gain_knight = expected_vp_from_knight(player, game)
        if knight_prob * vp_gain_knight > MIN_EXPECTED_VP_FOR_KNIGHT:
            deck_actions.append(
                (actions + [Action(ActionType.END_TURN), Action(ActionType.PLAY_DEV_CARD, DevelopmentCardType.KNIGHT)],
                 card_purchase_etb + 1, knight_prob * vp_gain_knight))

    return deck_actions


def estimated_time_to_win(player: SimPlayerState, sim_game: SimGame, dev_played: bool, max_iterations: int = 8) \
        -> float:
    """Optimised ETW calculation with memorisation and early pruning."""

    # Create cache key
    cache_key = (
        player.player_number,
        dev_played,
        len(player.settlements),
        len(player.cities),
        len(player.roads),
        tuple((r.value, player.resources.get(r, 0)) for r in Resource)
    )

    # Check cache
    if cache_key in player.etw_cache:
        return player.etw_cache[cache_key]

    points = player.victory_points()
    if points >= WIN_POINTS:
        return 0.0

    etw = 0
    iterations = 0

    # Limit simulation depth based on current points
    max_depth = min(WIN_POINTS + ETW_MAX_DEPTH_OFFSET - points, max_iterations)

    # Use a copy for simulation
    sim_player = player.copy()

    while points < WIN_POINTS and iterations < max_depth:
        # Get candidates but limit number
        candidate_actions = get_candidate_actions(sim_player, sim_game, dev_played,
                                                  max_candidates=ETW_SIMULATION_MAX_CANDIDATES)

        if not candidate_actions:
            etw += ETW_NO_ACTION_PENALTY  # Large penalty if no actions
            break

        # Take the best candidate
        actions, etb, vp_inc = candidate_actions[0]

        # Early exit if ETB is very high
        if etb > ETW_ETB_THRESHOLD:
            etw += ETW_NO_ACTION_PENALTY
            break

        etw += etb
        points += vp_inc

        # Apply actions
        for step in actions:
            simulate_step(sim_player, sim_game.game, step)

        iterations += 1

    # Add penalty for remaining points needed
    if points < WIN_POINTS:
        etw += (WIN_POINTS - points) * ETW_MISSING_POINT_PENALTY

    # Cache result
    player.etw_cache[cache_key] = etw
    return etw


def get_opponents(player: SimPlayerState, game: Game) -> List[SimPlayerState]:
    return [SimPlayerState(p, opponent=True) for p in game.players if p.player_number != player.player_number]


def simulate_step(player: SimPlayerState, game: Game, step: Action):
    if step.type == ActionType.BUILD:
        building, loc = step.payload
        if building == Buildable.ROAD:
            # Get opponent road lengths
            opp_roads = []
            for p in game.players:
                if p.player_number != player.player_number:
                    opp_roads.append(p.longest_road_length)
            player.build_road(loc, opp_roads)
        elif building == Buildable.SETTLEMENT:
            player.build_settlement(loc)
        elif building == Buildable.CITY:
            player.build_city(loc)
    elif step.type == ActionType.PLAY_DEV_CARD:
        ctype = step.payload
        player.remove_card(ctype)
        if ctype == DevelopmentCardType.KNIGHT:
            # Get opponent army sizes
            opp_armies = []
            for p in game.players:
                if p.player_number != player.player_number:
                    opp_armies.append(p.army_size)
            player.add_knight(opp_armies)


def choose_max_utility_action(player: SimPlayerState, utilities: List[Tuple[Action, float]],
                              ignore_affordability: bool = False) -> Action:
    """Choose best action, including bank trades if needed."""
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
    """Find a single bank trade that helps make the action affordable."""

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


def get_legal_settlement_vertices(game: Game) -> List[Vertex]:
    """Get all vertices where settlement could be legally placed."""
    legal_vertices = []

    for vertex in game.get_all_vertices():
        # Skip if already occupied
        if vertex.owner is not None:
            continue

        # Check distance rule
        valid = True
        for edge in vertex.edges:
            neighbor = edge.get_other_vertex(vertex)
            if neighbor.owner is not None:
                valid = False
                break

        if valid:
            legal_vertices.append(vertex)

    return legal_vertices


def find_edge_toward_vertex(from_vertex: Vertex, target_vertex: Vertex, available_edges: List[Edge]) -> Optional[Edge]:
    """Find which available edge moves us closest to target vertex."""
    best_edge = None
    best_distance = float("inf")

    for edge in available_edges:
        if from_vertex not in edge.vertices:
            continue

        other_vertex = edge.get_other_vertex(from_vertex)

        # Estimate distance from this vertex to target
        distance = estimate_distance(other_vertex, target_vertex)

        if distance < best_distance:
            best_distance = distance
            best_edge = edge

    return best_edge


def estimate_distance(v1: Vertex, v2: Vertex) -> int:
    """Estimate distance between two vertices."""
    if v1 == v2:
        return 0

    # Check direct connection
    for edge in v1.edges:
        if edge.get_other_vertex(v1) == v2:
            return 1

    # Check if they share a neighbor (distance = 2)
    v1_neighbors = {edge.get_other_vertex(v1) for edge in v1.edges}
    v2_neighbors = {edge.get_other_vertex(v2) for edge in v2.edges}

    if v1_neighbors & v2_neighbors:
        return 2

    return 3  # Further away


def moves_toward_vertex(from_vertex: Vertex, target_vertex: Vertex) -> bool:
    """Check if from_vertex is closer to target than starting point would be."""
    return estimate_distance(from_vertex, target_vertex) <= 2


def find_gap_connection(player: Player, available_edges: List[Edge]) -> Optional[Edge]:
    """Find edge that connects disconnected road segments or settlements."""

    # Get all vertices connected by our roads
    road_vertices = set()
    for road in player.roads:
        road_vertices.update(road.vertices)

    # Check each available edge
    for edge in available_edges:
        v1, v2 = edge.vertices

        # Check if this connects a settlement/city to road network
        for structure in player.settlements + player.cities:
            if (structure == v1 and v2 not in road_vertices) or \
                    (structure == v2 and v1 not in road_vertices):
                return edge

        # Check if this connects two disconnected road segments
        v1_has_road = v1 in road_vertices
        v2_has_road = v2 in road_vertices

        if v1_has_road != v2_has_road:  # One has road, one doesn't
            return edge

    return None


def find_edge_toward_vertex_from_any(player: Player, target_vertex: Vertex,
                                     available_edges: List[Edge]) -> Optional[Edge]:
    """Find edge that moves from any player structure toward target vertex."""

    # Get all our structures (settlements, cities, road endpoints)
    our_structures = list(player.settlements + player.cities)
    for road in player.roads:
        our_structures.extend(road.vertices)

    # Find edge that gets us closest to target from any structure
    best_edge = None
    best_distance = float("inf")

    for edge in available_edges:
        v1, v2 = edge.vertices

        # Check if edge connects to one of our structures
        if v1 in our_structures or v2 in our_structures:
            # Get the vertex that's NOT our structure (the new extension)
            new_vertex = v2 if v1 in our_structures else v1

            # Estimate distance from new vertex to target
            distance = estimate_distance(new_vertex, target_vertex)

            if distance < best_distance:
                best_distance = distance
                best_edge = edge

    return best_edge


def score_hex_for_opponent(opponent: Player, game: Game, hex_tile: HexTile, importance: Dict[Resource, float]) \
        -> float:
    """Calculates importance of hex tile for opponent"""

    resource = hex_tile.resource

    # Resource not needed
    if resource not in importance:
        return 0.0

    imp = importance[resource]

    # Expected production
    production = (
            dice_probability(hex_tile.production_number)
            * game.count_player_buildings(opponent, hex_tile)
    )

    return imp * production
