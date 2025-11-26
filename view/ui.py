from typing import Callable, Tuple

from game.Board import Board
from game.Edge import EdgeDirection, Edge
from game.Game import Game
from game.Player import Player
from game.Vertex import VertexDirection, Vertex, Buildable
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
            if dir_str.isdigit():
                direction = VertexDirection(int(dir_str))
            else:
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
            if dir_str.isdigit():
                direction = EdgeDirection(int(dir_str))
            else:
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


def make_round_move(player: Player, game: Game):
    """Handle a full turn for a human player, including dice roll, resource display, and building actions."""
    d1, d2, total = game.roll_dice()
    error_msg = None

    while True:
        clear_screen()
        display_board(game.board)
        print(f"\n--- {player.name}'s turn ---\n")
        print(f"Dice rolled: {d1} + {d2} = {total}\n")

        if error_msg:
            print(error_msg)
            error_msg = None

        # Show resources
        print("Your resources:")
        resources = list(player.resources.items())
        for i in range(0, len(resources), 2):
            first = resources[i]
            second = resources[i + 1] if i + 1 < len(resources) else None
            if second:
                print(f"{first[0].name:>5}: {first[1]:<3}\t{second[0].name:>5}: {second[1]}")
            else:
                print(f"{first[0].name:>5}: {first[1]}")

        # Show dynamic options
        options = {"1": "End turn"}
        buildable = game.get_buildable_options(player)
        option_number = 2

        for action_type in Buildable:
            if buildable[action_type]:
                options[str(option_number)] = f"Build {action_type.name.capitalize()}"
                option_number += 1

        # Print options
        print("\nOptions:")
        for key, val in options.items():
            print(f"  {key}. {val}")

        choice = input("Enter option: ").strip()

        if choice == "1":
            # End turn
            break

        elif choice in options:
            # Determine which build action
            action_str = options[choice].split()[1].upper()
            action_type = Buildable[action_str]

            # Get available locations
            available = buildable[action_type]
            if not available:
                error_msg = f"No valid {action_type.name.lower()} locations available."
                continue

            # Show locations and let player choose
            print(f"\nAvailable {action_type.name.lower()} locations:")
            for idx, loc in enumerate(available, 1):
                q, r, direction = loc.pos
                print(f"  {idx}. ({q}, {r}, {direction.name.title().replace('_', ' ')})")

            loc_choice = input(f"Enter number to build {action_type.name.lower()} or 0 to cancel: ").strip()
            try:
                idx = int(loc_choice)
                if idx == 0:
                    continue  # cancel build
                selected = available[idx - 1]
            except (ValueError, IndexError):
                error_msg = "Invalid selection."
                continue

            # Apply build
            if action_type == Buildable.ROAD:
                success, msg = game.try_build_road(player, selected, vertex=None, use_resources=True)
            elif action_type == Buildable.SETTLEMENT:
                success, msg = game.try_build_settlement(player, selected, use_resources=True)
            elif action_type == Buildable.CITY:
                success, msg = game.try_build_city(player, selected, use_resources=True)
            else:
                success, msg = False, "Unknown build type"

            print(msg)
            input("Press enter to continue...")

        else:
            error_msg = "Invalid option. Try again."


