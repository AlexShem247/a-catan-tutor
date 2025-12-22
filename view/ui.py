from typing import List, Optional, Tuple

from GameController import GameController
from drawing.View import View, select_blocking
from game.Edge import Edge
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex


def get_game_type(view: View) -> bool:
    human_player_one: bool = select_blocking(view, view.startGame, view.display_start_screen)
    return human_player_one


def initial_settlement_placement(player: Player, controller: GameController, view: View) -> Vertex:
    """Human selects a vertex for initial settlement placement."""
    view.display_board(player, "Select a position to build your settlement")

    vertices = controller.get_available_vertices(player, Buildable.SETTLEMENT, road_restriction=False)
    vertex: Vertex = select_blocking(view, view.canvasSelection, view.draw_selectable_vertices, vertices)
    view.display_board()

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


def make_round_move(player: Player, controller: GameController, view: View):
    """Handle a full turn for a human player, including dice roll, resource display, and building actions."""
    playable_cards = [card for card in player.development_cards if card.playable]
    played_dev_card = False
    if playable_cards:
        # Player can play card before rolling dice
        played_card: DevelopmentCardType | bool = select_blocking(view, view.turnMade, view.pre_roll, player)
        played_dev_card = played_card is not False

    d1, d2, total, _ = controller.roll_dice(player)
    select_blocking(view, view.turnMade, view.display_board_turn, player, (d1, d2, total), played_dev_card)


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
