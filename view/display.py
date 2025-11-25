from abc import ABC, abstractmethod

from game.Board import Board
from game.Edge import EdgeDirection, Edge
from game.HexTile import HexTile
from game.Player import Player
from game.Vertex import VertexDirection, Building, Vertex
from view.Color import Color, colorise

NO_EDGE = object()


def get_player_color(player: Player) -> Color:
    return [Color.BLUE, Color.RED, Color.GREEN, Color.YELLOW][player.value]


class Renderable(ABC):
    @abstractmethod
    def render(self) -> str:
        """Return a string representation suitable for display."""
        pass


class Empty(Renderable):
    def render(self) -> str:
        return "     "


class DisplayHexTile(Renderable):
    def __init__(self, hex_tile: HexTile):
        self.hex_tile = hex_tile

    def render(self) -> str:
        if self.hex_tile.type == "desert":
            label = "DESRT"
        else:
            label = self.hex_tile.type[0].upper() + f"({self.hex_tile.production_number:02})"

        color = {
            "forest": Color.DARK_GREEN,
            "hills": Color.RED_ORANGE,
            "pasture": Color.LIME_GREEN,
            "fields": Color.GOLD,
            "mountains": Color.GREY,
            "desert": Color.BEIGE,
        }.get(self.hex_tile.type)

        if color is None:
            return label

        return colorise(label, color, underline=True)


class DisplayVertex(Renderable):
    def __init__(self, vertex: Vertex):
        self.vertex = vertex

    def render(self) -> str:
        if not self.vertex.owner:
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

        def render_edge(edge, symbol, player=None):
            if edge is NO_EDGE:
                return " "

            text = symbol if edge is None else symbol
            if player:
                return colorise(text, get_player_color(player))
            return text

        return f"{render_edge(self.left, left_symbol)}   {render_edge(self.right, right_symbol)}"


def display_board(board: Board) -> None:
    display_array: list[list[Renderable]] = [[Empty() for _ in range(11)] for _ in range(17)]

    def init_diagonal(row_i: int, col_i: int, side: str, flipped: bool, owner: Player | None):
        cell = display_array[row_i][col_i]
        if not isinstance(cell, DiagonalEdges):
            cell = DiagonalEdges(flipped=flipped)
            display_array[row_i][col_i] = cell
        setattr(cell, side, owner)

    for r in range(board.MIN_R, board.MAX_R + 1):
        row_hexes = sorted([h for h in board.hexes if h.r == r], key=lambda h: h.q)

        for i, h in enumerate(row_hexes):
            row = 3 * r + 2
            col = 1 + abs(r - 2) + 2 * i
            display_array[row][col] = DisplayHexTile(h)
            display_array[row][col - 1] = DisplayEdge(board.get_edge(h.q, h.r, EdgeDirection.WEST))
            display_array[row][col + 1] = DisplayEdge(board.get_edge(h.q, h.r, EdgeDirection.WEST))

            # Places for vertices in display array (dR, dC)
            vertex_pos: (int, int) = [(-2, 0), (-1, 1), (1, 1), (2, 0), (1, -1), (-1, -1)]
            for vDir, (dR, dC) in enumerate(vertex_pos):
                r_idx = row + dR
                c_idx = col + dC
                # Only set if inside array bounds
                if 0 <= r_idx < len(display_array) and 0 <= c_idx < len(display_array[0]):
                    display_array[r_idx][c_idx] = DisplayVertex(board.get_vertex(h.q, h.r, VertexDirection(vDir)))

                # Top diagonals
                if vDir == VertexDirection.TOP and r <= board.MAX_R // 2:
                    init_diagonal(r_idx, c_idx + 1, "left", flipped=False,
                                  owner=board.get_edge(h.q, h.r, EdgeDirection.NORTH_EAST).owner)
                    init_diagonal(r_idx, c_idx - 1, "right", flipped=False,
                                  owner=board.get_edge(h.q, h.r, EdgeDirection.NORTH_WEST).owner)

                # Bottom diagonals
                if vDir == VertexDirection.BOTTOM and r >= board.MAX_R // 2:
                    init_diagonal(r_idx, c_idx + 1, "left", flipped=True,
                                  owner=board.get_edge(h.q, h.r, EdgeDirection.SOUTH_EAST).owner)
                    init_diagonal(r_idx, c_idx - 1, "right", flipped=True,
                                  owner=board.get_edge(h.q, h.r, EdgeDirection.SOUTH_WEST).owner)

    for row in display_array:
        print(" ".join(cell.render() for cell in row))
