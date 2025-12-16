from typing import List, Optional, Tuple

from GameController import GameController
from game.Board import Board
from game.Edge import EdgeDirection, Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import VertexDirection, Vertex
from view.display import display_board, clear_screen, get_player_lead_status, display_resources, display_trade_offer, \
    format_counter_offer


def initial_settlement_placement(player: Player, controller: GameController) -> Vertex:
    """Prompt the user to enter a vertex for a settlement."""
    error_msg = None
    while True:
        try:
            clear_screen()
            display_board(controller.get_game_state())
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
            vertex = controller.get_vertex(x, y, direction)

            # Validate placement via Game
            success, msg = controller.try_build_settlement(player, vertex, use_resources=False, road_restriction=False)
            if success:
                return vertex
            else:
                error_msg = msg

        except (ValueError, KeyError):
            error_msg = "Invalid input. Format: x y DIRECTION (e.g. 0 2 TOP_RIGHT)"


def initial_road_placement(settlement: Vertex, controller: GameController) -> Edge:
    """Prompt the user to enter an edge for a road, validating via game rules."""
    player = settlement.owner
    error_msg = None
    while True:
        try:
            clear_screen()
            display_board(controller.get_game_state())
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
            edge = controller.get_edge(x, y, direction)

            # Validate placement via Game
            success, msg = controller.try_build_road(player, edge, on_vertex=settlement, use_resources=False)
            if success:
                return edge
            else:
                error_msg = msg

        except (ValueError, KeyError):
            error_msg = "Invalid input. Format: x y DIRECTION (e.g. 0 2 EAST)"


def make_round_move(player: Player, controller: GameController):
    """Handle a full turn for a human player, including dice roll, resource display, and building actions."""
    d1, d2, total = controller.roll_dice(player)
    error_msg = None

    while True:
        clear_screen()
        display_board(controller.get_game_state())
        print(f"\n--- {player.name}'s turn ---\n")
        print(f"Dice rolled: {d1} + {d2} = {total}")

        if error_msg:
            print(error_msg)
            error_msg = None

        # Show stats
        visible_vp, true_vp = player.calc_victory_points()
        true_vp_str = ""
        if visible_vp != true_vp:
            true_vp_str = f" ({true_vp})"

        print(f"Longest Road: \t{player.longest_road_length} {'♕' if player.has_longest_road else ''}")
        print(f"Army Size: \t{player.army_size} {'♕' if player.has_largest_army else ''}")
        print(f"Victory Points: {visible_vp}{true_vp_str} {get_player_lead_status(player)}\n")

        # Show resources
        print("Your resources:")
        display_resources(player.resources)

        # Show dynamic options
        options = {"1": "End turn", "2": "Open Trade Menu"}
        buildable = controller.get_buildable_options(player)
        option_number = 3

        # Add buildable options
        for action_type in Buildable:
            if buildable[action_type]:
                action = "Buy " if action_type == Buildable.DEVELOPMENT_CARD else "Build "
                options[str(option_number)] = action + action_type.name.replace("_", " ").capitalize()
                option_number += 1
        dc_option_index = option_number

        # Add development card options
        playable_cards = set([c.card_type for c in player.development_cards if c.playable])
        for card_type in playable_cards:
            options[str(option_number)] = f"Use {card_type.name.upper()} card"

        # Print options
        print("\nOptions:")
        for key, val in options.items():
            print(f"  {key}. {val}")

        if player.calc_victory_points()[1] >= Game.VICTORY_POINTS_TO_WIN:
            break

        choice = input("Enter option: ").strip()

        if choice == "1" or choice == "":
            # End turn
            break

        if choice == "2":
            trading_menu(player, controller)

        elif choice.isnumeric() and 3 <= int(choice) < dc_option_index and choice in options:
            # Determine which build action
            action_str = options[choice].split()[1].upper()
            if "DEVELOPMENT" in action_str:
                action_type = Buildable.DEVELOPMENT_CARD
            else:
                action_type = Buildable[action_str]
            selected: Edge | Vertex | None = None

            if action_type != Buildable.DEVELOPMENT_CARD:
                # Need to pick a location
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
                success, msg = controller.try_build_road(player, selected)
            elif action_type == Buildable.SETTLEMENT:
                success, msg = controller.try_build_settlement(player, selected)
            elif action_type == Buildable.CITY:
                success, msg = controller.try_build_city(player, selected)
            elif action_type == Buildable.DEVELOPMENT_CARD:
                success, msg = controller.try_buy_development_card(player)
            else:
                success, msg = False, "Unknown build type"

            print(msg)
            input("Press enter to continue...")
        elif choice.isnumeric() and dc_option_index <= int(choice) and choice in options:
            # Play development card
            card_type = DevelopmentCardType[options[choice].split()[1]]
            controller.play_development_card(player, card_type)

        else:
            error_msg = "Invalid option. Try again."


def select_player_to_trade(controller: GameController, player: Player, original_offer: ResourceCount,
                           willing_players: List[Tuple[Player, Optional[ResourceCount]]]
                           ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
    """
        Let human select a trade to accept.
        Shows AI counteroffers, even if unaffordable.
        Marks trades as Affordable / Cannot Afford.
    """
    clear_screen()
    display_board(controller.get_game_state())
    print(f"\n--- {player.name}'s Trading Menu ---\n")

    if not willing_players:
        print("No players are willing to trade with you right now.")
        input("\nPress enter to continue...")
        return None

    # Prepare display and valid options
    valid_options = {}
    option_num = 1
    print("Available trades:")

    for p, counter in willing_players:
        # Format trade string
        if counter is None:
            can_afford = True
            trade_str = format_counter_offer(original_offer, original_offer)
        else:
            can_afford = all(player.resources.get(res, 0) >= amt for res, amt in counter.items())
            trade_str = (format_counter_offer(original_offer, counter) +
                         (" (AFFORDABLE)" if can_afford else " (CANNOT AFFORD)"))

        # Print option
        if can_afford:
            print(f"{option_num}. Trade {p.name}: {trade_str}")
            valid_options[option_num] = (p, counter)
            option_num += 1
        else:
            # Show unaffordable with X
            print(f"X. Trade {p.name}: {trade_str}")

    if not valid_options:
        print("\nYou cannot afford any of these trades.")
        input("Press enter to continue...")
        return None

    # Cancel option always last
    print(f"{option_num}. Cancel trade")
    valid_options[option_num] = None

    # Ask player to select
    while True:
        choice = input("\nSelect a trade to accept: ").strip()
        if choice == "":
            return None
        if choice.isdigit():
            choice = int(choice)
            if choice in valid_options:
                return valid_options[choice]
        print("Invalid choice, please enter a number from the list of affordable trades.")


def trading_menu(player: Player, controller: GameController):
    """Display trading menu, allow bank or player trades, auto-return after trade or cancel."""
    selling: ResourceCount = {res: 0 for res in Resource}
    buying: ResourceCount = {res: 0 for res in Resource}

    while True:
        clear_screen()
        display_board(controller.get_game_state())
        print(f"\n--- {player.name}'s Trading Menu ---\n")

        # Print current trading hand
        print("You give:")
        display_resources(selling, player.resources)

        print("\nYou receive:")
        display_resources(buying)

        trade_incomplete = all(v == 0 for v in selling.values()) or all(v == 0 for v in buying.values())
        valid_bank_trade = (not trade_incomplete and
                            controller.try_trade_with_bank(player, selling, buying, use_resources=False))
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
                amt = max(0, int(amt_str))
            except (KeyError, ValueError):
                print("Invalid resource or amount. Press enter to continue...")
                input()
                continue

            if option == "1":
                selling[res] = min(amt, player.resources.get(res))
                buying[res] = 0
            else:
                selling[res] = 0
                buying[res] = amt

        elif option == "3":
            # Trade with bank using the current selling and buying dicts
            success = controller.try_trade_with_bank(player, selling, buying)
            if success:
                print("Bank trade completed!")
                # Reset trade
                selling = {res: 0 for res in Resource}
                buying = {res: 0 for res in Resource}
            else:
                print("Bank trade failed. Check rules or resources.")
            input("Press enter to continue...")

        elif option == "4":
            # Trade with players
            willing_players = controller.trade_with_players(player, selling, buying)
            deal = select_player_to_trade(controller, player, selling, willing_players)

            if deal is not None:
                buying_player, counter = deal
                if counter is not None:
                    selling = counter  # Player accepted counteroffer

                controller.trade_between_players(player, selling, buying_player, buying)
                print(f"\nTrade completed with {buying_player.name}.")

                # Reset trade
                selling = {res: 0 for res in Resource}
                buying = {res: 0 for res in Resource}

                input("\nPress enter to continue...")

        elif option == "5":
            return  # terminate trade

        else:
            print("Invalid option. Press enter to continue...")
            input()


def trade_manager(controller: GameController, player: Player, selling: ResourceCount,
                  buying: ResourceCount, selling_player: Player) -> Tuple[bool, Optional[ResourceCount]]:
    """Display AI trade and give options to accept or reject, only if player can afford it."""

    # Auto-decline if player cannot afford the trade
    if not all(player.resources.get(res, 0) >= amt for res, amt in buying.items()):
        clear_screen()
        display_board(controller.get_game_state())
        display_trade_offer(controller.get_game_state(), selling_player, selling, buying, player)
        print("\nYou do not have the required resources for this trade.")
        input("Press enter to continue...")
        return False, None

    original_selling, counter_offer = selling.copy(), selling.copy()

    while True:
        clear_screen()
        display_board(controller.get_game_state())
        display_trade_offer(controller.get_game_state(), selling_player, counter_offer, buying, player)

        print("\nOptions:")
        label = "Accept" if counter_offer == original_selling else "Propose Counteroffer"
        print(f"  1. {label}")
        print("  2. Decline")
        print("  3. [RESOURCE] [AMOUNT] - Modify Buying Resource")

        user_input = input("Enter option: ").strip().split()

        # Default: decline
        if not user_input:
            return False, None

        option = user_input[0]

        # Accept or propose counteroffer
        if option == "1":
            if counter_offer == original_selling:
                return True, None
            else:
                return True, counter_offer

        # Decline
        elif option == "2":
            return False, None

        # Modify buying only
        elif option == "3":
            if len(user_input) != 3:
                print("Invalid input. Usage: 3 [RESOURCE] [AMOUNT]")
                input("Press enter to continue...")
                continue

            res_str = user_input[1].upper()
            amt_str = user_input[2]

            try:
                res = Resource[res_str]
                amt = max(0, int(amt_str))
            except (KeyError, ValueError):
                print("Invalid resource or amount.")
                input("Press enter to continue...")
                continue

            counter_offer[res] = amt

        else:
            print("Invalid option.")
            input("Press enter to continue...")


def robber_discard(player: Player, controller: GameController, num_resources: int, steal: bool) -> ResourceCount:
    """Handle a robber discard by selecting and returning a resource to discard."""
    giving: ResourceCount = {res: 0 for res in Resource}

    if steal and sum(player.resources.values()) == 0:
        # Nothing to steal
        return giving

    while sum(giving.values()) < num_resources:
        remaining = num_resources - sum(giving.values())
        clear_screen()
        display_board(controller.get_game_state())
        if steal:
            print(f"\nThe robber has been moved to your tile!")
        else:
            print(f"\nThe robber has been rolled!")
        print(f"You need to give {remaining} more resource{'s' if remaining > 1 else ''}.\n")

        print("Current discard selection:")
        display_resources(giving, player.resources)

        user_input = input("Enter [RESOURCE] [AMOUNT] to give: ").strip().lower()
        try:
            res_name, amount_str = user_input.split()
            amount = int(amount_str)
            res_enum = Resource[res_name.upper()]

            # Clamp amount to amount of resources player actually has
            amount = max(0, min(amount, player.resources[res_enum]))

            # Clamp to not give more than remaining resources
            amount = giving[res_enum] + min(amount - giving[res_enum], remaining)

            giving[res_enum] = amount

        except (ValueError, KeyError):
            print("Invalid input. Format: '[RESOURCE] [AMOUNT]', e.g., 'brick 2'.")

    return giving


def place_robber(player: Player, controller: GameController) -> Tuple[HexTile, Optional[Player]]:
    """Prompt the player to select a hex tile to move the robber, and pick a player to steal from if possible."""
    error_msg = None
    while True:
        try:
            clear_screen()
            display_board(controller.get_game_state())
            print(f"\n--- {player.name}'s Robber Move ---\n")
            print("Your resources:")
            display_resources(player.resources)
            if error_msg:
                print(error_msg)

            # Prompt for hex coordinates
            coords = input("\nEnter hex coordinates (x y) to move the robber: ").strip()
            x_str, y_str = coords.split()
            x, y = int(x_str), int(y_str)

            hex_tile = controller.get_hex_tile(x, y)
            if hex_tile is None or (x, y) not in Board.HEX_COORDS:
                error_msg = f"Invalid coordinate ({x}, {y})"
                continue

            # Get players on vertices adjacent to this hex (excluding the moving player)
            adjacent_players = [
                p for p in controller.get_players_on_hex(hex_tile)
                if p != player and any(v > 0 for v in p.resources.values())
            ]

            # If there are no stealable players, return hex_tile with None
            if not adjacent_players:
                return hex_tile, None

            # Otherwise, player must pick one
            print("\nPlayers on this hex to steal from:")
            for idx, p in enumerate(adjacent_players, 1):
                print(f"  {idx}. {p.name}")

            while True:
                choice = input("Select a player to steal from: ").strip()
                if choice.isdigit():
                    choice = int(choice)
                    if 1 <= choice <= len(adjacent_players):
                        return hex_tile, adjacent_players[choice - 1]

                print("Invalid choice. Enter a number from the list.")

        except (ValueError, KeyError):
            error_msg = "Invalid input. Format: x y (e.g., 1 2)"
