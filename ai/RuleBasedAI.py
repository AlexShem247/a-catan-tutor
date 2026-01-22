import random
from collections import deque
from typing import Tuple, Optional, List, Set, Deque

from ai.AI import AI
from ai.RandomAI import RandomAI
from ai.SimPlayerState import SimPlayerState
from ai.actions import Phase, Action, ActionType
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex


class RuleBasedAI(AI):
    INIT_PLACE_YIELD_WEIGHT = 1.0  # Expected dice yield importance for first/second settlements
    INIT_PLACE_DIVERSITY_WEIGHT = 0.5  # Value of having diverse resources initially
    INIT_PLACE_BLOCK_WEIGHT = 0.3  # Penalty if initial settlement doesn't block opponent expansion

    def __init__(self):
        self.random_policy = RandomAI()

    def select_initial_settlement_location(self, player: Player, game: Game, available_vertices: List[Vertex]) \
            -> Optional[Vertex]:
        """Choose initial settlement location based on settlement utility formula."""
        if not available_vertices:
            return None

        first_settlement = len(player.settlements) == 0

        # Pick the vertex with the highest utility
        best_vertex = max(
            available_vertices,
            key=lambda v: self._vertex_utility(v, player, game, available_vertices, first_settlement),
            default=None
        )
        return best_vertex

    def select_initial_road_location(self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
        """Choose the initial road that moves toward the highest-utility settlement vertex."""
        return self.random_policy.select_initial_road_location(player, game, available_edges)

    def _vertex_utility(
            self,
            vertex: Vertex,
            player: Player,
            game: Game,
            available_vertices: List[Vertex],
            first_settlement: bool = True,
    ) -> float:
        """Compute utility of a vertex for initial placement (settlement or target road vertex)."""
        hexes = vertex.hexes
        if not hexes:
            return float("-inf")

        # Dice probability sum
        dice_sum = sum(self._dice_probability(h.production_number) for h in hexes)

        # Resource diversity
        resources = {h.resource for h in hexes if h.resource is not None}
        diversity = len(resources)

        # Blocking penalty (1 if no opponent can reach, 0 otherwise)
        blocking_penalty = 1.0
        for opp in game.players:
            if opp == player:
                continue
            for opp_v in opp.settlements:
                if vertex in self._get_reachable_vertices(opp_v, opp, available_vertices):
                    blocking_penalty = 0.0
                    break
            if blocking_penalty == 0.0:
                break

        utility = (
                self.INIT_PLACE_YIELD_WEIGHT * dice_sum +
                self.INIT_PLACE_DIVERSITY_WEIGHT * diversity -
                self.INIT_PLACE_BLOCK_WEIGHT * blocking_penalty
        )

        # For second settlement: boost if adds new resource types
        if not first_settlement:
            first_resources = set()
            for s in player.settlements:
                first_resources.update({h.resource for h in s.hexes if h.resource is not None})
            combined_diversity = len(resources | first_resources)
            utility += self.INIT_PLACE_DIVERSITY_WEIGHT * (combined_diversity - diversity)

        return utility

    def _get_reachable_vertices(self, start_vertex: Vertex, player: Player,
                                available_vertices: List[Vertex]) -> Set[Vertex]:
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

    def _dice_probability(self, number):
        """Return the probability of rolling the given dice number on two six-sided dice."""
        dice_probs = {2: 1 / 36, 3: 2 / 36, 4: 3 / 36, 5: 4 / 36, 6: 5 / 36,
                      8: 5 / 36, 9: 4 / 36, 10: 3 / 36, 11: 2 / 36, 12: 1 / 36}
        return dice_probs.get(number, 0)

    def choose_trade_partner(self, player: Player, game: Game,
                             available_players: List[Tuple[Player, Optional[ResourceCount]]]) \
            -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        return self.random_policy.choose_trade_partner(player, game, available_players)

    def select_robber_target(self, player: Player, game: Game, valid_hexes: List[HexTile]) \
            -> Tuple[HexTile, Optional[Player]]:
        # 1. Score each valid hex
        best_score = -1
        best_hex = None
        our_resource_tiles = {h for v in player.settlements + player.cities for h in v.hexes}

        for h in valid_hexes:
            # Players on this hex
            players_on_h = [p for p in game.get_players_on_hex(h) if p != player]
            score = 0.0
            for p in players_on_h:
                # Dummy I(): always 1
                # TODO: Replace with indicator function based on inferred opponent needs
                score += p.calc_victory_points()[0] * 1
            # Multiply by dice probability
            score *= self._dice_probability(h.production_number)

            # Tie-breaking: prefer hex we do not occupy
            if h in our_resource_tiles:
                score *= 0.5  # slight penalty for own hex

            if score > best_score:
                best_score = score
                best_hex = h

        if best_hex is None:
            best_hex = random.choice(valid_hexes)

        # 2. Choose player to steal from
        players_on_best_hex = [p for p in game.get_players_on_hex(best_hex) if p != player]

        if not players_on_best_hex:
            return best_hex, None

        # Pick player with most cards weighted by VP
        best_player = max(
            players_on_best_hex,
            key=lambda pl: sum(p.resources.values()) * pl.calc_victory_points()[0]
        )

        return best_hex, best_player

    def _expected_rolls_for_resource(self, player: SimPlayerState, resource: Resource) -> float:
        """Estimate the expected number of dice rolls to gather one unit of the given resource."""

        # Compute production frequency f_r for this resource
        fr = 0.0
        for v in player.settlements + player.cities:
            for h in v.hexes:
                if h.resource == resource:
                    production_factor = 2 if v in player.cities else 1
                    fr += self._dice_probability(h.production_number) * production_factor

        if fr <= 0:
            return float("inf")  # Cannot produce this resource

        # Expected rolls to get one unit
        return 1 / fr

    def _estimated_time_to_build(self, player: SimPlayerState, R_target: ResourceCount) -> float:
        """Estimate expected dice rolls to gather all resources in R_target using a capped for loop."""

        expected_rolls_per_resource = {
            r: self._expected_rolls_for_resource(player, r) * max(0, R_target[r] - player.resources[r])
            for r in R_target
        }

        # TODO: later: apply trading rules to owned here

        return max(expected_rolls_per_resource.values())

    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        return self.random_policy.select_discard_resources(player, game, num_resources)

    def select_year_of_plenty_resources(self, player: Player, game: Game) -> ResourceCount:
        return self.random_policy.select_year_of_plenty_resources(player, game)

    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        return self.random_policy.select_monopoly_resource(player, game)

    def respond_to_trade(self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount) \
            -> Tuple[bool, Optional[ResourceCount]]:
        return self.random_policy.respond_to_trade(player, game, selling, buying)

    def _legal_settlement_vertex(self, player: SimPlayerState, vertex: Vertex) -> bool:
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

    def _calc_etb_actions(self, player: SimPlayerState, total_actions: List[Action]) -> float:
        total_resources: ResourceCount = {res: 0 for res in Resource}

        for action in total_actions:
            step_resources = self._calc_step_resources(action)
            for res, cost in step_resources.items():
                total_resources[res] += cost

        # Compute ETB based on total resources
        return self._estimated_time_to_build(player, total_resources)

    def _calc_step_resources(self, step: Action) -> ResourceCount:
        total_resources = {res: 0 for res in Resource}
        if step.type == ActionType.BUILD:
            building: Buildable = step.payload[0]
            for res, cost in Game.BUILDING_COST[building].items():
                total_resources[res] += cost

        return total_resources

    def _distant_settlement_candidates(self, player: SimPlayerState, max_extra_roads: int = 2) \
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
            if self._legal_settlement_vertex(player, vertex):
                # Valid location
                total_actions = actions_so_far + [Action(ActionType.BUILD, (Buildable.SETTLEMENT, vertex))]
                etb = self._calc_etb_actions(player, total_actions)
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

    def _get_candidate_actions(self, player: SimPlayerState) -> List[Tuple[List[Action], float, int]]:
        """Generate all candidate actions to increase VP given ETB"""
        candidate_actions: List[Tuple[List[Action], float, int]] = []

        # Add legal settlements (within 0-3 roads)
        candidate_actions.extend(self._distant_settlement_candidates(player))

        # Add potential cities
        etb_city = self._estimated_time_to_build(player, Game.BUILDING_COST[Buildable.CITY])
        if len(player.cities) < Buildable.CITY.max_on_board:
            candidate_actions.extend([
                ([Action(ActionType.BUILD, (Buildable.CITY, s))], etb_city, 1) for s in player.settlements
            ])

        # TODO: Add development cards
        return sorted(candidate_actions, key=lambda x: x[1])

    def _estimated_time_to_win(self, player: SimPlayerState, max_iterations=10_000) -> float:
        """Estimated Time to Win (ETW) Calculation"""
        points = player.victory_points()
        etw = 0
        iteration = 1
        while points < 10 and iteration < max_iterations:
            candidate_actions = self._get_candidate_actions(player)
            if len(candidate_actions) == 0:
                return float("inf")  # No more actions possible

            actions, etb, vp_inc = candidate_actions[0]
            for step in actions:
                # Perform action
                self._simulate_step(player, step)

            etw += etb
            points += vp_inc
            iteration += 1

        return etw

    def _simulate_step(self, player: SimPlayerState, step: Action):
        if step.type == ActionType.BUILD:
            building, loc = step.payload
            if building == Buildable.ROAD:
                player.build_road(loc)  # Simulate road build
            elif building == Buildable.SETTLEMENT:
                player.build_settlement(loc)  # Simulate settlement build
            elif building == Buildable.CITY:
                player.build_city(loc)  # Simulate city build
        # TODO: Handle other actions steps

    def _select_best_action(self, player: Player, utilities: List[Tuple[Action, float]]) -> Action:
        """Choose action with the highest utility"""
        # Lets trying picking most affordable action with the highest utility, i.e. myopic
        affordable_actions = []

        for action, utility in utilities:
            # Calculate resource cost for this action
            cost = self._calc_step_resources(action)

            # Only include if player can afford it
            if player.can_afford(cost):
                affordable_actions.append((action, utility))

        if not affordable_actions:
            # No affordable action, end turn
            return Action(ActionType.END_TURN)

        # Return action with the highest utility
        return max(affordable_actions, key=lambda x: x[1])[0]

    def _evaluate_utilities(self, player: SimPlayerState, candidates: List[Tuple[List[Action], float, int]],
                            etw_before: float) -> List[Tuple[Action, float]]:

        # TODO: Add other factors and weights
        utilities = []

        for actions, _, _ in candidates:
            # Simulate action on a copy of the player state
            step = actions[0]
            player_copy = player.copy()
            self._simulate_step(player_copy, step)  # update state copy
            etw_after = self._estimated_time_to_win(player_copy)

            if etw_before == 0:
                u_self = 0  # Already won, or no improvement possible
            else:
                u_self = (etw_before - etw_after) / etw_before * 100

            # Discount for time: ETB of the action itself
            etb_action = self._calc_etb_actions(player, [step])
            discount_rate = 0.1
            eu = u_self / ((1 + discount_rate) ** etb_action)
            utilities.append((step, eu))

        return utilities

    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        if phase == Phase.PRE_ROLL:
            return Action(ActionType.ROLL)

        # Main Phase
        sim_player = SimPlayerState(player)
        etw_before = self._estimated_time_to_win(sim_player.copy())
        candidates = self._get_candidate_actions(sim_player)
        utilities = self._evaluate_utilities(sim_player, candidates, etw_before)
        best_action = self._select_best_action(player, utilities)

        return best_action
