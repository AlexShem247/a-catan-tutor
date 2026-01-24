from collections import deque
from typing import List, Set, Tuple, Deque

from ai.SimPlayerState import SimPlayerState
from ai.actions import ActionType, Action
from game.Game import Game
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentDeck, DevelopmentCardType
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
        -> List[Tuple[List[Action], float, int]]:
    """
    Finds potential settlement locations reachable within 0 to max_extra_roads from
    the player's existing roads/settlements.
    """
    if len(player.settlements) >= Buildable.SETTLEMENT.max_on_board:
        # Cannot build more settlements
        return []

    max_extra_roads = min(Buildable.ROAD.max_on_board - len(player.roads), max_extra_roads)
    candidate_actions = []

    # All vertices reachable via player's current roads
    network_vertices = set()
    for road in player.roads:
        network_vertices.update(road.vertices)

    # BFS queue: (current_vertex, actions_so_far, roads_used)
    queue: Deque[Tuple[Vertex, List[Action], int]] = deque()
    for v in network_vertices:
        queue.append((v, [], 0))  # (vertex, action list, roads used)

    visited = set()  # keep track of vertices we've explored with a given road count

    while queue:
        vertex, actions_so_far, roads_used = queue.popleft()

        # Skip if we already visited this vertex with fewer or equal roads
        key = (vertex, roads_used)
        if key in visited or roads_used > max_extra_roads:
            continue
        visited.add(key)

        # Check if we can build a settlement here
        if legal_settlement_vertex(player, vertex):
            # Valid location
            total_actions = actions_so_far + [Action(ActionType.BUILD, (Buildable.SETTLEMENT, vertex))]
            etb = calc_etb_actions(player, total_actions)
            candidate_actions.append((total_actions, etb, 1))

        # Explore neighbors to extend network by one road
        for edge in vertex.edges:
            if edge in player.roads:
                # Player already owns edge
                continue

            if edge.owner is not None:
                # Opponent owns edge
                continue

            if edge in [a.payload[1] for a in actions_so_far]:
                # Edge always built in our current path
                continue

            # Edge is unowned
            # Legal to add a road here?
            if len(actions_so_far) + 1 <= max_extra_roads:
                new_actions = actions_so_far + [Action(ActionType.BUILD, (Buildable.ROAD, edge))]
                queue.append((edge.get_other_vertex(vertex), new_actions, roads_used + 1))

    return candidate_actions


def get_candidate_actions(player: SimPlayerState, game: Game) -> List[Tuple[List[Action], float, float]]:
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
    candidate_actions.extend(purchase_development_card_action(player, game.development_deck))

    # TODO: Add other development cards
    return sorted(candidate_actions, key=lambda x: x[1])


def purchase_development_card_action(player: SimPlayerState, deck: DevelopmentDeck) -> \
        List[Tuple[List[Action], float, float]]:
    """Generate all development card actions to increase VP given ETB"""
    if deck.empty():
        return []

    deck_actions: List[Tuple[List[Action], float, float]] = []
    card_purchase_etb = estimated_time_to_build(player, Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD])
    actions = [Action(ActionType.BUY_DEV_CARD)]

    # Chance of getting VP card
    vp_prob = deck.get_probability(DevelopmentCardType.VICTORY_POINT, player.dev_cards)
    deck_actions.append((actions, card_purchase_etb, vp_prob))

    return deck_actions


def estimated_time_to_win(player: SimPlayerState, game: Game, max_iterations=10_000) -> float:
    """Estimated Time to Win (ETW) Calculation"""
    points = player.victory_points()
    etw = 0
    iteration = 1
    while points < 10 and iteration < max_iterations:
        candidate_actions = get_candidate_actions(player, game)
        if len(candidate_actions) == 0:
            return float("inf")  # No more actions possible

        actions, etb, vp_inc = candidate_actions[0]
        for step in actions:
            # Perform action
            simulate_step(player, step)

        etw += etb
        points += vp_inc
        iteration += 1

    return etw


def simulate_step(player: SimPlayerState, step: Action):
    if step.type == ActionType.BUILD:
        building, loc = step.payload
        if building == Buildable.ROAD:
            player.build_road(loc)  # Simulate road build
        elif building == Buildable.SETTLEMENT:
            player.build_settlement(loc)  # Simulate settlement build
        elif building == Buildable.CITY:
            player.build_city(loc)  # Simulate city build
    # TODO: Handle other actions steps


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
