from abc import ABC, abstractmethod
from typing import Dict

from game.Board import Board
from game.Edge import EdgeDirection, Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.Resources import Resource
from game.Vertex import VertexDirection, Building, Vertex, Port
from view.Color import Color, colorise, brighten

NO_EDGE = object()


def get_player_color(player: Player) -> Color:
    return [Color.BLUE, Color.RED, Color.GREEN, Color.YELLOW][player.playerNumber.value]


def clear_screen():
    print("\033[H\033[J", end="")


class Renderable(ABC):
    @abstractmethod
    def render(self) -> str:
        """Return a string representation suitable for display."""
        pass


class Empty(Renderable):
    def render(self) -> str:
        return "     "


class DisplayHexTile(Renderable):
    COLOR_MAP = {
        "forest": Color.DARK_GREEN,
        "hills": Color.RED_ORANGE,
        "pasture": Color.LIME_GREEN,
        "fields": Color.GOLD,
        "mountains": Color.GREY,
        "desert": Color.BEIGE,
    }

    HEX_LABEL = {
        "forest": "FOR",
        "hills": "HIL",
        "pasture": "PAS",
        "fields": "FLD",
        "mountains": "MTN",
    }

    def __init__(self, hex_tile: HexTile):
        self.hex_tile = hex_tile

    def render(self) -> str:
        length = 4 - len(str(self.hex_tile.production_number))
        label = "DESRT" if self.hex_tile.type == "desert" \
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

        return f"{render_edge(self.left, left_symbol)}   {render_edge(self.right, right_symbol)}"


def display_board(game: Game) -> None:
    display_array: list[list[Renderable]] = [[Empty() for _ in range(11)] for _ in range(17)]

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

    for row in display_array:
        print(" ".join(cell.render() for cell in row))


def get_player_lead_status(player: Player) -> str:
    """Return lead status."""
    player_vp = player.calc_victory_points()
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
    sorted_players = sorted(game.players, key=lambda p: p.calc_victory_points(), reverse=True)

    print(f"\nThe winner is: {sorted_players[0].name}!\n")
    print("Scores:")
    for i, player in enumerate(sorted_players, start=1):
        print(f"{i}. {player.name}: {player.calc_victory_points()} points")


def display_resources(resources: Dict[Resource, int], player: Player | None = None):
    resources_list = list(resources.items())
    for i in range(0, len(resources_list), 2):
        first = resources_list[i]
        second = resources_list[i + 1] if i + 1 < len(resources_list) else None

        def format_res(res_tuple: tuple[Resource, int]):
            res, amt = res_tuple
            if player:
                amt = f"{amt}/{player.resources.get(res, 0)}"
            return f"{res.name:>5}: {amt}"

        if second:
            print(f"{format_res(first)}\t{format_res(second)}")
        else:
            print(f"{format_res(first)}")
