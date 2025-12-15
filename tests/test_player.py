import unittest
from game.Player import Player, PlayerNumber
from game.Resources import Resource
from game.Vertex import Vertex, Port, VertexDirection
from game.Edge import Edge, EdgeDirection


class PlayerTests(unittest.TestCase):

    def setUp(self):
        # Create a default human player
        self.player = Player(is_human=True, playerNumber=PlayerNumber.P1)

    def test_initial_state(self):
        # Resources should all be zero
        for res in Resource:
            self.assertEqual(self.player.resources[res], 0)

        # No buildings initially
        self.assertEqual(self.player.settlements, [])
        self.assertEqual(self.player.cities, [])
        self.assertEqual(self.player.roads, [])

        # Game metrics
        self.assertEqual(self.player.longest_road_length, 0)
        self.assertFalse(self.player.has_longest_road)
        self.assertEqual(self.player.best_opponents_victory_point, 0)

    def test_add_resource(self):
        self.player.add_resource(Resource.WOOD, 3)
        self.assertEqual(self.player.resources[Resource.WOOD], 3)

    def test_remove_resource(self):
        self.player.add_resource(Resource.BRICK, 5)
        self.player.remove_resource(Resource.BRICK, 2)
        self.assertEqual(self.player.resources[Resource.BRICK], 3)

        # Removing more than current should clamp to 0
        self.player.remove_resource(Resource.BRICK, 10)
        self.assertEqual(self.player.resources[Resource.BRICK], 0)

    def test_add_settlement(self):
        vertex = Vertex(pos=(0, 0, VertexDirection.TOP))
        self.player.add_settlement(vertex)
        self.assertIn(vertex, self.player.settlements)

    def test_add_city(self):
        vertex = Vertex(pos=(0, 0, VertexDirection.TOP))
        self.player.add_settlement(vertex)
        self.player.add_city(vertex)

        self.assertIn(vertex, self.player.cities)
        self.assertNotIn(vertex, self.player.settlements)

    def test_add_city_without_settlement(self):
        vertex = Vertex(pos=(1, 1, VertexDirection.TOP))
        self.player.add_city(vertex)
        self.assertIn(vertex, self.player.cities)
        self.assertNotIn(vertex, self.player.settlements)

    def test_add_road(self):
        v1, v2 = Vertex(pos=(0, 0, VertexDirection.TOP)), Vertex(pos=(0, 0, VertexDirection.TOP_RIGHT))
        edge = Edge(v1, v2, (0, 0, EdgeDirection.NORTH_EAST))
        self.player.add_road(edge)
        self.assertIn(edge, self.player.roads)

    def test_calc_victory_points(self):
        # No buildings, no achievements
        self.assertEqual(self.player.calc_victory_points(), 0)

        # Add settlements and cities
        v1, v2 = Vertex(pos=(0, 0, VertexDirection.TOP)), Vertex(pos=(0, 0, VertexDirection.TOP_RIGHT))
        self.player.add_settlement(v1)
        self.assertEqual(self.player.calc_victory_points(), 1)

        self.player.add_city(v2)
        self.assertEqual(self.player.calc_victory_points(), 3)  # 1 settlement + 2 city

        # Add longest road achievement
        self.player.has_longest_road = True
        self.assertEqual(self.player.calc_victory_points(), 5)

    def test_get_ports(self):
        v1, v2, v3 = Vertex(pos=(0, 0, VertexDirection.TOP)), Vertex(pos=(0, 0, VertexDirection.TOP_RIGHT)), \
            Vertex(pos=(0, 0, VertexDirection.BOTTOM_RIGHT))
        v1.port = Port.THREE_TO_ONE
        v2.port = None
        v3.port = Port.WOOD

        self.player.add_settlement(v1)
        self.player.add_settlement(v2)
        self.player.add_city(v3)

        ports = self.player.get_ports()
        self.assertIn(Port.THREE_TO_ONE, ports)
        self.assertIn(Port.WOOD, ports)
        self.assertNotIn(None, ports)


if __name__ == "__main__":
    unittest.main()
