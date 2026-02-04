from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Tuple

from game.Board import Board
from game.Edge import EdgeDirection, Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import DevelopmentCardType
from game.Resources import Resource, ResourceCount, HexType
from game.Vertex import VertexDirection, Building, Vertex, Port


def rgb_to_ansi(r: int, g: int, b: int) -> str:
    """Convert (R,G,B) to 24-bit ANSI escape sequence."""
    return f"\033[38;2;{r};{g};{b}m"  # noqa: E702


class Color(Enum):
    GREY = (140, 140, 140)
    GOLD = (220, 170, 25)
    LIME_GREEN = (130, 170, 15)
    DARK_GREEN = (20, 110, 20)
    RED_ORANGE = (180, 35, 35)
    BEIGE = (200, 170, 120)
    BROWN = (140, 70, 25)
    WHITE = (225, 225, 225)

    BLUE = (0, 0, 255)
    RED = (255, 0, 0)
    GREEN = (0, 230, 0)
    YELLOW = (240, 225, 0)

    RESET = "reset"

    def apply(self, text: str) -> str:
        """Return the text wrapped in this RGB colour."""
        if self is Color.RESET:
            return text

        r, g, b = self.value
        ansi = rgb_to_ansi(r, g, b)
        return f"{ansi}{text}\033[0m"

    def ansi(self) -> str:
        """Return ANSI code for this colour."""
        if self is Color.RESET:
            return "\033[0m"
        r, g, b = self.value
        return rgb_to_ansi(r, g, b)


def colorise(text: str, color: Color, bold: bool = False, underline: bool = False) -> str:
    if color is Color.RESET:
        return text

    if hasattr(color, "value"):
        r, g, b = color.value
    else:
        r, g, b = color

    # Build ANSI prefix
    prefix_codes = []
    if bold:
        prefix_codes.append("1")  # bold
    if underline:
        prefix_codes.append("4")  # underline

    # RGB foreground
    prefix_codes.append(f"38;2;{r};{g};{b}")  # noqa: E702
    ansi_prefix = f"\033[{';'.join(prefix_codes)}m"

    return f"{ansi_prefix}{text}\033[0m"


def brighten(color: Color, value: int = 50):
    r, g, b = color.value
    return min(r + value, 255), min(g + value, 255), min(b + value, 255)


NO_EDGE = object()
ROBBER_SYM = colorise("R", Color.WHITE, bold=True)


def get_player_color(player: Player) -> Color:
    return [Color.BLUE, Color.RED, Color.GREEN, Color.YELLOW][player.player_number.value]


def clear_screen():
    print("\033[H\033[J", end="")


class Renderable(ABC):
    robber = False

    @abstractmethod
    def render(self) -> str:
        """Return a string representation suitable for display."""
        pass


class Empty(Renderable):
    def render(self) -> str:
        if self.robber:
            return "  " + ROBBER_SYM + "  "
        return "     "


class DisplayHexTile(Renderable):
    COLOR_MAP = {
        HexType.FOREST: Color.DARK_GREEN,
        HexType.HILLS: Color.RED_ORANGE,
        HexType.PASTURE: Color.LIME_GREEN,
        HexType.FIELDS: Color.GOLD,
        HexType.MOUNTAINS: Color.GREY,
        HexType.DESERT: Color.BEIGE,
    }

    HEX_LABEL = {
        HexType.FOREST: "FOR",
        HexType.HILLS: "HIL",
        HexType.PASTURE: "PAS",
        HexType.FIELDS: "FLD",
        HexType.MOUNTAINS: "MTN",
    }

    def __init__(self, hex_tile: HexTile):
        self.hex_tile = hex_tile

    def render(self) -> str:
        length = 4 - len(str(self.hex_tile.production_number))
        label = "DESRT" if self.hex_tile.type == HexType.DESERT \
            else f"{self.HEX_LABEL[self.hex_tile.type][:length]}-{self.hex_tile.production_number}"
        color = self.COLOR_MAP.get(self.hex_tile.type)
        return colorise(label, color, underline=True) if color else label


class DisplayCoordinate(Renderable):
    COLOR_MAP = DisplayHexTile.COLOR_MAP

    def __init__(self, hex_tile: HexTile):
        self.hex_tile = hex_tile

    def render(self) -> str:
        label = f"{self.hex_tile.q:2},{self.hex_tile.r:2}"
        color = self.COLOR_MAP.get(self.hex_tile.type)
        return colorise(label, color) if color else label


class DisplayVertex(Renderable):
    COLOR_MAP = {
        Port.WOOD: brighten(Color.DARK_GREEN),
        Port.BRICK: brighten(Color.RED_ORANGE),
        Port.SHEEP: brighten(Color.LIME_GREEN),
        Port.WHEAT: brighten(Color.GOLD),
        Port.ORE: Color.GREY,
        Port.THREE_TO_ONE: Color.BROWN,
    }

    def __init__(self, vertex: Vertex):
        self.vertex = vertex

    def render(self) -> str:
        if not self.vertex.owner:
            if self.vertex.port is not None:
                if self.vertex.port == Port.THREE_TO_ONE:
                    return colorise("3?:1?", self.COLOR_MAP[Port.THREE_TO_ONE])
                return colorise(f"2{self.vertex.port.name[0]}:1?", self.COLOR_MAP[self.vertex.port])
            return "EMPTY"

        owner_abbr = self.vertex.owner.name[:2].rjust(2)
        building_char = self.vertex.building.name[0] if self.vertex.building else "?"
        text = f"{owner_abbr}({building_char})"
        color = get_player_color(self.vertex.owner)
        bold = self.vertex.building == Building.CITY

        return colorise(text, color, bold=bold)


class DisplayEdge(Renderable):
    def __init__(self, edge: Edge):
        self.edge = edge

    def render(self) -> str:
        text = "  |  "
        if self.edge.owner:
            return colorise(text, get_player_color(self.edge.owner))
        return text


class DiagonalEdges(Renderable):
    left: Player | None | object = NO_EDGE
    right: Player | None | object = NO_EDGE

    def __init__(self, flipped: bool = False):
        self.flipped = flipped

    def render(self) -> str:
        left_symbol, right_symbol = ("╱", "╲") if self.flipped else ("╲", "╱")

        def render_edge(edge_owner, symbol):
            if edge_owner is NO_EDGE:
                return " "

            text = symbol if edge_owner is None else symbol
            if edge_owner is not None:
                return colorise(text, get_player_color(edge_owner))
            return text

        robber_str = ROBBER_SYM if self.robber else " "
        return f"{render_edge(self.left, left_symbol)} {robber_str} {render_edge(self.right, right_symbol)}"


def display_board(game: Game) -> None:
    display_array: List[List[Renderable]] = [[Empty() for _ in range(11)] for _ in range(17)]

    def init_diagonal(row_i: int, col_i: int, side: str, flipped: bool, owner: Player | None):
        cell = display_array[row_i][col_i]
        if not isinstance(cell, DiagonalEdges):
            cell = DiagonalEdges(flipped=flipped)
            display_array[row_i][col_i] = cell
        setattr(cell, side, owner)

    for r in range(Board.MIN_R, Board.MAX_R + 1):
        for i, h in enumerate(game.get_row_hexes(r)):
            row = 3 * r + 2
            col = 1 + abs(r - 2) + 2 * i
            display_array[row + int(r > Board.MAX_R // 2)][col] = DisplayHexTile(h)
            display_array[row - 1 + int(r > Board.MAX_R // 2)][col] = DisplayCoordinate(h)
            display_array[row][col - 1] = DisplayEdge(game.get_edge(h.q, h.r, EdgeDirection.WEST))
            display_array[row][col + 1] = DisplayEdge(game.get_edge(h.q, h.r, EdgeDirection.EAST))

            # Places for vertices in display array (dR, dC)
            vertex_pos: (int, int) = [(-2, 0), (-1, 1), (1, 1), (2, 0), (1, -1), (-1, -1)]
            for vDir, (dR, dC) in enumerate(vertex_pos):
                r_idx = row + dR
                c_idx = col + dC
                # Only set if inside array bounds
                if 0 <= r_idx < len(display_array) and 0 <= c_idx < len(display_array[0]):
                    display_array[r_idx][c_idx] = DisplayVertex(game.get_vertex(h.q, h.r, VertexDirection(vDir)))

                # Top diagonals
                if vDir == VertexDirection.TOP and r <= Board.MAX_R // 2:
                    init_diagonal(r_idx, c_idx + 1, "left", flipped=False,
                                  owner=game.get_edge(h.q, h.r, EdgeDirection.NORTH_EAST).owner)
                    init_diagonal(r_idx, c_idx - 1, "right", flipped=False,
                                  owner=game.get_edge(h.q, h.r, EdgeDirection.NORTH_WEST).owner)

                # Bottom diagonals
                if vDir == VertexDirection.BOTTOM and r >= Board.MAX_R // 2:
                    init_diagonal(r_idx, c_idx + 1, "left", flipped=True,
                                  owner=game.get_edge(h.q, h.r, EdgeDirection.SOUTH_EAST).owner)
                    init_diagonal(r_idx, c_idx - 1, "right", flipped=True,
                                  owner=game.get_edge(h.q, h.r, EdgeDirection.SOUTH_WEST).owner)

    # Add robber symbol
    for r in range(Board.MIN_R, Board.MAX_R + 1):
        for i, h in enumerate(game.get_row_hexes(r)):
            row = 3 * r + 2
            col = 1 + abs(r - 2) + 2 * i
            if isinstance(display_array[row + 1][col], (Empty, DiagonalEdges)):
                display_array[row + 1][col].robber = game.get_hex_tile(h.q, h.r).robber
            elif isinstance(display_array[row - 1][col], DiagonalEdges):
                display_array[row - 1][col].robber = game.get_hex_tile(h.q, h.r).robber

    for row in display_array:
        print(" ".join(cell.render() for cell in row))


def get_player_lead_status(player: Player) -> str:
    """Return lead status."""
    if player.is_human:
        player_vp = player.calc_victory_points()[1]
    else:
        player_vp = player.calc_victory_points()[0]
    best_opponent_vp = player.best_opponents_victory_point

    if player_vp > best_opponent_vp:
        return "♕"
    elif player_vp == best_opponent_vp and player_vp > 2:
        return 'Tied-♕'
    else:
        return ""


def display_results(game: Game):
    clear_screen()
    print("Board final values:\n")
    display_board(game)
    sorted_players = sorted(game.players, key=lambda p: p.calc_victory_points()[1], reverse=True)

    print(f"\nThe winner is: {sorted_players[0].name}!\n")
    print("Scores:")
    for i, player in enumerate(sorted_players, start=1):
        print(f"{i}. {player.name}: {player.calc_victory_points()[1]} points")

    for player in sorted_players:
        print(f"\nPoint Summary {player.name}:")
        if len(player.settlements) > 0:
            print(f"Settlements: {len(player.settlements)}")
        if len(player.cities) > 0:
            print(f"Cities: {len(player.cities)}")
        if player.has_longest_road:
            print(f"Longest Road: {player.longest_road_length}")
        if player.has_largest_army:
            print(f"Largest Army: {player.army_size}")

        num_vp_cards = len([c for c in player.development_cards if c.card_type == DevelopmentCardType.VICTORY_POINT])
        if num_vp_cards > 0:
            print(f"Victory Card Points: {num_vp_cards}")


def display_resources(resources: ResourceCount, player_resources: ResourceCount | None = None):
    resources_list = list(resources.items())
    for i in range(0, len(resources_list), 2):
        first = resources_list[i]
        second = resources_list[i + 1] if i + 1 < len(resources_list) else None

        def format_res(res_tuple: Tuple[Resource, int]):
            res, amt = res_tuple
            if player_resources:
                amt = f"{amt}/{player_resources.get(res, 0)}"
            return f"{res.name:>5}: {amt}"

        if second:
            print(f"{format_res(first)}\t{format_res(second)}")
        else:
            print(f"{format_res(first)}")


def resource_dict_to_str(resources: ResourceCount) -> str:
    """Convert a resource-count dict into a human-readable string."""
    parts = [
        f"{count} {resource.name.upper()}"
        for resource, count in resources.items()
        if count > 0
    ]

    if not parts:
        return "nothing"
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return " and ".join(parts)

    return ", ".join(parts[:-1]) + " and " + parts[-1]


def display_trade_offer(
        game: Game,
        selling_player: Player,
        selling: ResourceCount,
        buying: ResourceCount,
        player: Player
):
    clear_screen()
    display_board(game)
    print(f"\n--- Trade Offer from {selling_player.name} ---\n")
    print(f"{selling_player.name} gives:")
    display_resources(selling)
    print("\nYou give:")
    display_resources(buying, player.resources)


def format_counter_offer(original: ResourceCount, counter: ResourceCount) -> str:
    """
    Show resources in the format:
      - 'wood 1' if unchanged
      - 'brick 2 -> 3' if changed
    """
    parts = []
    for res in Resource:
        orig_amt = original.get(res, 0)
        new_amt = counter.get(res, 0)
        if orig_amt != new_amt:
            parts.append(f"{res.name.upper()} {orig_amt} -> {new_amt}")
        elif orig_amt > 0:  # unchanged but present
            parts.append(f"{res.name.upper()} {orig_amt}")
    return ", ".join(parts) if parts else "No resources"
