from typing import List, Optional, Tuple

from GameController import GameController
from drawing.View import View, select_blocking
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from view.display import display_board, clear_screen, get_player_lead_status, display_resources, format_counter_offer


def initial_settlement_placement(player: Player, controller: GameController, view: View) -> Vertex:
    """Human selects a vertex for initial settlement placement."""
    view.display_board(player, "Select a position to build your settlement")

    vertices = controller.get_available_vertices(player, Buildable.SETTLEMENT, road_restriction=False)
    vertex: Vertex = select_blocking(view, view.canvasSelection, view.draw_selectable_vertices, vertices)

    return vertex


def initial_road_placement(player: Player, controller: GameController, view: View,
                           settlement: Optional[Vertex] = None) -> Edge:
    """Human selects an edge for initial road placement."""
    view.display_board(player, "Select a position to build your road")

    edges = controller.get_available_edges(player)
    if settlement is not None:
        # Restrict edges to be directly connected to settlement
        edges = [edge for edge in edges if settlement in edge.vertices]

    edge: Edge = select_blocking(view, view.canvasSelection, view.draw_selectable_edges, edges)

    return edge


def play_dev_card_menu(player: Player, controller: GameController) -> bool:
    """
    Show playable development cards and allow the player to play one.
    Returns True if a card was played, False otherwise.
    """
    used_dev_card = False
    playable_cards = [c.card_type for c in player.development_cards if c.playable]
    if not playable_cards:
        return used_dev_card  # Nothing to do

    while True:
        print("\nPlayable development cards:")
        for idx, card_type in enumerate(playable_cards, 1):
            print(f"  {idx}. {card_type.name.title()}")
        idx = len(playable_cards) + 1
        print(f"  {idx}. Roll Dice")

        choice = input("Choose a development card to play: ").strip()
        if choice == str(idx) or choice == "":
            break
        try:
            idx = int(choice) - 1
            card_type = playable_cards[idx]
            error_msg = controller.play_development_card(player, card_type)
            used_dev_card = True
            if error_msg:
                print(error_msg)
                input("Press enter to continue...")
            else:
                print(f"Played '{card_type.name.title()}' card.")
                input("Press enter to continue...")
            break  # Played successfully
        except (ValueError, IndexError):
            print("Invalid selection.")
            input("Press enter to continue...")
    return used_dev_card


def make_round_move(player: Player, controller: GameController, view: View):
    """Handle a full turn for a human player, including dice roll, resource display, and building actions."""
    d1, d2, total, _ = controller.roll_dice(player)
    select_blocking(view, view.turnMade, view.display_board_turn, player, (d1, d2, total))


def make_round_move_old(player: Player, controller: GameController, view: View):
    # Pre-roll development cards
    clear_screen()
    view.display_board(player, "")
    print(f"\n--- {player.name}'s turn (Pre-Roll) ---\n")
    print("Your resources:")
    display_resources(player.resources)
    used_dev_card = play_dev_card_menu(player, controller)

    # Roll dice
    d1, d2, total, error_msg = controller.roll_dice(player)

    while True:
        clear_screen()
        display_board(controller.get_game_state())
        view.display_board_turn(player, (d1, d2, total))
        print(f"\n--- {player.name}'s turn ---\n")
        print(f"Dice rolled: {d1} + {d2} = {total}")

        if error_msg:
            print(error_msg)
            error_msg = None

        # Show stats
        visible_vp, true_vp = player.calc_victory_points()
        true_vp_str = f" ({true_vp})" if visible_vp != true_vp else ""

        print(f"Longest Road: \t{player.longest_road_length} {'♕' if player.has_longest_road else ''}")
        print(f"Army Size: \t{player.army_size} {'♕' if player.has_largest_army else ''}")
        print(f"Victory Points: {visible_vp}{true_vp_str} {get_player_lead_status(player)}\n")

        # Show resources
        print("Your resources:")
        display_resources(player.resources)

        # Buildable / menu options
        buildable = controller.get_buildable_options(player)
        options = {"1": "End turn", "2": "Open Trade Menu"}
        option_number = 3

        # Only add Build / Place if player can build something
        if buildable[Buildable.ROAD] or buildable[Buildable.SETTLEMENT] or buildable[Buildable.CITY]:
            options[str(option_number)] = "Build / Place"
            build_option_index = option_number
            option_number += 1
        else:
            build_option_index = None

        # Add option to buy development card
        if buildable[Buildable.DEVELOPMENT_CARD]:
            options[str(option_number)] = "Buy Development Card"
            option_number += 1
        dc_option_index = option_number

        # Add playable development cards
        if not used_dev_card:
            playable_cards = set(c.card_type for c in player.development_cards if c.playable)
            for card_type in playable_cards:
                options[str(option_number)] = f"Use '{card_type.name.title()}' card"
                option_number += 1

        # Print menu
        print("\nOptions:")
        for key, val in options.items():
            print(f"  {key}. {val.replace('_', ' ').title()}")

        # Check victory
        if player.calc_victory_points()[1] >= Game.VICTORY_POINTS_TO_WIN:
            break

        # Get player choice
        choice = input("Enter option: ").strip()

        # End turn
        if choice == "1" or choice == "":
            break

        # Trade
        elif choice == "2":
            trading_menu(player, controller, view)

        # Build / Place interactive
        elif build_option_index is not None and choice == str(build_option_index):
            selected_buildable: Vertex | Edge = select_blocking(view, view.canvasSelection, view.draw_buildables,
                                                                buildable)

            match selected_buildable:
                case Edge():
                    controller.try_build_road(player, selected_buildable)
                case Vertex():
                    if selected_buildable.building is None:
                        controller.try_build_settlement(player, selected_buildable)
                    else:
                        controller.try_build_city(player, selected_buildable)

        # Buy development card
        elif choice.isnumeric() and int(choice) < dc_option_index:
            success, msg = controller.try_buy_development_card(player)
            print(msg)
            input("Press enter to continue...")

        # Play development card
        elif choice.isnumeric() and dc_option_index <= int(choice) and choice in options:
            card_type = DevelopmentCardType[options[choice].split()[1].strip("'").upper()]
            error_msg = controller.play_development_card(player, card_type)
            used_dev_card = True

        else:
            error_msg = "Invalid option. Try again."


def select_player_to_trade(controller: GameController, player: Player, view: View, original_offer: ResourceCount,
                           willing_players: List[Tuple[Player, Optional[ResourceCount]]]
                           ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
    """
        Let human select a trade to accept.
        Shows AI counteroffers, even if unaffordable.
        Marks trades as Affordable / Cannot Afford.
    """
    clear_screen()
    display_board(controller.get_game_state())
    view.display_board(controller.get_game_state())
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


def trading_menu(player: Player, controller: GameController, view: View):
    """Display trading menu, allow bank or player trades, auto-return after trade or cancel."""
    selling: ResourceCount = {res: 0 for res in Resource}
    buying: ResourceCount = {res: 0 for res in Resource}

    while True:
        clear_screen()
        display_board(controller.get_game_state())
        view.display_board(controller.get_game_state())
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
            deal = select_player_to_trade(controller, player, view, selling, willing_players)

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


def trade_manager(_: GameController, player: Player, view: View, selling: ResourceCount,
                  buying: ResourceCount, selling_player: Player) -> Tuple[bool, Optional[ResourceCount]]:
    """Display AI trade and give options to accept or reject, only if player can afford it."""
    trade: Tuple[bool, Optional[ResourceCount]] = select_blocking(
        view, view.tradeDecisionMade, view.display_trade_manager, player, selling, buying, selling_player
    )

    return trade


def choose_resources(
        *,
        controller: GameController,
        view: View,
        num_resources: int,
        title: str,
        resource_caps: dict[Resource, int] | None = None
) -> ResourceCount:
    """
    Generic resource selection helper.
    Allows choosing exactly `num_resources` resources, optionally capped per resource.
    """
    chosen: ResourceCount = select_blocking(view, view.resourcesPicked, view.show_resource_chooser,
                                            controller.get_all_players()[0], num_resources, title, resource_caps)
    return chosen


def robber_discard(
        player: Player,
        controller: GameController,
        view: View,
        num_resources: int,
        steal: bool
) -> ResourceCount:
    """Handle a robber discard or steal."""
    if steal and sum(player.resources.values()) == 0:
        return {res: 0 for res in Resource}

    return choose_resources(
        controller=controller,
        view=view,
        num_resources=num_resources,
        title="The robber has been moved to your tile!" if steal else "The robber has been rolled!",
        resource_caps=player.resources
    )


def year_of_plenty_selection(controller: GameController, view: View, ) -> ResourceCount:
    """Let player choose two resources from the bank."""
    return choose_resources(
        controller=controller,
        view=view,
        num_resources=2,
        title="Year of Plenty: choose any two resources from the bank.",
        resource_caps=controller.get_bank_resources()
    )


def monopoly_selection(controller: GameController, view: View) -> Resource:
    """Let player choose one resource from the other players."""
    chosen = choose_resources(
        controller=controller,
        view=view,
        num_resources=1,
        title="Monopoly: choose a resource to get from the other players.",
        resource_caps={res: 1 for res in Resource}
    )
    # Extract the single Resource enum
    return next(iter(chosen.keys()))


def place_robber(player: Player, controller: GameController, view: View) -> Tuple[HexTile, Optional[Player]]:
    """Prompt the player to select a hex tile to move the robber, and pick a player to steal from if possible."""

    # Get available hex tiles (exclude current robber tile)
    available_hexes = [tile for tile in controller.get_all_hexes() if not tile.robber]
    view.display_board(player, "Select a hex to move the robber")
    selected_hex: HexTile = select_blocking(view, view.canvasSelection, view.draw_selectable_tiles, available_hexes)

    # Check for stealable players on adjacent vertices
    adjacent_player_buildings: List[Vertex] = [
        v for v in selected_hex.vertices
        if v.owner is not None  # Has a building
        and v.owner != player  # Not the active player
        and any(v.owner.resources.values())  # Owner has at least one resource
    ]

    if not adjacent_player_buildings:
        return selected_hex, None

    view.display_board(player, "Select a player to steal from")
    selected_player_building: Vertex = select_blocking(view, view.canvasSelection, view.draw_selectable_vertices,
                                                       adjacent_player_buildings)
    selected_player = selected_player_building.owner

    return selected_hex, selected_player
