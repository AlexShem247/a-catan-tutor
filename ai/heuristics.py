from typing import List, Set, Tuple

from ai.SimPlayerState import SimPlayerState, dice_probability
from ai.actions import ActionType, Action
from game.Game import Game
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex

# Small value to avoid division by zero
EPSILON = 1e-6

# Performance tuning constants
# These limit search space to maintain acceptable runtime

# Settlement candidate search limits
MAX_EXTRA_ROADS_FOR_SETTLEMENT = 1       # Max roads to build to reach a settlement location
MAX_POTENTIAL_VERTICES = 10               # Max vertices to consider in heuristic pre-filtering
MAX_SETTLEMENTS_FOR_CITY_UPGRADE = 2     # Max settlements to consider for city upgrade
MAX_SETTLEMENT_CANDIDATES = 3            # Max settlement candidates to include in action list

# Candidate action generation thresholds
MIN_CANDIDATES_FOR_ROAD = 3              # Minimum candidate count before considering road building
ROAD_ETB_THRESHOLD = 10.0                # Max ETB to consider building a road
DEV_CARD_ETB_THRESHOLD = 15.0            # Max ETB to consider buying development cards
MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE = 5    # Don't buy knights if army size exceeds this

# Expected VP thresholds for knight evaluation
KNIGHT_DEFICIT_THRESHOLD = 2             # Knight deficit for reduced value
LOW_KNIGHT_VALUE = 0.1                   # Value when far from the largest army
HIGH_KNIGHT_VALUE = 2.0                  # Value when claiming the largest army
MEDIUM_KNIGHT_VALUE = 0.5                # Value when maintaining the largest army
MIN_EXPECTED_VP_FOR_KNIGHT = 0.2         # Minimum expected VP to consider knight purchase

# ETW simulation performance limits
ETW_SIMULATION_MAX_CANDIDATES = 5        # Max candidates to evaluate during ETW simulation
ETW_ETB_THRESHOLD = 20.0                 # ETB threshold to abort ETW simulation
ETW_NO_ACTION_PENALTY = 50.0             # Penalty added when no actions available
ETW_MISSING_POINT_PENALTY = 10.0         # Penalty per missing victory point
WIN_POINTS = 10                          # Victory points needed to win
ETW_MAX_DEPTH_OFFSET = 5                 # Offset added to WIN_POINTS for simulation depth limit


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


def expected_rolls_for_resource(player: SimPlayerState, resource: Resource) -> float:
    """Estimate the expected number of dice rolls to gather one unit of the given resource."""
    fr = player.get_production_rate(resource)

    if fr <= EPSILON:  # Use EPSILON constant
        return float("inf")  # Cannot produce this resource

    # Expected rolls to get one unit
    return 1 / fr


def estimated_time_to_build(player: SimPlayerState, R_target: ResourceCount) -> float:
    """Optimised ETB calculation using expected values with caching."""

    # Check cache
    target_key = tuple((r.value, R_target.get(r, 0)) for r in Resource)
    player_key = (
        player.player_number,
        tuple(v for v in player.settlements),
        tuple(v for v in player.cities)
    )
    cache_key = (player_key, target_key)

    if cache_key in player.etb_cache:
        return player.etb_cache[cache_key]

    # Calculate expected rolls for each needed resource
    max_rolls = 0.0
    current = player.resources.copy()

    for resource, needed in R_target.items():
        if needed <= current.get(resource, 0):
            continue

        deficit = needed - current.get(resource, 0)
        expected_per_unit = expected_rolls_for_resource(player, resource)
        expected_rolls = deficit * expected_per_unit

        if expected_rolls > max_rolls:
            max_rolls = expected_rolls

    # TODO: Include trading in calculation

    # Cache result
    player.etb_cache[cache_key] = max_rolls

    return max_rolls


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


def distant_settlement_candidates(player: SimPlayerState) \
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
            if edge not in player_roads_set and edge.owner is None:
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
        if not legal_settlement_vertex(player, vertex):
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
                    if edge.owner is None and edge not in player_roads_set:
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


def get_candidate_actions(player: SimPlayerState, game: Game, dev_played: bool, max_candidates: int = 8) \
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
    settlement_candidates = distant_settlement_candidates(player)
    # Sort by ETB and take top N
    settlement_candidates.sort(key=lambda x: x[1])
    candidate_actions.extend(settlement_candidates[:MAX_SETTLEMENT_CANDIDATES])

    # 3. Development cards - only consider if we're close to the largest army or need VP
    points_needed = WIN_POINTS - player.victory_points()
    if player.army_size >= 2 or points_needed <= 2:  # Buy cards if close to army or win
        dev_card_actions = purchase_development_card_action(player, game)
        candidate_actions.extend(dev_card_actions)

    # 4. Play development cards if available (only if not already played this turn)
    if not dev_played:
        play_cards = play_development_card_action(player, game)
        candidate_actions.extend(play_cards)

    # 5. Consider buying roads only if we have excess resources or need for settlements
    if len(candidate_actions) < MIN_CANDIDATES_FOR_ROAD:  # Not many good options
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

    if card_purchase_etb > DEV_CARD_ETB_THRESHOLD:  # Too expensive, skip
        return deck_actions

    actions = [Action(ActionType.BUY_DEV_CARD)]

    # Chance of getting VP card
    vp_prob = deck.get_probability(DevelopmentCardType.VICTORY_POINT, player.dev_cards)
    if vp_prob > 0:
        deck_actions.append((actions, card_purchase_etb, vp_prob))

    # Chance of drawing a Knight card (only if we need knights)
    if player.army_size < MAX_ARMY_SIZE_FOR_KNIGHT_PURCHASE:  # Don't buy knights if we already have many
        knight_prob = deck.get_probability(DevelopmentCardType.KNIGHT, player.dev_cards)
        vp_gain_knight = expected_vp_from_knight(player, game)
        if knight_prob * vp_gain_knight > MIN_EXPECTED_VP_FOR_KNIGHT:  # Only if worthwhile
            deck_actions.append(
                (actions + [Action(ActionType.END_TURN), Action(ActionType.PLAY_DEV_CARD, DevelopmentCardType.KNIGHT)],
                 card_purchase_etb + 1, knight_prob * vp_gain_knight))

    return deck_actions


def estimated_time_to_win(player: SimPlayerState, game: Game, dev_played: bool, max_iterations: int = 8) -> float:
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
        candidate_actions = get_candidate_actions(sim_player, game, dev_played,
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
            simulate_step(sim_player, game, step)

        iterations += 1

    # Add penalty for remaining points needed
    if points < WIN_POINTS:
        etw += (WIN_POINTS - points) * ETW_MISSING_POINT_PENALTY

    # Cache result
    player.etw_cache[cache_key] = etw
    return etw


def get_opponents(player: SimPlayerState, game: Game) -> List[SimPlayerState]:
    return [SimPlayerState(p) for p in game.players if p.player_number != player.player_number]


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


def choose_max_utility_action(player: Player, utilities: List[Tuple[Action, float]]) -> Action:
    """Choose action with the highest utility."""
    affordable_actions = []

    for action, utility in utilities:
        # Calculate resource cost for this action
        cost = calc_step_resources(action)

        # Only include if player can afford it
        if player.can_afford(cost):
            affordable_actions.append((action, utility))

    if not affordable_actions:
        # No affordable action, end turn
        return Action(ActionType.END_TURN)

    # Return action with the highest utility
    return max(affordable_actions, key=lambda x: x[1])[0]
