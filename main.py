from game.Board import Board
from game.Vertex import VertexDirection
from game.Edge import EdgeDirection
from game.Player import Player
from view.display import display_board

if __name__ == "__main__":
    board = Board()

    # Settlements
    board.build_settlement(board.get_vertex(0, 2, VertexDirection.TOP_RIGHT), Player.P1)
    board.build_settlement(board.get_vertex(0, 2, VertexDirection.TOP_LEFT), Player.P2)
    board.build_settlement(board.get_vertex(1, 1, VertexDirection.TOP_LEFT), Player.P3)
    board.build_settlement(board.get_vertex(-1, 3, VertexDirection.TOP_RIGHT), Player.P4)
    board.build_settlement(board.get_vertex(0, 1, VertexDirection.TOP_LEFT), Player.P1)
    board.build_settlement(board.get_vertex(1, 2, VertexDirection.BOTTOM), Player.P2)
    board.build_settlement(board.get_vertex(-1, 2, VertexDirection.BOTTOM_LEFT), Player.P3)
    board.build_settlement(board.get_vertex(0, 0, VertexDirection.TOP), Player.P1)
    board.build_settlement(board.get_vertex(2, 0, VertexDirection.TOP), Player.P2)

    # Cities
    board.build_city(board.get_vertex(0, 2, VertexDirection.TOP_RIGHT), Player.P1)
    board.build_city(board.get_vertex(1, 1, VertexDirection.TOP_LEFT), Player.P3)

    # Roads
    board.build_road(board.get_edge(0, 0, EdgeDirection.NORTH_WEST), Player.P1)
    board.build_road(board.get_edge(0, 0, EdgeDirection.NORTH_EAST), Player.P1)
    board.build_road(board.get_edge(2, 0, EdgeDirection.NORTH_EAST), Player.P2)
    board.build_road(board.get_edge(0, 2, EdgeDirection.EAST), Player.P1)
    board.build_road(board.get_edge(0, 2, EdgeDirection.WEST), Player.P2)
    board.build_road(board.get_edge(1, 1, EdgeDirection.NORTH_WEST), Player.P3)
    board.build_road(board.get_edge(-1, 3, EdgeDirection.NORTH_EAST), Player.P4)
    board.build_road(board.get_edge(0, 1, EdgeDirection.WEST), Player.P1)
    board.build_road(board.get_edge(1, 2, EdgeDirection.SOUTH_EAST), Player.P2)
    board.build_road(board.get_edge(-1, 2, EdgeDirection.SOUTH_WEST), Player.P3)

    display_board(board)
