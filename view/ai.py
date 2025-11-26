import random

from game.Board import Board
from game.Player import Player
from game.Vertex import VertexDirection, Vertex
from view.display import clear_screen, display_board


def random_settlement(board: Board, player: Player, try_build_settlement):
    """Choose a valid random vertex for settlement."""
    available_vertices = []
    for x, y in board.HEX_COORDS:
        for direction in VertexDirection:
            vertex = board.get_vertex(x, y, direction)
            success, _ = try_build_settlement(player, vertex, build=False)
            if success:
                available_vertices.append(vertex)

    return random.choice(available_vertices) if available_vertices else None


def random_road(settlement: Vertex, try_build_road):
    """
    Choose a valid edge connected to the given settlement.
    Picks a random edge adjacent to the settlement where a road can be built.
    """
    available_edges = [e for e in settlement.edges if try_build_road(settlement.owner, e, build=False)[0]]

    if not available_edges:
        return None

    return random.choice(available_edges)


def make_round_move_ai(board: Board, player: Player, roll_dice):
    """User rolls dice and decides on move"""
    clear_screen()
    display_board(board)
    print(f"\n--- {player.name}'s turn ---\n")
    d1, d2, total = roll_dice()
    print(f"Player {player.name} rolled {d1} + {d2} = {total}\n")
    input("Press enter to continue")
