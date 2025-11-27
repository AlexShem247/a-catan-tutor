import random

from game.Board import Board
from game.Game import Game
from game.Player import Player
from game.Vertex import VertexDirection, Vertex, Buildable
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


def make_round_move_ai(player: Player, game: Game):
    """Simple AI turn: AI makes decisions first, then board is displayed."""
    d1, d2, total = game.roll_dice()
    buildable = game.get_buildable_options(player)

    # Weighting: encourages cities > settlements > roads > nothing
    action_weights = {
        Buildable.CITY: 10,
        Buildable.SETTLEMENT: 8,
        Buildable.ROAD: 3,
        "NOTHING": 4,
    }

    # Build weighted action set
    weighted_actions = []
    for action_type in Buildable:
        if buildable[action_type]:
            weighted_actions.extend([action_type] * action_weights[action_type])

    # Always allow doing nothing
    weighted_actions.extend(["NOTHING"] * action_weights["NOTHING"])

    # AI makes its choice
    chosen_action = random.choice(weighted_actions)

    chosen_location = None
    msg = ""

    if chosen_action != "NOTHING":
        locations = buildable[chosen_action]
        chosen_location = random.choice(locations)

        # Perform the build
        if chosen_action == Buildable.ROAD:
            success, msg = game.try_build_road(player, chosen_location, build=True, use_resources=True)
        elif chosen_action == Buildable.SETTLEMENT:
            success, msg = game.try_build_settlement(player, chosen_location, build=True, use_resources=True)
        elif chosen_action == Buildable.CITY:
            success, msg = game.try_build_city(player, chosen_location, build=True, use_resources=True)
        else:
            msg = "AI attempted unknown action"
    else:
        msg = f"{player.name} chooses to do nothing."

    # Display results
    clear_screen()
    display_board(game.board)

    print(f"\n--- {player.name}'s turn (AI) ---\n")
    print(f"{player.name} rolled {d1} + {d2} = {total}\n")

    if chosen_action == "NOTHING":
        print(msg)
    else:
        print(msg)

    input("\nPress enter to continue...")
