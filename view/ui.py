from game.Board import Board
from game.Edge import EdgeDirection, Edge
from game.Game import Game
from game.Player import Player
from game.Resources import Resource
from game.Vertex import VertexDirection, Vertex, Buildable
from view.display import display_board, clear_screen, get_player_lead_status, display_resources


def initial_settlement_placement(player: Player, game: Game) -> Vertex:
    """Prompt the user to enter a vertex for a settlement."""
    error_msg = None
    while True:
        try:
            clear_screen()
            display_board(game)
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
            if (x, y) not in Board.HEX_COORDS:
                error_msg = f"Invalid Coordinate ({x}, {y})"
                continue
            vertex = game.get_vertex(x, y, direction)

            # Validate placement via Game
            success, msg = game.try_build_settlement(player, vertex, use_resources=False, road_restriction=False)
            if success:
                return vertex
            else:
                error_msg = msg

        except (ValueError, KeyError):
            error_msg = "Invalid input. Format: x y DIRECTION (e.g. 0 2 TOP_RIGHT)"


def initial_road_placement(settlement: Vertex, game: Game) -> Edge:
    """Prompt the user to enter an edge for a road, validating via game rules."""
    player = settlement.owner
    error_msg = None
    while True:
        try:
            clear_screen()
            display_board(game)
            print(f"\n--- {player.name}'s road placement turn ---\n")
            if error_msg:
                print(error_msg)

            coords = input("Enter edge coordinates (x y) and direction (NORTH_WEST, EAST, etc.): ")
            x_str, y_str, dir_str = coords.strip().split()
            x, y = int(x_str), int(y_str)
            if (x, y) not in Board.HEX_COORDS:
                error_msg = f"Invalid Coordinate ({x}, {y})"
                continue
            if dir_str.isdigit():
                direction = EdgeDirection(int(dir_str))
            else:
                direction = EdgeDirection[dir_str.upper()]
            edge = game.get_edge(x, y, direction)

            # Validate placement via Game
            success, msg = game.try_build_road(player, edge, on_vertex=settlement, use_resources=False)
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
        display_board(game)
        print(f"\n--- {player.name}'s turn ---\n")
        print(f"Dice rolled: {d1} + {d2} = {total}")

        if error_msg:
            print(error_msg)
            error_msg = None

        # Show stats
        print(f"Longest Road: \t{player.longest_road_length} {'♕' if player.has_longest_road else ''}")
        print(f"Victory Points: {player.calc_victory_points()} {get_player_lead_status(player)}\n")

        # Show resources
        print("Your resources:")
        display_resources(player.resources)

        # Show dynamic options
        options = {"1": "End turn", "2": "Open Trade Menu"}
        buildable = game.get_buildable_options(player)
        option_number = 3

        for action_type in Buildable:
            if buildable[action_type]:
                options[str(option_number)] = f"Build {action_type.name.capitalize()}"
                option_number += 1

        # Print options
        print("\nOptions:")
        for key, val in options.items():
            print(f"  {key}. {val}")

        if player.calc_victory_points() >= Game.VICTORY_POINTS_TO_WIN:
            break

        choice = input("Enter option: ").strip()

        if choice == "1" or choice == "":
            # End turn
            break

        if choice == "2":
            trading_menu(player, game)

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
                print(f"  {idx}. ({loc.get_pos()})")

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
                success, msg = game.try_build_road(player, selected)
            elif action_type == Buildable.SETTLEMENT:
                success, msg = game.try_build_settlement(player, selected)
            elif action_type == Buildable.CITY:
                success, msg = game.try_build_city(player, selected)
            else:
                success, msg = False, "Unknown build type"

            print(msg)
            input("Press enter to continue...")

        else:
            error_msg = "Invalid option. Try again."


def trading_menu(player: Player, game: Game):
    """Display trading menu, allow bank or player trades, auto-return after trade or cancel."""
    selling = {res: 0 for res in Resource}
    buying = {res: 0 for res in Resource}

    while True:
        clear_screen()
        display_board(game)
        print(f"\n--- {player.name}'s Trading Menu ---\n")

        # Print current trading hand
        print("You give:")
        display_resources(selling, player)

        print("\nYou receive:")
        display_resources(buying)

        trade_incomplete = all(v == 0 for v in selling.values()) or all(v == 0 for v in buying.values())
        valid_bank_trade = (not trade_incomplete and
                            game.try_trade_with_bank(player, selling, buying, use_resources=False))
        valid_player_trade = not trade_incomplete

        print("\nOptions:")
        print("  1. [RESOURCE] [AMOUNT] - Modify Selling Resource")
        print("  2. [RESOURCE] [AMOUNT] - Modify Buying Resource")
        print(f"  3. Trade with Bank - {'TRADE VALID' if valid_bank_trade else 'TRADE INCOMPLETE'}")
        print(f"  4. Trade with Player - {'TRADE VALID' if valid_player_trade else 'TRADE INCOMPLETE'}")
        print("  5. Terminate Trade")

        user_input = input("Enter option: ").strip().split()

        if not user_input:
            print("Invalid input. Press enter to continue...")
            input()
            continue

        option = user_input[0]

        # Trade builder options
        if option in {"1", "2"}:
            if len(user_input) != 3:
                print("Invalid input. Usage: <option> <RESOURCE> <AMOUNT>")
                input("Press enter to continue...")
                continue

            res_str = user_input[1].upper()
            amt_str = user_input[2]

            try:
                res = Resource[res_str]
                amt = max(0, min(int(amt_str), player.resources.get(res)))
            except (KeyError, ValueError):
                print("Invalid resource or amount. Press enter to continue...")
                input()
                continue

            if option == "1":
                selling[res] = amt
            else:
                buying[res] = amt

        elif option == "3":
            # Trade with bank using the current selling and buying dicts
            success = game.try_trade_with_bank(player, selling, buying)
            if success:
                print("Bank trade completed!")
                # Reset trade
                selling = {res: 0 for res in Resource}
                buying = {res: 0 for res in Resource}
            else:
                print("Bank trade failed. Check rules or resources.")
            input("Press enter to continue...")

        elif option == "4":
            # Trade with player (you can implement similarly)
            # Here, just a placeholder
            print("Player trade not implemented yet.")
            input("Press enter to continue...")

        elif option == "5":
            return  # terminate trade

        else:
            print("Invalid option. Press enter to continue...")
            input()
