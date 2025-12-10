import random
from math import ceil
from typing import Dict

from game.Game import Game
from game.Player import Player
from game.Resources import Resource
from game.Vertex import Vertex, Buildable
from view.display import clear_screen, display_board, get_player_lead_status


def random_initial_settlement_placement(player: Player, game: Game):
    """Choose a valid random vertex for settlement."""
    available_vertices = game.get_available_vertices(player, Buildable.SETTLEMENT, road_restriction=False)

    return random.choice(available_vertices) if available_vertices else None


def random_initial_road_placement(settlement: Vertex, game: Game):
    """
    Choose a valid edge connected to the given settlement.
    Picks a random edge adjacent to the settlement where a road can be built.
    """
    available_edges = game.get_buildable_edges_for_vertex(settlement)

    if not available_edges:
        return None

    return random.choice(available_edges)


def ai_choose_build_action():
    """
    Choose a desired build action for the AI based on weighted preferences,
    ignoring whether the AI can currently afford it.
    """
    action_weights = {
        Buildable.CITY: 10,
        Buildable.SETTLEMENT: 8,
        Buildable.ROAD: 3,
        "NOTHING": 4,
    }

    weighted_actions = []

    # Include all possible actions (even if not buildable yet)
    for action in Buildable:
        weighted_actions.extend([action] * action_weights[action])

    # Always allow doing nothing
    weighted_actions.extend(["NOTHING"] * action_weights["NOTHING"])

    return random.choice(weighted_actions)


def ai_attempt_bank_trade(player: Player, game: Game, desired_build: Buildable):
    """Try one bank trade to help the AI reach the resources needed for a desired build."""

    cost = game.BUILDING_COST[desired_build]

    # Determine missing resources
    missing = {
        r: needed - player.resources.get(r, 0)
        for r, needed in cost.items()
        if player.resources.get(r, 0) < needed
    }
    if not missing:
        return None  # Nothing missing

    # Determine spare tradable resources that are NOT needed for this build
    spare = {
        r: player.resources.get(r, 0)
        for r in Resource
        if r not in cost and player.resources.get(r, 0) >= game.get_trade_rate(player, r)
    }
    if not spare:
        return None  # Nothing safe to trade away

    # Pick a missing resource to buy
    buying_resource = random.choice(list(missing.keys()))

    # Pick a spare resource to sell
    selling_resource = random.choice(list(spare.keys()))
    rate = game.get_trade_rate(player, selling_resource)

    selling = {res: 0 for res in Resource}
    buying = {res: 0 for res in Resource}

    selling[selling_resource] = rate
    buying[buying_resource] = 1

    # Attempt trade
    success = game.try_trade_with_bank(player, selling, buying)
    if not success:
        return None

    return (
        f"{player.name} trades {rate} {selling_resource.name} "
        f"for 1 {buying_resource.name} to work towards a {desired_build.name.lower()}."
    )


def ai_attempt_build(player: Player, game: Game, action: Buildable):
    """Attempt a build action and return the resulting message."""

    buildable = game.get_buildable_options(player)
    if action not in buildable or not buildable[action]:
        return f"{player.name} chooses to do nothing."

    locations = buildable[action]
    chosen_location = random.choice(locations)

    if action == Buildable.ROAD:
        success, msg = game.try_build_road(player, chosen_location)
    elif action == Buildable.SETTLEMENT:
        success, msg = game.try_build_settlement(player, chosen_location)
    elif action == Buildable.CITY:
        success, msg = game.try_build_city(player, chosen_location)
    else:
        msg = "AI attempted unknown action"

    return msg


def make_round_move_ai(player: Player, game: Game):
    """AI turn: decides what to build, trades if helpful, then attempts the build."""

    d1, d2, total = game.roll_dice()

    # 1. AI chooses what it wants to build
    chosen_action = ai_choose_build_action()

    # 2. Try a bank trade if needed
    trade_msg = None
    if chosen_action != "NOTHING":
        trade_msg = ai_attempt_bank_trade(player, game, chosen_action)

    # 3. Attempt the build
    build_msg = ai_attempt_build(player, game, chosen_action)

    # 4. Display results
    clear_screen()
    display_board(game)

    print(f"\n--- {player.name}'s turn (AI) ---\n")
    print(f"{player.name} rolled {d1} + {d2} = {total}")

    print(f"Longest Road: \t{player.longest_road_length} {'♕' if player.has_longest_road else ''}")
    print(f"Victory Points: {player.calc_victory_points()} {get_player_lead_status(player)}\n")

    if trade_msg:
        print(trade_msg)

    print(build_msg)

    input("\nPress enter to continue...")


def trade_manager_ai(player: Player, selling: Dict[Resource, int], buying: Dict[Resource, int],
                     selling_player: Player, round_num: int) -> bool:
    """
    Basic AI logic for accepting or rejecting a trade.
    - Player must have the required resources (buying)
    - AI becomes pickier as rounds progress
    """
    total_rounds = 20  # Estimated total rounds in the game
    max_ratio = 4      # Maximum resources AI will ask for 1 resource late game

    # 1. Check if AI has the resources it is being asked to give
    for resource, amount in buying.items():
        if player.resources.get(resource, 0) < amount:
            return False  # Cannot trade what you don't have

    # 2. Calculate AI's required ratio for this round
    required_ratio = ceil(1 + (round_num - 1) / total_rounds * (max_ratio - 1))

    # 3. Calculate totals
    total_selling = sum(selling.values())  # What the AI would get
    total_buying = sum(buying.values())    # What AI would give

    # 4. Accept trade if total offered meets or exceeds AI's required ratio
    return total_selling >= required_ratio * total_buying
