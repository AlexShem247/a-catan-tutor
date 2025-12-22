import unittest

from game.Edge import EdgeDirection
from game.Game import Game
from game.Vertex import VertexDirection
from view.display_utils import display_board


class ExampleBoardSetup(unittest.TestCase):

    def test_example_board_setup(self):
        game = Game(human_player_one=False)
        p1, p2, p3, p4 = game.players

        # Settlements
        game.try_build_settlement(p1, game.get_vertex(0, 2, VertexDirection.TOP_RIGHT), road_restriction=False)
        game.try_build_settlement(p2, game.get_vertex(0, 2, VertexDirection.TOP_LEFT), road_restriction=False)
        game.try_build_settlement(p3, game.get_vertex(1, 1, VertexDirection.TOP_LEFT), road_restriction=False)
        game.try_build_settlement(p4, game.get_vertex(-1, 3, VertexDirection.TOP_RIGHT), road_restriction=False)
        game.try_build_settlement(p1, game.get_vertex(0, 1, VertexDirection.TOP_LEFT), road_restriction=False)
        game.try_build_settlement(p2, game.get_vertex(1, 2, VertexDirection.BOTTOM), road_restriction=False)
        game.try_build_settlement(p3, game.get_vertex(-1, 2, VertexDirection.BOTTOM_LEFT), road_restriction=False)
        game.try_build_settlement(p1, game.get_vertex(0, 0, VertexDirection.TOP), road_restriction=False)
        game.try_build_settlement(p2, game.get_vertex(2, 0, VertexDirection.TOP), road_restriction=False)
        game.try_build_settlement(p1, game.get_vertex(1, 2, VertexDirection.TOP_RIGHT), road_restriction=False)

        # Cities
        game.try_build_city(p1, game.get_vertex(0, 2, VertexDirection.TOP_RIGHT))
        game.try_build_city(p3, game.get_vertex(1, 1, VertexDirection.TOP_LEFT))

        # Roads
        game.try_build_road(p1, game.get_edge(0, 0, EdgeDirection.NORTH_WEST))
        game.try_build_road(p1, game.get_edge(0, 0, EdgeDirection.NORTH_EAST))
        game.try_build_road(p2, game.get_edge(2, 0, EdgeDirection.NORTH_EAST))
        game.try_build_road(p1, game.get_edge(0, 2, EdgeDirection.EAST))
        game.try_build_road(p2, game.get_edge(0, 2, EdgeDirection.WEST))
        game.try_build_road(p3, game.get_edge(1, 1, EdgeDirection.NORTH_WEST))
        game.try_build_road(p4, game.get_edge(-1, 3, EdgeDirection.NORTH_EAST))
        game.try_build_road(p1, game.get_edge(0, 1, EdgeDirection.WEST))
        game.try_build_road(p2, game.get_edge(1, 2, EdgeDirection.SOUTH_EAST))
        game.try_build_road(p3, game.get_edge(-1, 2, EdgeDirection.SOUTH_WEST))
        game.try_build_road(p1, game.get_edge(1, 2, EdgeDirection.EAST))

        print("\n")
        display_board(game)

        # Sanity checks
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


if __name__ == "__main__":
    unittest.main()
