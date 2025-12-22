import random
from math import ceil
from typing import Optional, List, Tuple

from GameController import GameController
from drawing.View import View
from drawing.constants import SHOW_AI_BUILT_LOCATIONS
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from view.display import resource_dict_to_str

TOTAL_ROUNDS = 20  # Estimated total rounds in the game
MAX_RATIO = 4  # Maximum resources AI will ask for 1 resource late game
HUMAN_BIAS_WEIGHT, AI_BIAS_WEIGHT = 1.2, 1.0

ACCEPT_PROBABILITY_BY_OVERCOST = {  # Counter trades probabilities
    0: 1.0,
    1: 0.4,
    2: 0.1,
}


def random_initial_settlement_placement(player: Player, controller: GameController, view: View) -> Optional[Vertex]:
    """Choose a valid random vertex for settlement."""
    available_vertices = controller.get_available_vertices(player, Buildable.SETTLEMENT, road_restriction=False)
    view.display_board()
    view.draw_selectable_vertices(available_vertices, disable_interactivity=True)
    view.display_board_ai(player, "Select a position to build your settlement")

    return random.choice(available_vertices) if available_vertices else None


def random_initial_road_placement(player: Player, controller: GameController, view: View,
                                  settlement: Optional[Vertex] = None) -> Optional[Edge]:
    """
    Choose a valid edge connected to the given settlement.
    Picks a random edge adjacent to the settlement where a road can be built.
    """
    if settlement is None:
        available_edges = controller.get_available_edges(player)
    else:
        available_edges = controller.get_buildable_edges_for_vertex(settlement)

    if not available_edges:
        return None

    view.display_board()
    view.draw_selectable_edges(available_edges, disable_interactivity=True)
    view.display_board_ai(player, "Select a position to build your road")

    return random.choice(available_edges)


def get_required_trade_ratio(round_num: int) -> int:
    """Return the AI's required trade ratio for the current round."""
    return ceil(1 + (round_num - 1) / TOTAL_ROUNDS * (MAX_RATIO - 1))


def ai_choose_build_action() -> Buildable | str:
    """
    Choose a desired build action for the AI based on weighted preferences,
    ignoring whether the AI can currently afford it.
    """
    action_weights = {
        Buildable.CITY: 10,
        Buildable.SETTLEMENT: 8,
        Buildable.DEVELOPMENT_CARD: 6,
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


def pick_random_resources(resources: ResourceCount, num_resources: int) -> Optional[ResourceCount]:
    """Randomly pick num_resources resource units from the given resource dict."""
    total = sum(resources.values())
    if total < num_resources:
        return None

    pool = [
        resource
        for resource, count in resources.items()
        for _ in range(count)
    ]

    chosen = random.sample(pool, num_resources)

    result: ResourceCount = {}
    for resource in chosen:
        result[resource] = result.get(resource, 0) + 1

    return result


def resource_cost(resources: ResourceCount) -> int:
    return sum(resources.values())


def player_trade_weight(player: Player) -> float:
    """Return selection weight for a player in trade decisions."""
    return HUMAN_BIAS_WEIGHT if player.is_human else AI_BIAS_WEIGHT


def accept_probability(over_cost: int) -> float:
    """Probability of accepting a counteroffer exceeding estimated cost."""
    if over_cost <= 0:
        return 1.0
    return ACCEPT_PROBABILITY_BY_OVERCOST.get(over_cost, 0.0)


def weighted_pick(players: List[Player]) -> Player:
    weights = [player_trade_weight(p) for p in players]
    return random.choices(players, weights=weights, k=1)[0]


def pick_trade_partner(
        available_players: List[Tuple[Player, Optional[ResourceCount]]],
        estimated_cost: int
) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
    """Decide which trade to follow through with. Returns (Player, counteroffer) or None."""

    if not available_players:
        return None

    # Prefer original trades
    originals = [(p, c) for (p, c) in available_players if c is None]
    if originals:
        players = [p for (p, _) in originals]
        chosen = weighted_pick(players)
        return chosen, None

    # Evaluate Counteroffers
    counters_with_cost = [
        (p, c, resource_cost(c))
        for (p, c) in available_players
        if c is not None
    ]

    if not counters_with_cost:
        return None

    # Find minimum cost
    min_cost = min(cost for (_, _, cost) in counters_with_cost)
    cheapest = [(p, c, cost) for (p, c, cost) in counters_with_cost if cost == min_cost]

    # Acceptance probability
    over_cost = min_cost - estimated_cost
    if random.random() > accept_probability(over_cost):
        return None

    # Bias toward human if tied
    players = [p for (p, _, _) in cheapest]
    chosen_player = weighted_pick(players)

    # Retrieve that player's counteroffer
    for p, c, _ in cheapest:
        if p == chosen_player:
            return p, c

    return None


def ai_attempt_trade(player: Player, controller: GameController, desired_build: Buildable, round_num: int):
    """Try one bank trade to help the AI reach the resources needed for a desired build."""
    cost = Game.BUILDING_COST[desired_build]

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
        if r not in cost and player.resources.get(r, 0) >= controller.get_trade_rate(player, r)
    }
    if not spare:
        return None  # Nothing safe to trade away

    # Pick a missing resource to buy
    buying_resource = random.choice(list(missing.keys()))

    # Pick a spare resource to sell
    selling_resource = random.choice(list(spare.keys()))
    bank_rate = controller.get_trade_rate(player, selling_resource)

    ai_buying_rate = get_required_trade_ratio(round_num)
    buying = {res: 0 for res in Resource}
    buying[buying_resource] = 1

    # Case 1: Prefer player trade
    if ai_buying_rate < bank_rate:
        selling = pick_random_resources(spare, ai_buying_rate)
        if selling is None:
            # Not enough resources to offer a player trade
            return None

        willing_players = controller.trade_with_players(player, selling, buying)
        deal = pick_trade_partner(willing_players, ai_buying_rate)
        if deal is not None:
            buying_player, counter = deal

            if counter is not None:
                selling = counter  # AI accepted counteroffer

            # Actually perform trade
            controller.trade_between_players(player, selling, buying_player, buying)
            return (
                f"{player.name} trades {resource_dict_to_str(selling)} with "
                f"{buying_player.name} for {resource_dict_to_str(buying)} "
                f"to work towards a {desired_build.name.replace('_', ' ').lower()}."
            )
        # If no player accepts, fall through to bank trade

    # Case 2: Bank trade
    selling = {res: 0 for res in Resource}
    selling[selling_resource] = bank_rate

    success = controller.try_trade_with_bank(player, selling, buying)
    if not success:
        return None

    return (
        f"{player.name} trades {resource_dict_to_str(selling)} with the bank "
        f"for {resource_dict_to_str(buying)} to work towards a {desired_build.name.replace('_', ' ').lower()}."
    )


def ai_attempt_build(player: Player, controller: GameController, action: Buildable):
    """Attempt a build action and return the resulting message."""

    buildable = controller.get_buildable_options(player)
    if action not in buildable or not buildable[action]:
        return f"{player.name} chooses to do nothing."

    if action == Buildable.ROAD:
        success, msg = controller.try_build_road(player, random.choice(buildable[action]))
    elif action == Buildable.SETTLEMENT:
        success, msg = controller.try_build_settlement(player, random.choice(buildable[action]))
    elif action == Buildable.CITY:
        success, msg = controller.try_build_city(player, random.choice(buildable[action]))
    elif action == Buildable.DEVELOPMENT_CARD:
        success, _ = controller.try_buy_development_card(player)
        msg = f"{player.name} bought a development card."
    else:
        msg = "AI attempted unknown action"

    if not SHOW_AI_BUILT_LOCATIONS:
        msg = msg.partition("built")[0] + f"built by {player.name}"

    return msg


def make_round_move_ai(player: Player, controller: GameController, view: View):
    """AI turn: decides what to build, trades if helpful, then attempts the build."""
    used_dev_card = False
    card_msg = ""
    playable_cards = [c.card_type for c in player.development_cards if c.playable]
    if playable_cards and random.random() < 0.3:  # Chance to play a card pre-roll
        card: DevelopmentCardType = random.choice(playable_cards)
        card_msg = controller.play_development_card(player, card) + " (Pre-roll)"
        used_dev_card = True

    d1, d2, total, roll_msg = controller.roll_dice(player)

    # 1. AI chooses what it wants to build
    chosen_action = ai_choose_build_action()

    # 2. Try a bank trade if needed
    trade_msg = None
    if chosen_action != "NOTHING":
        trade_msg = ai_attempt_trade(player, controller, chosen_action, controller.round_num)

    # 3. Attempt the build
    build_msg = ai_attempt_build(player, controller, chosen_action)

    # 4. Use playable development card if AI has one
    if playable_cards and not used_dev_card:
        card: DevelopmentCardType = random.choice(playable_cards)
        card_msg = controller.play_development_card(player, card) + " (Post-roll)"

    # 5. Display results
    msg = "\n".join(msg for msg in [trade_msg, build_msg, card_msg, roll_msg] if msg)
    view.display_board_turn_ai(player, (d1, d2, total), msg)


def trade_manager_ai(player: Player, selling: ResourceCount, buying: ResourceCount,
                     round_num: int) -> Tuple[bool, Optional[ResourceCount]]:
    """
    Basic AI logic for accepting or rejecting a trade.
    - Player must have the required resources (buying)
    - AI becomes pickier as rounds progress
    """
    # 1. Check if AI has the resources it is being asked to give
    for resource, amount in buying.items():
        if player.resources.get(resource, 0) < amount:
            return False, None  # Cannot trade what you don't have

    # 2. AI expected ratio
    required_ratio = get_required_trade_ratio(round_num)

    # 3. Totals
    total_selling = sum(selling.values())  # What AI would get
    total_buying = sum(buying.values())  # What AI would give

    over_cost = total_selling - required_ratio * total_buying
    over_cost_int = int(abs(over_cost))

    # 4. Decide accept or counter probabilistically
    prob = ACCEPT_PROBABILITY_BY_OVERCOST.get(over_cost_int, 0.0)
    if random.random() < prob:
        return True, None  # Accept

    # 5. Generate simple counteroffer if not accepting
    if total_selling < required_ratio * total_buying:
        missing = required_ratio * total_buying - total_selling
        # Pick one offered resource to increase
        resource_to_increase = max(selling, key=lambda r: selling[r])
        counter_selling = selling.copy()
        counter_selling[resource_to_increase] += int(missing)
        return True, counter_selling

    # Otherwise, reject
    return False, None


def robber_discard_ai(player: Player, _: GameController, __: View, num_resources: int, ___: bool) -> ResourceCount:
    """Handle a robber discard by selecting and returning a resource to discard."""
    return pick_random_resources(player.resources, num_resources)


def place_robber_ai(player: Player, controller: GameController, _: View) -> Tuple[HexTile, Optional[Player]]:
    """AI chooses a hex with players and randomly steals from one of them."""
    # Exclude the hex that already has the robber
    valid_hexes = [
        hex_tile for hex_tile in controller.get_all_hexes()
        if not hex_tile.robber
    ]

    # Filter hexes that have at least one stealable opponent
    stealable_hexes = [
        hex_tile for hex_tile in valid_hexes
        if any(
            p != player and any(v > 0 for v in p.resources.values())
            for p in controller.get_players_on_hex(hex_tile)
        )
    ]

    if stealable_hexes:
        # Pick a random hex where stealing is possible
        hex_tile = random.choice(stealable_hexes)

        stealable_players = [
            p for p in controller.get_players_on_hex(hex_tile)
            if p != player and any(v > 0 for v in p.resources.values())
        ]

        target_player = random.choice(stealable_players)
        return hex_tile, target_player

    # Otherwise, move robber to any other valid hex (no stealing)
    hex_tile = random.choice(valid_hexes)
    return hex_tile, None


def year_of_plenty_selection_ai(controller: GameController) -> ResourceCount:
    """Randomly pick two resources from the bank."""
    return pick_random_resources(controller.get_bank_resources(), 2)


def monopoly_selection_ai(controller: GameController) -> Resource:
    """Randomly pick two resources from the bank."""
    res_dict = pick_random_resources(controller.get_bank_resources(), 1)
    # Extract the single key
    return next(iter(res_dict.keys()))
