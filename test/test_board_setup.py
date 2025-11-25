import unittest

from game.Board import Board
from game.Vertex import VertexDirection
from game.Edge import EdgeDirection
from game.Player import Player, PlayerNumber
from view.display import display_board


class TestBoardSetup(unittest.TestCase):

    def test_example_board_setup(self):
        board = Board()

        # Create Players
        p1 = Player(PlayerNumber.P1)
        p2 = Player(PlayerNumber.P2)
        p3 = Player(PlayerNumber.P3)
        p4 = Player(PlayerNumber.P4)

        # Settlements
        board.build_settlement(board.get_vertex(0, 2, VertexDirection.TOP_RIGHT), p1)
        board.build_settlement(board.get_vertex(0, 2, VertexDirection.TOP_LEFT), p2)
        board.build_settlement(board.get_vertex(1, 1, VertexDirection.TOP_LEFT), p3)
        board.build_settlement(board.get_vertex(-1, 3, VertexDirection.TOP_RIGHT), p4)
        board.build_settlement(board.get_vertex(0, 1, VertexDirection.TOP_LEFT), p1)
        board.build_settlement(board.get_vertex(1, 2, VertexDirection.BOTTOM), p2)
        board.build_settlement(board.get_vertex(-1, 2, VertexDirection.BOTTOM_LEFT), p3)
        board.build_settlement(board.get_vertex(0, 0, VertexDirection.TOP), p1)
        board.build_settlement(board.get_vertex(2, 0, VertexDirection.TOP), p2)
        board.build_settlement(board.get_vertex(1, 2, VertexDirection.TOP_RIGHT), p1)

        # Cities
        board.build_city(board.get_vertex(0, 2, VertexDirection.TOP_RIGHT), p1)
        board.build_city(board.get_vertex(1, 1, VertexDirection.TOP_LEFT), p3)

        # Roads
        board.build_road(board.get_edge(0, 0, EdgeDirection.NORTH_WEST), p1)
        board.build_road(board.get_edge(0, 0, EdgeDirection.NORTH_EAST), p1)
        board.build_road(board.get_edge(2, 0, EdgeDirection.NORTH_EAST), p2)
        board.build_road(board.get_edge(0, 2, EdgeDirection.EAST), p1)
        board.build_road(board.get_edge(0, 2, EdgeDirection.WEST), p2)
        board.build_road(board.get_edge(1, 1, EdgeDirection.NORTH_WEST), p3)
        board.build_road(board.get_edge(-1, 3, EdgeDirection.NORTH_EAST), p4)
        board.build_road(board.get_edge(0, 1, EdgeDirection.WEST), p1)
        board.build_road(board.get_edge(1, 2, EdgeDirection.SOUTH_EAST), p2)
        board.build_road(board.get_edge(-1, 2, EdgeDirection.SOUTH_WEST), p3)
        board.build_road(board.get_edge(1, 2, EdgeDirection.EAST), p1)

        # # Simple sanity checks
        self.assertEqual(len(p1.settlements), 3)
        self.assertEqual(len(p2.settlements), 3)
        self.assertEqual(len(p3.settlements), 1)
        self.assertEqual(len(p4.settlements), 1)

        self.assertEqual(len(p1.cities), 1)
        self.assertEqual(len(p3.cities), 1)

        self.assertEqual(len(p1.roads), 5)
        self.assertEqual(len(p2.roads), 3)
        self.assertEqual(len(p3.roads), 2)
        self.assertEqual(len(p4.roads), 1)

        # Check board gets displayed
        print("\n")
        display_board(board)


if __name__ == "__main__":
    unittest.main()
