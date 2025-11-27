from random import randint, choice
from typing import List, Optional, Dict
from game.Board import Board
from game.Edge import Edge
from game.Player import Player
from game.Resources import Resource
from game.Vertex import Building, Vertex, Buildable


class Game:
    # Resource cost for each building type
    BUILDING_COST: Dict[Buildable, Dict[Resource, int]] = {
        Buildable.ROAD: {Resource.WOOD: 1, Resource.BRICK: 1},
        Buildable.SETTLEMENT: {Resource.WOOD: 1, Resource.BRICK: 1, Resource.SHEEP: 1, Resource.WHEAT: 1},
        Buildable.CITY: {Resource.ORE: 3, Resource.WHEAT: 2}
    }

    def __init__(self, players: List[Player], board: Board):
        self.players = players
        self.board = board
        self.game_over = False

    def can_afford(self, player: Player, building_type: Buildable) -> bool:
        """Check if the player has enough resources to build the given type."""
        cost = self.BUILDING_COST[building_type]

        for resource, amount_required in cost.items():
            if player.resources.get(resource, 0) < amount_required:
                return False
        return True

    def run_initial_placement(self):
        """Run the two-settlement-two-road initial placement sequence."""
        for player in self.players[:] + self.players[::-1]:
            # 1. Place settlement
            if player.is_human:
                vertex = self.get_settlement_choice(player)
            else:
                vertex = self.get_settlement_choice_ai(player)

            self.board.build_settlement(vertex, player)

            # 2. Place road
            if player.is_human:
                edge = self.get_road_choice(player, vertex)
            else:
                edge = self.get_road_choice_ai(vertex)

            self.board.build_road(edge, player)

    def start_game(self):
        """Starts the game"""
        self.run_initial_placement()
        while not self.game_over:
            for player in self.players:
                if player.is_human:
                    self.play_round(player)
                else:
                    self.play_round_ai(player)

                if self.game_over:
                    break

    def handle_initial_turn(self, player: Player):
        """Perform one settlement + one road placement for a player."""
        vertex = self.get_settlement_choice(player)
        self.board.build_settlement(vertex, player)

        edge = self.get_road_choice(player, vertex)
        self.board.build_road(edge, player)

    def roll_dice(self):
        d1, d2 = randint(1, 6), randint(1, 6)
        total = d1 + d2

        # Give resources to players
        tiles = self.board.production_to_hex[total]
        for tile in tiles:
            for vertex in tile.vertices:
                if vertex.owner is not None:
                    # There is a building on this tile
                    vertex.owner.add_resource(tile.resource, vertex.building.get_resource_yield())
                    # Temp: Give a random additional resources
                    vertex.owner.add_resource(choice([r for r in Resource if r != tile.resource]), 1)

        return d1, d2, total

    def get_buildable_options(self, player: Player) -> dict:
        """
        Returns a dictionary of possible actions the player can do this turn
        based on their resources and available board locations.

        If no locations are available or resources are insufficient, the list is empty.
        """
        options = {
            Buildable.ROAD: [],
            Buildable.SETTLEMENT: [],
            Buildable.CITY: []
        }

        # Roads
        if self.can_afford(player, Buildable.ROAD) and len(player.roads) < Buildable.ROAD.max_on_board:
            for edge in self.board.edges:
                success, _ = self.try_build_road(player, edge, build=False)
                if success:
                    options[Buildable.ROAD].append(edge)

        # Settlements
        if self.can_afford(player, Buildable.SETTLEMENT) and \
                len(player.settlements) < Buildable.SETTLEMENT.max_on_board:
            for vertex in self.board.vertices:
                success, _ = self.try_build_settlement(player, vertex, build=False, road_restriction=True)
                if success:
                    options[Buildable.SETTLEMENT].append(vertex)

        # Cities
        if self.can_afford(player, Buildable.CITY) and len(player.cities) < Buildable.CITY.max_on_board:
            for vertex in player.settlements:
                success, _ = self.try_build_city(player, vertex, build=False)
                if success:
                    options[Buildable.CITY].append(vertex)

        return options

    @staticmethod
    def try_build_settlement(player: Player, vertex: Vertex, build: bool = True,
                             use_resources: bool = True, road_restriction: bool = False) -> (bool, str):
        """
        Attempt to build a settlement for the player.
        Returns (success, message).
        Rules enforced:
        - Vertex must be unoccupied.
        - Adjacent vertices cannot have a settlement or city.
        """
        if vertex.owner is not None or vertex.building is not None:
            if vertex.owner:
                return False, f"Vertex already owned by {vertex.owner.name}"
            return False, f"Vertex already has a building: {vertex.building}"

        for edge in vertex.edges:
            for neighbour in edge.vertices:
                if neighbour is not vertex and neighbour.building is not None:
                    return False, f"Adjacent vertex already has a building"

        if road_restriction:
            connected_to_road = any(edge.owner == player for edge in vertex.edges)
            if not connected_to_road:
                return False, "Settlement must be connected to one of your roads"

        if build:
            Board.build_settlement(vertex, player)
            if use_resources:
                for resource, cost in Game.BUILDING_COST[Buildable.SETTLEMENT].items():
                    player.remove_resource(resource, cost)
        return True, f"Settlement built at {vertex}"

    @staticmethod
    def try_build_city(player: Player, vertex: Vertex, build: bool = False, use_resources: bool = False) -> (bool, str):
        """
        Attempt to upgrade a settlement to a city.
        Rules enforced:
        - Vertex must belong to player.
        - Vertex must have a settlement.
        """
        if vertex.owner != player:
            return False, f"Vertex is owned by {vertex.owner.name if vertex.owner else 'nobody'}"
        if vertex.building != Building.SETTLEMENT:
            return False, f"Vertex does not have a settlement to upgrade"

        if build:
            Board.build_city(vertex, player)
            if use_resources:
                for resource, cost in Game.BUILDING_COST[Buildable.CITY].items():
                    player.remove_resource(resource, cost)
        return True, f"City built at {vertex}"

    @staticmethod
    def try_build_road(
            player: Player,
            edge: Edge,
            vertex: Optional[Vertex] = None,
            build: bool = True,
            use_resources: bool = False,
    ) -> (bool, str):
        """
        Attempt to build a road for the player.
        Rules enforced:
        - Edge must be unoccupied.
        - If 'vertex' is provided, road must be adjacent to that vertex.
        - Otherwise, road must be adjacent to a vertex owned by the player or
          connected to one of the player's existing roads.
        """

        def _finalise_road_build() -> tuple[bool, str]:
            if build:
                Board.build_road(edge, player)
                if use_resources:
                    for resource, cost in Game.BUILDING_COST[Buildable.ROAD].items():
                        player.remove_resource(resource, cost)
            return True, f"Road built at {edge}"

        # Rule: Edge must be free
        if edge.owner is not None:
            return False, f"Edge already owned by {edge.owner.name}"

        # Special Param: Required to place road next to a specified vertex
        if vertex is not None:
            if edge not in vertex.edges:
                return False, f"Edge must connect to the specified vertex at {vertex}"
            return _finalise_road_build()

        # Rule: Adjacent to player's settlement
        if any(v.owner == player for v in edge.vertices):
            return _finalise_road_build()

        # Rule: Adjacent to player's road
        for v in edge.vertices:
            for connected_edge in v.edges:
                if connected_edge is not edge and connected_edge.owner == player:
                    return _finalise_road_build()

        # Otherwise fail
        v_info = ", ".join(v.owner.name if v.owner else "EMPTY" for v in edge.vertices)
        return False, (
            "Cannot build road: no adjacent settlement or connecting road. "
            f"Vertices: {v_info}"
        )

    # Hooks you fill in with UI

    def get_settlement_choice(self, player: Player):
        """Return the Vertex where this player places a settlement."""
        raise NotImplementedError("Choose a vertex for the settlement.")

    def get_road_choice(self, player: Player, vertex: Vertex):
        """Return the Edge where this player places a road."""
        raise NotImplementedError("Choose an edge for the road.")

    def get_settlement_choice_ai(self, player: Player):
        """Return the Vertex where this AI player places a settlement."""
        raise NotImplementedError("Choose a vertex for the settlement.")

    def get_road_choice_ai(self, vertex: Vertex):
        """Return the Edge where this AI player places a road."""
        raise NotImplementedError("Choose an edge for the road.")

    def play_round(self, player: Player):
        """Execute a single turn for a player."""
        raise NotImplementedError("Player makes turn.")

    def play_round_ai(self, player: Player):
        """Execute a single turn for an AI."""
        raise NotImplementedError("Player makes turn.")
