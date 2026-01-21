import random
from typing import Tuple, Optional, List, Set

from ai.AI import AI
from ai.RandomAI import RandomAI
from ai.actions import Phase, Action, ActionType
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
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
        # 1. Score each valid hex ---
        best_score = -1
        best_hex = None

        for h in valid_hexes:
            # Players on this hex
            players_on_h = game.get_players_on_hex(h)
            score = 0.0
            for p in players_on_h:
                # Dummy I(): always 1
                # TODO: Replace with indicator function based on inferred opponent needs
                score += p.calc_victory_points()[0] * 1
            # Multiply by dice probability
            score *= self._dice_probability(h.production_number)

            # Tie-breaking: prefer hex we do not occupy
            if h in player.settlements or h in player.cities:
                score *= 0.9  # slight penalty for own hex

            if score > best_score:
                best_score = score
                best_hex = h

        if best_hex is None:
            best_hex = random.choice(valid_hexes)

        # 2. Choose player to steal from
        players_on_best_hex = game.get_players_on_hex(best_hex)
        if not players_on_best_hex:
            return best_hex, None

        # Pick player with most cards weighted by VP
        best_player = max(
            players_on_best_hex,
            key=lambda pl: sum(p.resources.values()) * pl.calc_victory_points()[0]
        )

        return best_hex, best_player

    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        return self.random_policy.select_discard_resources(player, game, num_resources)

    def select_year_of_plenty_resources(self, player: Player, game: Game) -> ResourceCount:
        return self.random_policy.select_year_of_plenty_resources(player, game)

    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        return self.random_policy.select_monopoly_resource(player, game)

    def respond_to_trade(self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount) \
            -> Tuple[bool, Optional[ResourceCount]]:
        return self.random_policy.respond_to_trade(player, game, selling, buying)

    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        # if phase == Phase.PRE_ROLL:
        #     return Action(ActionType.ROLL)
        #
        # # Main Phase

        return self.random_policy.next_action(player, game, phase, dev_played)
