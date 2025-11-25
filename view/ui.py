from typing import Callable, Tuple

from game.Board import Board
from game.Edge import EdgeDirection, Edge
from game.Player import Player
from game.Vertex import VertexDirection, Vertex
from view.display import display_board, clear_screen


def choose_vertex(board: Board, player: Player,
                  try_build_settlement: Callable[[Player, Vertex], Tuple[bool, str]]) -> Vertex:
    """Prompt the user to enter a vertex for a settlement."""
    error_msg = None
    while True:
        try:
            clear_screen()
            display_board(board)
            print(f"\n--- {player.name}'s placement turn ---\n")
            if error_msg:
                print(error_msg)

            coords = input("Enter vertex coordinates (x y) and direction (TOP, TOP_RIGHT, TOP_LEFT, etc.): ")
            x_str, y_str, dir_str = coords.strip().split()
            x, y = int(x_str), int(y_str)
            direction = VertexDirection[dir_str.upper()]
            if (x, y) not in board.HEX_COORDS:
                error_msg = f"Invalid Coordinate ({x}, {y})"
                continue
            vertex = board.get_vertex(x, y, direction)

            # Validate placement via Game
            success, msg = try_build_settlement(player, vertex)
            if success:
                return vertex
            else:
                error_msg = msg

        except (ValueError, KeyError):
            error_msg = "Invalid input. Format: x y DIRECTION (e.g. 0 2 TOP_RIGHT)"


def choose_edge(board: Board, player: Player, vertex: Vertex,
                try_build_road: Callable[[Player, Edge, Vertex], Tuple[bool, str]]) -> Edge:
    """Prompt the user to enter an edge for a road, validating via game rules."""
    error_msg = None
    while True:
        try:
            clear_screen()
            display_board(board)
            print(f"\n--- {player.name}'s road placement turn ---\n")
            if error_msg:
                print(error_msg)

            coords = input("Enter edge coordinates (x y) and direction (NORTH_WEST, EAST, etc.): ")
            x_str, y_str, dir_str = coords.strip().split()
            x, y = int(x_str), int(y_str)
            if (x, y) not in board.HEX_COORDS:
                error_msg = f"Invalid Coordinate ({x}, {y})"
                continue
            direction = EdgeDirection[dir_str.upper()]
            edge = board.get_edge(x, y, direction)

            # Validate placement via Game
            success, msg = try_build_road(player, edge, vertex)
            if success:
                return edge
            else:
                error_msg = msg

        except (ValueError, KeyError):
            error_msg = "Invalid input. Format: x y DIRECTION (e.g. 0 2 EAST)"
