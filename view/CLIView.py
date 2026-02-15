from typing import List, Optional, Tuple, Dict

from GameController import GameController
from game.Board import Board
from game.Edge import EdgeDirection, Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import VertexDirection, Vertex
from view.View import View
from view.display_utils import display_board, clear_screen, get_player_lead_status, display_resources, \
    display_trade_offer, format_counter_offer, display_results


class CLIView(View):
    def __init__(self, controller: GameController):
        self.controller = controller

    def display_board(self, player: Optional[Player] = None, msg: Optional[str] = None) -> None:
        """Display the game board with optional message."""
        clear_screen()
        display_board(self.controller.get_game_state())
        if msg:
            print(f"\n{msg}")
        if player:
            print(f"\n--- {player.name}'s turn ---")
            print(f"Resources:")
            display_resources(player.resources)

    def display_board_ai(self, player: Player, msg: str) -> None:
        """Display board for AI turn."""
        self.display_board(player, msg)

    def display_board_turn(self, player: Player, dice_info: Tuple[int, int, int],
                           played_dev_card: bool = False) -> None:
        """Handle a full turn for a human player, including dice roll, resource display, and building actions."""
        d1, d2, total = dice_info
        error_msg = None

        while True:
            clear_screen()
            display_board(self.controller.get_game_state())
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
            buildable = self.controller.get_buildable_options(player)
            option_number = 3

            # Add buildable options
            for action_type in Buildable:
                if buildable[action_type]:
                    action = "Buy " if action_type == Buildable.DEVELOPMENT_CARD else "Build "
                    options[str(option_number)] = action + action_type.name.replace("_", " ").capitalize()
                    option_number += 1
            dc_option_index = option_number

            # Add development card options
            if not played_dev_card:
                playable_cards = []
                for c in player.development_cards:
                    if c.playable and c.card_type not in playable_cards:
                        playable_cards.append(c.card_type)
                for card_type in playable_cards:
                    options[str(option_number)] = f"Use '{card_type.name.title()}' card"

            # Print options
            print("\nOptions:")
            for key, val in options.items():
                print(f"  {key}. {val.replace('_', ' ').title()}")

            if player.calc_victory_points()[1] >= Game.VICTORY_POINTS_TO_WIN:
                break

            choice = input("Enter option: ").strip()

            if choice == "1" or choice == "":
                # End turn
                break

            if choice == "2":
                self.trading_menu(player)

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
                    success, msg = self.controller.try_build_road(player, selected)
                elif action_type == Buildable.SETTLEMENT:
                    success, msg = self.controller.try_build_settlement(player, selected)
                elif action_type == Buildable.CITY:
                    success, msg = self.controller.try_build_city(player, selected)
                elif action_type == Buildable.DEVELOPMENT_CARD:
                    success, msg = self.controller.try_buy_development_card(player)
                else:
                    success, msg = False, "Unknown build type"

                print(msg)
                input("Press enter to continue...")
            elif choice.isnumeric() and dc_option_index <= int(choice) and choice in options:
                # Play development card
                card_type = DevelopmentCardType[options[choice].split()[1].strip("'").upper()]
                error_msg = self.controller.play_development_card(player, card_type)
                played_dev_card = True

            else:
                error_msg = "Invalid option. Try again."

    def display_board_turn_ai(self, player: Player, dice_info: Tuple[int, int, int], msg: str) -> None:
        """Display board for AI turn."""
        d1, d2, total = dice_info
        clear_screen()
        display_board(self.controller.get_game_state())
        print(f"\n--- {player.name}'s turn (AI) ---")
        print(f"Dice rolled: {d1} + {d2} = {total}")
        print(msg)
        input("\nPress enter to continue...")

    def draw_selectable_vertices(self, vertices: List[Vertex], disable_interactivity: bool = False) -> Vertex:
        """Prompt the user to enter a vertex for a settlement (initial placement)."""
        if disable_interactivity and vertices:
            return vertices[0]

        error_msg = None
        while True:
            try:
                clear_screen()
                display_board(self.controller.get_game_state())
                print(f"\n--- Select Vertex ---\n")
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
                vertex = self.controller.get_vertex(x, y, direction)

                # Check if vertex is in the list of available vertices
                if vertex not in vertices:
                    error_msg = "Invalid vertex selection. Choose from available vertices."
                    continue

                return vertex

            except (ValueError, KeyError):
                error_msg = "Invalid input. Format: x y DIRECTION (e.g. 0 2 TOP_RIGHT)"

    def draw_selectable_edges(self, edges: List[Edge], disable_interactivity: bool = False) -> Edge:
        """Prompt the user to enter an edge for a road (initial placement)."""
        if disable_interactivity and edges:
            return edges[0]

        error_msg = None
        while True:
            try:
                clear_screen()
                display_board(self.controller.get_game_state())
                print(f"\n--- Select Edge ---\n")
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
                edge = self.controller.get_edge(x, y, direction)

                # Check if edge is in the list of available edges
                if edge not in edges:
                    error_msg = "Invalid edge selection. Choose from available edges."
                    continue

                return edge

            except (ValueError, KeyError):
                error_msg = "Invalid input. Format: x y DIRECTION (e.g. 0 2 EAST)"

    def draw_selectable_tiles(self, tiles: List[HexTile]) -> HexTile:
        """Prompt user to select a hex tile (for robber placement)."""
        error_msg = None
        while True:
            try:
                clear_screen()
                display_board(self.controller.get_game_state())
                print(f"\n--- Select Hex Tile ---\n")
                if error_msg:
                    print(error_msg)

                print("Available tiles:")
                for idx, tile in enumerate(tiles, 1):
                    print(f"  {idx}. ({tile.q}, {tile.r}) - {tile.resource.name if tile.resource else 'Desert'}")

                coords = input("Enter hex coordinates (x y): ").strip()
                x_str, y_str = coords.split()
                x, y = int(x_str), int(y_str)

                hex_tile = self.controller.get_hex_tile(x, y)
                if hex_tile is None or hex_tile not in tiles:
                    error_msg = f"Invalid tile selection. Choose from available tiles."
                    continue

                return hex_tile

            except (ValueError, KeyError):
                error_msg = "Invalid input. Format: x y (e.g., 1 2)"

    def draw_buildables(self, buildables: Dict) -> None:
        """Display buildable options to the user."""
        print("\nBuildable Options:")
        for action_type, locations in buildables.items():
            if locations:
                print(f"\n{action_type.name.replace('_', ' ').title()}:")
                for idx, loc in enumerate(locations, 1):
                    print(f"  {idx}. ({loc.get_pos()})")

    def show_resource_chooser(self, player: Player, num_resources: int, title: str,
                              resource_caps: Optional[ResourceCount] = None) -> ResourceCount:
        """Generic resource selection helper."""
        if resource_caps is None:
            resource_caps = player.resources

        chosen: ResourceCount = {res: 0 for res in Resource}

        while sum(chosen.values()) < num_resources:
            remaining = num_resources - sum(chosen.values())
            clear_screen()
            display_board(self.controller.get_game_state())

            print(f"\n{title}")
            print(f"You need to select {remaining} more resource{'s' if remaining > 1 else ''}.\n")

            print("Current selection:")
            display_resources(chosen, resource_caps)

            user_input = input("Enter [RESOURCE] [AMOUNT]: ").strip().lower()

            try:
                res_name, amount_str = user_input.split()
                amount = int(amount_str)
                res = Resource[res_name.upper()]

                max_allowed = resource_caps.get(res, 0)
                current = chosen.get(res, 0)

                # Clamp
                amount = max(0, min(amount, max_allowed))
                amount = current + min(amount - current, remaining)

                chosen[res] = amount

            except (ValueError, KeyError):
                print("Invalid input. Format: '[RESOURCE] [AMOUNT]'")
                input("Press enter to continue...")

        return chosen

    def display_trade_manager(self, player: Player, selling: ResourceCount,
                              buying: ResourceCount, selling_player: Player) -> Tuple[bool, Optional[ResourceCount]]:
        """Display AI trade and give options to accept or reject."""
        # Auto-decline if player cannot afford the trade
        if not all(player.resources.get(res, 0) >= amt for res, amt in buying.items()):
            clear_screen()
            display_board(self.controller.get_game_state())
            display_trade_offer(self.controller.get_game_state(), selling_player, selling, buying, player)
            print("\nYou do not have the required resources for this trade.")
            input("Press enter to continue...")
            return False, None

        original_selling, counter_offer = selling.copy(), selling.copy()

        while True:
            clear_screen()
            display_board(self.controller.get_game_state())
            display_trade_offer(self.controller.get_game_state(), selling_player, counter_offer, buying, player)

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
                except (ValueError, KeyError):
                    print("Invalid resource or amount.")
                    input("Press enter to continue...")
                    continue

                counter_offer[res] = amt

            else:
                print("Invalid option.")
                input("Press enter to continue...")

    def pre_roll(self, player: Player) -> DevelopmentCardType | bool:
        """Show playable development cards and allow player to play one pre-roll."""
        playable_cards = [c.card_type for c in player.development_cards if c.playable]
        if not playable_cards:
            return False  # No cards to play

        while True:
            clear_screen()
            display_board(self.controller.get_game_state())
            print(f"\n--- {player.name}'s turn (Pre-Roll) ---\n")
            print("Your resources:")
            display_resources(player.resources)

            print("\nPlayable development cards:")
            for idx, card_type in enumerate(playable_cards, 1):
                print(f"  {idx}. {card_type.name.title()}")
            idx = len(playable_cards) + 1
            print(f"  {idx}. Roll Dice")

            choice = input("Choose a development card to play: ").strip()
            if choice == str(idx) or choice == "":
                return False  # Player chose to roll dice

            try:
                idx = int(choice) - 1
                card_type = playable_cards[idx]
                error_msg = self.controller.play_development_card(player, card_type)
                if error_msg:
                    print(error_msg)
                    input("Press enter to continue...")
                else:
                    print(f"Played '{card_type.name.title()}' card.")
                    input("Press enter to continue...")
                    return card_type
            except (ValueError, IndexError):
                print("Invalid selection.")
                input("Press enter to continue...")

    def display_results(self) -> None:
        """Display game results."""
        display_results(self.controller.get_game_state())

    def display_start_screen(self) -> bool:
        """Display game start screen and get player count."""
        clear_screen()
        print("=" * 50)
        print("WELCOME TO CATAN")
        print("=" * 50)

        print("\nInstructions:")
        print("- Each player takes turns rolling dice and collecting resources")
        print("- Build settlements, cities, and roads to expand your territory")
        print("- Trade resources with other players or the bank")
        print("- First to reach 10 victory points wins!")

        print("\nGame Setup:")

        while True:
            user_input = input("\nPlay without human players? (y/n, or press enter to cancel): ").strip().lower()
            if user_input == "":
                return True
            if user_input in ("y", "yes"):
                print("\nSimulation mode enabled (no human players)...")
                return False
            if user_input in ("n", "no"):
                return True
            print("Invalid input. Enter 'y' or 'n'.")

    # Additional helper methods for initial placement (not part of View interface but needed for CLI)
    def initial_settlement_placement(self, player: Player) -> Vertex:
        """Prompt the user to enter a vertex for a settlement (initial placement)."""
        return self.draw_selectable_vertices(
            self.controller.get_available_vertices(player, Buildable.SETTLEMENT, road_restriction=False)
        )

    def initial_road_placement(self, player: Player, settlement: Optional[Vertex] = None) -> Edge:
        """Prompt the user to enter an edge for a road (initial placement)."""
        edges = self.controller.get_available_edges(player)
        if settlement is not None:
            # Restrict edges to be directly connected to settlement
            edges = [edge for edge in edges if settlement in edge.vertices]

        return self.draw_selectable_edges(edges)

    def place_robber(self, player: Player) -> Tuple[HexTile, Optional[Player]]:
        """Prompt the player to select a hex tile to move the robber, and pick a player to steal from if possible."""
        # Get available tiles (excluding current robber position)
        available_tiles = [tile for tile in self.controller.get_all_hexes()
                           if not tile.robber and tile.resource is not None]

        hex_tile = self.draw_selectable_tiles(available_tiles)

        # Get players on vertices adjacent to this hex (excluding the moving player)
        adjacent_players = [
            p for p in self.controller.get_players_on_hex(hex_tile)
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

    def trading_menu(self, player: Player):
        """Display trading menu, allow bank or player trades."""
        selling: ResourceCount = {res: 0 for res in Resource}
        buying: ResourceCount = {res: 0 for res in Resource}

        while True:
            clear_screen()
            display_board(self.controller.get_game_state())
            print(f"\n--- {player.name}'s Trading Menu ---\n")

            # Print current trading hand
            print("You give:")
            display_resources(selling, player.resources)

            print("\nYou receive:")
            display_resources(buying)

            trade_incomplete = all(v == 0 for v in selling.values()) or all(v == 0 for v in buying.values())
            valid_bank_trade = (not trade_incomplete and
                                self.controller.try_trade_with_bank(player, selling, buying, use_resources=False))
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
                    selling[res] = min(amt, player.resources.get(res, 0))
                    buying[res] = 0
                else:
                    selling[res] = 0
                    buying[res] = amt

            elif option == "3":
                # Trade with bank using the current selling and buying dicts
                success = self.controller.try_trade_with_bank(player, selling, buying)
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
                willing_players = self.controller.trade_with_players(player, selling, buying)
                deal = self.select_player_to_trade(player, selling, willing_players)

                if deal is not None:
                    buying_player, counter = deal
                    if counter is not None:
                        selling = counter  # Player accepted counteroffer

                    self.controller.trade_between_players(player, selling, buying_player, buying)
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

    def select_player_to_trade(self, player: Player, original_offer: ResourceCount,
                               willing_players: List[Tuple[Player, Optional[ResourceCount]]]
                               ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        """Let human select a trade to accept."""
        clear_screen()
        display_board(self.controller.get_game_state())
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
