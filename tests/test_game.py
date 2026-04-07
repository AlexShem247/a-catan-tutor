import unittest
from random import Random

from ai.tutor.confidence import (
    confidence_from_margin,
    confidence_from_ratio,
    confidence_label,
    initial_road_connection_confidence,
    initial_road_flexible_confidence,
    initial_settlement_confidence,
)
from GameController import GameController
from game.Edge import Edge, EdgeDirection
from game.Game import Game
from game.HexTile import HexTile
from game.Player import PlayerNumber
from game.PlayerAssets import Buildable, DevelopmentCard, DevelopmentCardType
from game.Resources import Resource, HexType
from game.Vertex import Vertex, Building, VertexDirection, Port


class TestGame(unittest.TestCase):

    def setUp(self):
        player_config = {
            PlayerNumber.P1: None,
            PlayerNumber.P2: None,
            PlayerNumber.P3: None,
            PlayerNumber.P4: None,
        }
        self.game = Game(player_config, Random(0))
        self.player = self.game.players[0]
        self.opponent = self.game.players[1]

        # Give some resources for testing
        self.player.resources = {res: 5 for res in Resource}
        self.opponent.resources = {res: 5 for res in Resource}

        # Set up basic board objects
        self.hex_tile = HexTile(q=0, r=0, hex_type=HexType.FOREST, production_number=8)
        self.vertex = Vertex(pos=(0, 0, VertexDirection.TOP))
        v2 = Vertex(pos=(0, 0, VertexDirection.TOP_RIGHT))
        self.edge = Edge(self.vertex, v2, pos=(0, 0, EdgeDirection.NORTH_EAST))

    def test_can_afford_exact(self):
        # Player has exactly required resources
        self.player.resources = Game.BUILDING_COST[Buildable.ROAD].copy()
        self.assertTrue(self.game.can_afford(self.player, Buildable.ROAD))

    def test_can_afford_more(self):
        self.assertTrue(self.game.can_afford(self.player, Buildable.SETTLEMENT))

    def test_cannot_afford(self):
        self.player.resources[Resource.WOOD] = 0
        self.assertFalse(self.game.can_afford(self.player, Buildable.ROAD))

    def test_roll_dice_range_and_distribution(self):
        d1, d2, total = self.game.roll_dice()
        self.assertIn(d1, range(1, 7))
        self.assertIn(d2, range(1, 7))
        self.assertEqual(total, d1 + d2)

    def test_get_buildable_options_empty_when_cannot_afford(self):
        self.player.resources = {res: 0 for res in Resource}
        options = self.game.get_buildable_options(self.player)
        del options[Buildable.DEVELOPMENT_CARD]
        for buildable, locations in options.items():
            self.assertEqual(locations, [])

    def test_get_trade_rate_with_specific_port(self):
        self.player.get_ports = lambda: []
        self.assertEqual(self.game.get_trade_rate(self.player, Resource.WOOD), 4)

        self.player.get_ports = lambda: [Port.THREE_TO_ONE]
        self.assertEqual(self.game.get_trade_rate(self.player, Resource.WOOD), 3)

        self.player.get_ports = lambda: [Port.WOOD]
        self.assertEqual(self.game.get_trade_rate(self.player, Resource.WOOD), 2)

    def test_try_trade_with_bank_success(self):
        selling = {Resource.WOOD: 4}
        buying = {Resource.BRICK: 1}
        self.player.resources[Resource.WOOD] = 4
        self.player.bank_resources[Resource.BRICK] += 1
        success = self.game.try_trade_with_bank(self.player, selling, buying)
        self.assertTrue(success)
        self.assertEqual(self.player.resources[Resource.BRICK], 6)

    def test_try_trade_with_bank_fail_multiple_resources(self):
        selling = {Resource.WOOD: 1, Resource.BRICK: 1}
        buying = {Resource.SHEEP: 1}
        self.assertFalse(self.game.try_trade_with_bank(self.player, selling, buying))

    def test_try_build_settlement_success(self):
        # Allow a free vertex for building
        success, _ = self.game.try_build_settlement(self.player, self.vertex)
        self.assertFalse(success)

        success, _ = self.game.try_build_settlement(self.player, self.vertex, road_restriction=False)
        self.assertTrue(success)
        self.assertEqual(self.vertex.owner, self.player)
        self.assertEqual(self.vertex.building, Building.SETTLEMENT)

    def test_try_build_settlement_fail_occupied(self):
        self.vertex.owner = self.opponent
        success, _ = self.game.try_build_settlement(self.player, self.vertex)
        self.assertFalse(success)

    def test_try_build_city_success(self):
        self.vertex.owner = self.player
        self.vertex.building = Building.SETTLEMENT
        success, _ = self.game.try_build_city(self.player, self.vertex)
        self.assertTrue(success)
        self.assertEqual(self.vertex.building, Building.CITY)

    def test_try_build_city_fail_not_owned(self):
        self.vertex.owner = self.opponent
        self.vertex.building = Building.SETTLEMENT
        success, _ = self.game.try_build_city(self.player, self.vertex)
        self.assertFalse(success)

    def test_try_build_road_success(self):
        # Attach road to player vertex
        v2 = Vertex(pos=(0, 0, VertexDirection.TOP_RIGHT))
        edge = Edge(self.vertex, v2, pos=(0, 0, EdgeDirection.NORTH_EAST))
        self.vertex.owner = self.player
        success, _ = self.game.try_build_road(self.player, edge)
        self.assertTrue(success)
        self.assertEqual(edge.owner, self.player)

    def test_try_build_road_fail_no_connection(self):
        v3 = Vertex(pos=(1, 0, VertexDirection.TOP))
        v4 = Vertex(pos=(1, 0, VertexDirection.TOP_RIGHT))
        edge = Edge(v3, v4, pos=(1, 0, EdgeDirection.NORTH_EAST))
        success, _ = self.game.try_build_road(self.player, edge)
        self.assertFalse(success)

    def test_update_best_opponent_victory_points(self):
        self.player.calc_victory_points = lambda: (5, 5)
        self.opponent.calc_victory_points = lambda: (7, 7)
        self.game.update_best_opponent_victory_points()
        self.assertEqual(self.player.best_opponents_victory_point, 7)
        self.assertFalse(self.game.game_over)

    def test_update_best_opponent_victory_points_game_over(self):
        self.player.calc_victory_points = lambda: (10, 10)
        self.opponent.calc_victory_points = lambda: (5, 5)
        self.game.update_best_opponent_victory_points()
        self.assertTrue(self.game.game_over)

    def test_trade_between_players(self):
        selling = {Resource.WOOD: 2}
        buying = {Resource.BRICK: 1}
        self.player.resources[Resource.WOOD] = 3
        self.opponent.resources[Resource.BRICK] = 2
        self.game.trade_between_players(self.player, selling, self.opponent, buying)
        self.assertEqual(self.player.resources[Resource.WOOD], 1)
        self.assertEqual(self.player.resources[Resource.BRICK], 6)
        self.assertEqual(self.opponent.resources[Resource.WOOD], 7)
        self.assertEqual(self.opponent.resources[Resource.BRICK], 1)

    def test_get_available_vertices_and_edges(self):
        vertices = self.game.get_available_vertices(self.player, Buildable.SETTLEMENT)
        self.assertIsInstance(vertices, list)
        edges = self.game.get_available_edges(self.player)
        self.assertIsInstance(edges, list)

    def test_buy_victory_point_card_sets_game_over(self):
        self.player.settlements = [Vertex(pos=(0, 0, VertexDirection.TOP))]
        self.player.cities = [
            Vertex(pos=(0, 0, VertexDirection.TOP_RIGHT)),
            Vertex(pos=(0, 0, VertexDirection.BOTTOM_RIGHT)),
            Vertex(pos=(0, 0, VertexDirection.BOTTOM)),
            Vertex(pos=(0, 0, VertexDirection.BOTTOM_LEFT)),
        ]
        self.game.development_deck._deck = [DevelopmentCard(DevelopmentCardType.VICTORY_POINT)]

        success, _ = self.game.try_buy_development_card(self.player)

        self.assertTrue(success)
        self.assertTrue(self.game.game_over)

    def test_knight_largest_army_sets_game_over(self):
        player_config = {
            PlayerNumber.P1: None,
            PlayerNumber.P2: None,
            PlayerNumber.P3: None,
            PlayerNumber.P4: None,
        }
        controller = GameController(player_config, player_config, game_seed=0)
        player = controller.get_all_players()[0]
        player.cities = [
            Vertex(pos=(0, 0, VertexDirection.TOP)),
            Vertex(pos=(0, 0, VertexDirection.TOP_RIGHT)),
            Vertex(pos=(0, 0, VertexDirection.BOTTOM_RIGHT)),
            Vertex(pos=(0, 0, VertexDirection.BOTTOM)),
        ]
        player.army_size = 2
        player.development_cards.append(DevelopmentCard(DevelopmentCardType.KNIGHT, playable=True))
        controller.handle_robber_action = lambda _: None

        controller.play_development_card(player, DevelopmentCardType.KNIGHT)

        self.assertTrue(player.has_largest_army)
        self.assertTrue(controller.get_game_state().game_over)

    def test_confidence_ratio_is_clamped_to_zero_to_one(self):
        self.assertEqual(confidence_from_ratio(8.0, 10.0), 0.8)
        self.assertEqual(confidence_from_ratio(15.0, 10.0), 1.0)

    def test_confidence_from_margin_normalises_by_spread(self):
        self.assertAlmostEqual(confidence_from_margin(10.0, 8.0, 0.0), 0.2)
        self.assertEqual(confidence_from_margin(10.0, None, 0.0), 0.0)

    def test_opening_confidence_helpers(self):
        self.assertEqual(initial_settlement_confidence(12.0, 12.0), 1.0)
        self.assertEqual(initial_road_connection_confidence(1), 1.0)
        self.assertEqual(initial_road_connection_confidence(4), 0.25)
        self.assertEqual(initial_road_flexible_confidence(), 0.3)

    def test_confidence_labels_use_zero_to_one_thresholds(self):
        self.assertEqual(confidence_label(0.9), "Excellent")
        self.assertEqual(confidence_label(0.7), "Good")
        self.assertEqual(confidence_label(0.5), "Okay")
        self.assertEqual(confidence_label(0.25), "Questionable")
        self.assertEqual(confidence_label(0.1), "Poor")


if __name__ == "__main__":
    unittest.main()
