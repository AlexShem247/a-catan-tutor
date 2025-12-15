import unittest

from game.Board import Board
from game.Player import Player, PlayerNumber


class TestBoard(unittest.TestCase):

    def setUp(self):
        self.board = Board()

    def test_hex_count_and_desert(self):
        # Check total number of hexes and exactly one desert
        self.assertEqual(len(self.board.hexes), len(self.board.HEX_COORDS))
        desert_tiles = [h for h in self.board.hexes if h.type == "desert"]
        self.assertEqual(len(desert_tiles), 1)

    def test_production_numbers(self):
        # Non-desert tiles have valid production numbers
        for hex_tile in self.board.hexes:
            if hex_tile.type != "desert":
                self.assertIn(hex_tile.production_number, range(2, 13))
            else:
                self.assertIsNone(hex_tile.production_number)

    def test_hex_map_consistency(self):
        # Each hex maps correctly in hex_map
        for hex_tile in self.board.hexes:
            self.assertEqual(self.board.hex_map[(hex_tile.q, hex_tile.r)], hex_tile)

    def test_vertex_count_and_sharing(self):
        # Vertices exist and belong to at least one hex
        self.assertTrue(len(self.board.vertices) > 0)
        for vertex in self.board.vertices:
            self.assertGreaterEqual(len(vertex.hexes), 1)
        # Each vertex is in vertex_map
        for key, vertex in self.board.vertex_map.items():
            self.assertIn(vertex, self.board.vertices)

    def test_vertex_has_correct_edges(self):
        # Each vertex references its edges, and each edge references the vertex
        for vertex in self.board.vertices:
            for edge in vertex.edges:
                self.assertIn(vertex, edge.vertices)

    def test_edge_count_and_uniqueness(self):
        # All edges are unique and properly connect two vertices
        seen = set()
        for edge in self.board.edges:
            verts = tuple(sorted(edge.vertices, key=id))
            self.assertNotIn(verts, seen)
            seen.add(verts)
            self.assertEqual(len(edge.vertices), 2)
            for v in edge.vertices:
                self.assertIn(edge, v.edges)

    def test_edge_map_consistency(self):
        # All edges are stored in edge_map
        for key, edge in self.board.edge_map.items():
            self.assertIn(edge, self.board.edges)

    def test_neighbors_assigned_correctly(self):
        # Neighboring hexes are correctly assigned
        directions = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
        for hex_tile in self.board.hexes:
            for dq, dr in directions:
                neighbor = self.board.hex_map.get((hex_tile.q + dq, hex_tile.r + dr))
                if neighbor:
                    self.assertIn(neighbor, hex_tile.neighbors)

    def test_ports_assigned_to_water_edges(self):
        # Ports are assigned to edges on the water
        water_edges = self.board._get_water_edges()
        for vertex in self.board.vertices:
            if vertex.port is not None:
                self.assertTrue(any(edge in water_edges for edge in vertex.edges))

    def test_build_settlement_and_city(self):
        # Player can build a settlement and upgrade to a city
        player = Player(False, PlayerNumber.P1)
        vertex = self.board.vertices[0]
        self.board.build_settlement(vertex, player)
        self.assertEqual(vertex.owner, player)
        self.assertEqual(vertex.building.name, "SETTLEMENT")
        self.assertIn(vertex, player.settlements)
        self.board.build_city(vertex, player)
        self.assertEqual(vertex.building.name, "CITY")
        self.assertIn(vertex, player.cities)

    def test_build_road(self):
        # Player can build a road
        player = Player(False, PlayerNumber.P1)
        edge = self.board.edges[0]
        self.board.build_road(edge, player)
        self.assertEqual(edge.owner, player)
        self.assertIn(edge, player.roads)

    def test_longest_road_simple_chain(self):
        # Longest road calculation works for simple chains
        player = Player(False, PlayerNumber.P1)
        edges = self.board.edges[:3]
        for edge in edges:
            self.board.build_road(edge, player)
        length = Board.calculate_longest_road_length(edges)
        self.assertGreaterEqual(length, 1)
        self.assertLessEqual(length, len(edges))

    def test_longest_road_blocked_by_opponent(self):
        # Longest road is shortened if blocked by opponent's building
        player1 = Player(False, PlayerNumber.P1)
        player2 = Player(False, PlayerNumber.P2)
        edge_chain = self.board.edges[:3]
        for edge in edge_chain:
            self.board.build_road(edge, player1)
        vertex_to_block = edge_chain[1].vertices[0]
        vertex_to_block.owner = player2
        vertex_to_block.building = vertex_to_block.building or "SETTLEMENT"
        length = Board.calculate_longest_road_length(edge_chain)
        self.assertLess(length, len(edge_chain))

    def test_no_roads_longest_road(self):
        # Longest road length is zero when no roads
        length = Board.calculate_longest_road_length([])
        self.assertEqual(length, 0)

    def test_vertex_edge_consistency(self):
        # Each vertex references edges, and each edge references the vertex
        for vertex in self.board.vertices:
            for edge in vertex.edges:
                self.assertIn(vertex, edge.vertices)

    def test_hex_vertex_edge_consistency(self):
        # Hexes reference vertices, vertices reference hexes, edges reference vertices
        for hex_tile in self.board.hexes:
            for vertex in hex_tile.vertices:
                self.assertIn(hex_tile, vertex.hexes)
            for edge in getattr(hex_tile, 'edges', []):
                for v in edge.vertices:
                    self.assertIn(edge, v.edges)


if __name__ == "__main__":
    unittest.main()
