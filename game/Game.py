from typing import List
from game.Board import Board
from game.Edge import Edge
from game.Player import Player
from game.Vertex import Building, Vertex


class Game:
    def __init__(self, players: List[Player], board: Board):
        self.players = players
        self.board = board
        self.initial_order = self.players[:] + self.players[::-1]  # [1, 2, 3, 4, 4, 3, 2, 1] ordering
        self.placement_index = 0
        self.game_over = False

    def run_initial_placement(self):
        """Run the two-settlement-two-road initial placement sequence."""
        for player in self.initial_order:
            self.handle_initial_turn(player)

        self.game_over = True

    def handle_initial_turn(self, player: Player):
        """Perform one settlement + one road placement for a player."""
        vertex = self.get_settlement_choice(player)
        self.board.build_settlement(vertex, player)

        edge = self.get_road_choice(player)
        self.board.build_road(edge, player)

    @staticmethod
    def try_build_settlement(player: Player, vertex: Vertex) -> (bool, str):
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
    def try_build_road(player: Player, edge: Edge) -> (bool, str):
        """
        Attempt to build a road for the player.
        Rules enforced:
        - Edge must be unoccupied.
        - Must be adjacent to a vertex owned by the player or connected to one of the player's existing roads.
        """
        if edge.owner is not None:
            return False, f"Edge already owned by {edge.owner.name}"

        # Check if edge is adjacent to a vertex owned by the player
        if any(v.owner == player for v in edge.vertices):
            Board.build_road(edge, player)
            return True, f"Road built at {edge}"

        # Check if edge is connected to an existing player road
        for v in edge.vertices:
            for connected_edge in v.edges:
                if connected_edge is not edge and connected_edge.owner == player:
                    Board.build_road(edge, player)
                    return True, f"Road built at {edge}"

        # Fail if not connected
        v_info = ", ".join(v.owner.name if v.owner else "EMPTY" for v in edge.vertices)
        return False, f"Cannot build road: no adjacent settlement or connecting road. Vertices: {v_info}"

    # --- Hooks you fill in with UI ---

    def get_settlement_choice(self, player: Player):
        """Return the Vertex where this player places a settlement."""
        raise NotImplementedError("Choose a vertex for the settlement.")

    def get_road_choice(self, player: Player):
        """Return the Edge where this player places a road."""
        raise NotImplementedError("Choose an edge for the road.")
