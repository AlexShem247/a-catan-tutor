from random import randint
from typing import List, Optional
from game.Board import Board
from game.Edge import Edge
from game.Player import Player
from game.Vertex import Building, Vertex
from view.display import clear_screen, display_board


class Game:
    def __init__(self, players: List[Player], board: Board):
        self.players = players
        self.board = board
        self.game_over = False

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
        clear_screen()
        while not self.game_over:
            for player in self.players:
                if player.is_human:
                    self.play_round(player)
                else:
                    self.play_round_ai(player)

                if self.game_over:
                    break

        print("Board final values:")
        display_board(self.board)

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

        return d1, d2, total

    @staticmethod
    def try_build_settlement(player: Player, vertex: Vertex, build: bool = True) -> (bool, str):
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
                if neighbour is not vertex and neighbour.building == Building.SETTLEMENT:
                    return False, f"Adjacent vertex already has a settlement"

        if build:
            Board.build_settlement(vertex, player)
        return True, f"Settlement built at {vertex}"

    @staticmethod
    def try_build_city(player: Player, vertex: Vertex) -> (bool, str):
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

        Board.build_city(vertex, player)
        return True, f"City built at {vertex}"

    @staticmethod
    def try_build_road(
            player: Player,
            edge: Edge,
            vertex: Optional[Vertex] = None,
            build: bool = True
    ) -> (bool, str):
        """
        Attempt to build a road for the player.
        Rules enforced:
        - Edge must be unoccupied.
        - If 'vertex' is provided, road must be adjacent to that vertex.
        - Otherwise, road must be adjacent to a vertex owned by the player or
          connected to one of the player's existing roads.
        """
        if edge.owner is not None:
            return False, f"Edge already owned by {edge.owner.name}"

        # If a vertex is provided, only allow edges connected to that vertex
        if vertex:
            if edge not in vertex.edges:
                return False, f"Edge must connect to the specified vertex at {vertex}"
            if build:
                Board.build_road(edge, player)
            return True, f"Road built at {edge}"

        # Standard rules: adjacent to a player-owned vertex
        if any(v.owner == player for v in edge.vertices):
            if build:
                Board.build_road(edge, player)
            return True, f"Road built at {edge}"

        # Or connected to existing player road
        for v in edge.vertices:
            for connected_edge in v.edges:
                if connected_edge is not edge and connected_edge.owner == player:
                    if build:
                        Board.build_road(edge, player)
                    return True, f"Road built at {edge}"

        # Fail if not connected
        v_info = ", ".join(v.owner.name if v.owner else "EMPTY" for v in edge.vertices)
        return False, f"Cannot build road: no adjacent settlement or connecting road. Vertices: {v_info}"

    # --- Hooks you fill in with UI ---

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
