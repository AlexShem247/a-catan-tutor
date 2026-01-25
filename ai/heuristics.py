from typing import List, Set, Tuple

from ai.SimPlayerState import SimPlayerState
from ai.actions import ActionType, Action
from game.Game import Game
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex


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


def dice_probability(number):
    """Return the probability of rolling the given dice number on two six-sided dice."""
    dice_probs = {2: 1 / 36, 3: 2 / 36, 4: 3 / 36, 5: 4 / 36, 6: 5 / 36,
                  8: 5 / 36, 9: 4 / 36, 10: 3 / 36, 11: 2 / 36, 12: 1 / 36}
    return dice_probs.get(number, 0)


def expected_rolls_for_resource(player: SimPlayerState, resource: Resource) -> float:
    """Estimate the expected number of dice rolls to gather one unit of the given resource."""

    # Compute production frequency f_r for this resource
    fr = 0.0
    for v in player.settlements + player.cities:
        for h in v.hexes:
            if h.resource == resource:
                production_factor = 2 if v in player.cities else 1
                fr += dice_probability(h.production_number) * production_factor

    if fr <= 0:
        return float("inf")  # Cannot produce this resource

    # Expected rolls to get one unit
    return 1 / fr


def estimated_time_to_build(player: SimPlayerState, R_target: ResourceCount) -> float:
    """Estimate expected dice rolls to gather all resources in R_target using a capped for loop."""

    expected_rolls_per_resource = {
        r: expected_rolls_for_resource(player, r) * max(0, R_target[r] - player.resources[r])
        for r in R_target
    }

    # TODO: later: apply trading rules to owned here

    return max(expected_rolls_per_resource.values())


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
            total_resources[res] += cost

    # Compute ETB based on total resources
    return estimated_time_to_build(player, total_resources)


def calc_step_resources(step: Action) -> ResourceCount:
    total_resources = {res: 0 for res in Resource}
    if step.type == ActionType.BUILD:
        building: Buildable = step.payload[0]
        for res, cost in Game.BUILDING_COST[building].items():
            total_resources[res] += cost
    elif step.type == ActionType.BUY_DEV_CARD:
        total_resources = Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD]

    # TODO: Add others

    return total_resources


def distant_settlement_candidates(player: SimPlayerState, max_extra_roads: int = 2) \
        -> List[Tuple[List[Action], float, float]]:
    if len(player.settlements) >= Buildable.SETTLEMENT.max_on_board:
        return []

    max_extra_roads = min(Buildable.ROAD.max_on_board - len(player.roads), max_extra_roads)

    # Fast lookup structures
    player_roads_set = set(player.roads)
    player_settlement_vertices = {s for s in player.settlements}
    player_city_vertices = {c for c in player.cities}
    all_player_vertices = player_settlement_vertices | player_city_vertices

    # Collect all vertices connected to player's road network
    network_vertices = set()
    for road in player.roads:
        network_vertices.update(road.vertices)

    # Cache for settlement legality - precompute for all vertices
    legal_vertices_cache = {}
    candidate_actions = []

    # Phase 1: Check immediate network vertices (0 roads)
    for vertex in network_vertices:
        if vertex not in legal_vertices_cache:
            legal_vertices_cache[vertex] = legal_settlement_vertex(player, vertex)
        if legal_vertices_cache[vertex]:
            actions = [Action(ActionType.BUILD, (Buildable.SETTLEMENT, vertex))]
            etb = calc_etb_actions(player, actions)
            candidate_actions.append((actions, etb, 1))

    if max_extra_roads == 0:
        return candidate_actions

    # Phase 2: Check vertices reachable with 1 road
    # Build set of potential vertices for 1-road expansion
    visited_one_road = set()

    for start_vertex in network_vertices:
        for edge in start_vertex.edges:
            if edge.owner is not None or edge in player_roads_set:
                continue

            # Get the other vertex of this edge
            other_vertex = edge.get_other_vertex(start_vertex)

            # Skip if vertex is already occupied or in visited
            if (other_vertex in all_player_vertices or
                    other_vertex in visited_one_road):
                continue

            # Check if we can build a settlement here
            if other_vertex not in legal_vertices_cache:
                legal_vertices_cache[other_vertex] = legal_settlement_vertex(player, other_vertex)

            if legal_vertices_cache[other_vertex]:
                actions = [
                    Action(ActionType.BUILD, (Buildable.ROAD, edge)),
                    Action(ActionType.BUILD, (Buildable.SETTLEMENT, other_vertex))
                ]
                etb = calc_etb_actions(player, actions)
                candidate_actions.append((actions, etb, 1))

            visited_one_road.add(other_vertex)

    if max_extra_roads == 1:
        return candidate_actions

    # Phase 3: Check vertices reachable with 2 roads
    # Two approaches:

    # APPROACH 1: Direct 2-hop exploration (more efficient)
    visited_two_roads = set()

    # Explore from vertices reachable with 1 road
    for mid_vertex in visited_one_road:
        for edge in mid_vertex.edges:
            if edge.owner is not None or edge in player_roads_set:
                continue

            # Get the vertex that's 2 hops away
            end_vertex = edge.get_other_vertex(mid_vertex)

            # Skip if already visited or occupied
            if (end_vertex in visited_two_roads or
                    end_vertex in all_player_vertices or
                    end_vertex in network_vertices):
                continue

            # Need to find which road connects start_vertex to mid_vertex
            # Find the connecting edge between network and mid_vertex
            connecting_edge = None
            for e in mid_vertex.edges:
                other = e.get_other_vertex(mid_vertex)
                if other in network_vertices and e.owner is None and e not in player_roads_set:
                    connecting_edge = e
                    break

            if connecting_edge is None:
                continue

            # Check settlement legality
            if end_vertex not in legal_vertices_cache:
                legal_vertices_cache[end_vertex] = legal_settlement_vertex(player, end_vertex)

            if legal_vertices_cache[end_vertex]:
                actions = [
                    Action(ActionType.BUILD, (Buildable.ROAD, connecting_edge)),
                    Action(ActionType.BUILD, (Buildable.ROAD, edge)),
                    Action(ActionType.BUILD, (Buildable.SETTLEMENT, end_vertex))
                ]
                etb = calc_etb_actions(player, actions)
                candidate_actions.append((actions, etb, 1))

            visited_two_roads.add(end_vertex)

    return candidate_actions


def get_candidate_actions(player: SimPlayerState, game: Game, dev_played: bool) \
        -> List[Tuple[List[Action], float, float]]:
    """
    Generate all feasible action sequences for the player.

    Returns:
        List of tuples of the form (actions, etb, expected_vp), where:
            actions (List[Action]): Sequence of actions the player can take.
            etb (float): Estimated Time to Build to complete the actions.
            expected_vp (float): Expected victory points gained from the actions.
    """
    candidate_actions: List[Tuple[List[Action], float, float]] = []

    # Add legal settlements (within 0-3 roads)
    candidate_actions.extend(distant_settlement_candidates(player))

    # Add potential cities
    etb_city = estimated_time_to_build(player, Game.BUILDING_COST[Buildable.CITY])
    if len(player.cities) < Buildable.CITY.max_on_board:
        candidate_actions.extend([
            ([Action(ActionType.BUILD, (Buildable.CITY, s))], etb_city, 1) for s in player.settlements
        ])

    # Development Deck Actions
    candidate_actions.extend(purchase_development_card_action(player, game))
    if not dev_played:
        candidate_actions.extend(play_development_card_action(player, game))

    return sorted(candidate_actions, key=lambda x: x[1])


def expected_vp_from_knight(player: SimPlayerState, game: Game) -> float:
    """Estimate expected VP gain from buying and playing a Knight card."""
    my_knights = player.army_size
    opponents = get_opponents(player, game)
    opponent_best = max([p.army_size for p in opponents], default=0)

    # Current Largest Army VP (0 or 2)
    has_largest_army = 2 if player.has_largest_army else 0

    # Target to claim/retain Largest Army
    target = max(3, opponent_best + 1)

    # If playing a Knight gives Largest Army
    if my_knights + 1 >= target and not player.has_largest_army:
        la_vp_gain = 2 - has_largest_army
    else:
        la_vp_gain = 0

    return la_vp_gain


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
    """Generate buying new development card actions to increase VP given ETB"""
    deck = game.development_deck
    if deck.empty():
        return []

    deck_actions: List[Tuple[List[Action], float, float]] = []
    card_purchase_etb = estimated_time_to_build(player, Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD])
    actions = [Action(ActionType.BUY_DEV_CARD)]

    # Chance of getting VP card
    vp_prob = deck.get_probability(DevelopmentCardType.VICTORY_POINT, player.dev_cards)
    deck_actions.append((actions, card_purchase_etb, vp_prob))

    # Chance of drawing a Knight card
    knight_prob = deck.get_probability(DevelopmentCardType.KNIGHT, player.dev_cards)
    vp_gain_knight = expected_vp_from_knight(player, game)
    deck_actions.append(
        (actions + [Action(ActionType.END_TURN), Action(ActionType.PLAY_DEV_CARD, DevelopmentCardType.KNIGHT)],
         card_purchase_etb + 1, knight_prob * vp_gain_knight))

    return deck_actions


def estimated_time_to_win(player: SimPlayerState, game: Game, dev_played: bool, max_iterations=100) -> float:
    """Estimated Time to Win (ETW) Calculation"""
    points = player.victory_points()
    etw = 0
    iteration = 1
    while points < 10 and iteration < max_iterations:
        candidate_actions = get_candidate_actions(player, game, dev_played)
        if len(candidate_actions) == 0:
            return float("inf")  # No more actions possible

        actions, etb, vp_inc = candidate_actions[0]
        for step in actions:
            # Perform action
            simulate_step(player, game, step)

        etw += etb
        points += vp_inc
        iteration += 1
        if iteration > 90:
            pass

    return etw


def get_opponents(player: SimPlayerState, game: Game):
    return [p for p in game.players if p.player_number != player.player_number]


def simulate_step(player: SimPlayerState, game: Game, step: Action):
    if step.type == ActionType.BUILD:
        building, loc = step.payload
        if building == Buildable.ROAD:
            # Simulate road build
            player.build_road(loc, [p.longest_road_length for p in get_opponents(player, game)])
        elif building == Buildable.SETTLEMENT:
            player.build_settlement(loc)  # Simulate settlement build
        elif building == Buildable.CITY:
            player.build_city(loc)  # Simulate city build
    elif step.type == ActionType.PLAY_DEV_CARD:
        ctype = step.payload
        player.remove_card(ctype)
        if ctype == DevelopmentCardType.KNIGHT:
            player.add_knight([p.army_size for p in get_opponents(player, game)])


def choose_max_utility_action(player: Player, utilities: List[Tuple[Action, float]]) -> Action:
    """Choose action with the highest utility"""
    # Lets trying picking most affordable action with the highest utility, i.e. myopic
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
