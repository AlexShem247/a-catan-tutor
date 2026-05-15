import unittest
from random import Random

from game.Edge import Edge, EdgeDirection
from game.Game import Game
from game.Player import Player, PlayerNumber
from game.PlayerAssets import DevelopmentCard, DevelopmentCardType, DevelopmentDeck
from game.Resources import Resource
from game.Vertex import Port, Vertex, VertexDirection


class PlayerTests(unittest.TestCase):

    def setUp(self):
        # Create a default human player
        self.rng = Random(0)
        self.player = Player(is_human=True, player_number=PlayerNumber.P1,
                             bank_resources=Game.BANK_INITIAL_RESOURCES.copy(), rng=self.rng)
        self.deck = DevelopmentDeck(self.rng)

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
        self.assertEqual(self.player.calc_victory_points()[1], 0)

        # Add settlements and cities
        v1, v2 = Vertex(pos=(0, 0, VertexDirection.TOP)), Vertex(pos=(0, 0, VertexDirection.TOP_RIGHT))
        self.player.add_settlement(v1)
        self.assertEqual(self.player.calc_victory_points()[1], 1)

        self.player.add_city(v2)
        self.assertEqual(self.player.calc_victory_points()[1], 3)  # 1 settlement + 2 city

        # Add longest road achievement
        self.player.has_longest_road = True
        self.assertEqual(self.player.calc_victory_points()[1], 5)

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

    def test_calculate_discard_count(self):
        # Less than 7 resources
        for res in Resource:
            self.player.resources[res] = 1
        assert self.player.calculate_discard_count() == 0

        # Exactly 7 resources
        self.player.resources[Resource.WOOD] += 2
        assert self.player.calculate_discard_count() == 3

        # Even total > 7
        self.player.resources = {res: 0 for res in Resource}
        self.player.resources[Resource.WOOD] = 4
        self.player.resources[Resource.BRICK] = 6
        assert self.player.calculate_discard_count() == 5

        # Odd total > 7
        self.player.resources = {res: 0 for res in Resource}
        self.player.resources[Resource.WOOD] = 3
        self.player.resources[Resource.BRICK] = 3
        self.player.resources[Resource.SHEEP] = 3
        assert self.player.calculate_discard_count() == 4

        # Zero resources
        self.player.resources = {res: 0 for res in Resource}
        assert self.player.calculate_discard_count() == 0

    def test_victory_point_card_count(self):
        # Add buildings
        self.player.settlements.append(Vertex(pos=(0, 0, VertexDirection.TOP)))
        self.player.settlements.append(Vertex(pos=(1, 0, VertexDirection.TOP)))
        self.player.cities.append(Vertex(pos=(2, 0, VertexDirection.TOP)))

        # Add hidden Victory Point development cards
        self.player.development_cards.append(DevelopmentCard(DevelopmentCardType.VICTORY_POINT))
        self.player.development_cards.append(DevelopmentCard(DevelopmentCardType.VICTORY_POINT))

        # Calculate victory points
        visible, total = self.player.calc_victory_points()

        # Visible points = 1+1+2 = 4 (2 settlements + 1 city)
        self.assertEqual(visible, 4)
        # Total points = 4 + 2 VP cards = 6
        self.assertEqual(total, 6)

    def test_deck_composition(self):
        """Check that the deck has the correct number of each card type."""
        counts = {card_type: 0 for card_type in DevelopmentCardType}
        for card in self.deck.cards():
            counts[card.card_type] += 1

        self.assertEqual(counts[DevelopmentCardType.KNIGHT], 14)
        self.assertEqual(counts[DevelopmentCardType.ROAD_BUILDING], 2)
        self.assertEqual(counts[DevelopmentCardType.YEAR_OF_PLENTY], 2)
        self.assertEqual(counts[DevelopmentCardType.MONOPOLY], 2)
        self.assertEqual(counts[DevelopmentCardType.VICTORY_POINT], 5)

    def test_draw_and_empty_behavior(self):
        """Test draw() reduces deck size, empty() detects when deck is empty, and drawing empty deck raises."""
        initial_size = len(self.deck.cards())

        # Draw a single card and check size decreases
        card = self.deck.draw()
        self.assertIsNotNone(card)
        self.assertEqual(len(self.deck.cards()), initial_size - 1)

        # Draw all remaining cards
        while not self.deck.empty():
            self.deck.draw()
        self.assertTrue(self.deck.empty(), "Deck should be empty after drawing all cards")

        # Drawing from empty deck raises RuntimeError
        with self.assertRaises(RuntimeError):
            self.deck.draw()

    def test_add_resource_respects_bank_limit(self):
        """Player cannot take more resources than the bank has."""
        # Bank starts with 2 of each resource
        bank_resources = {res: 2 for res in Resource}
        player = Player(
            is_human=True,
            player_number=PlayerNumber.P1,
            bank_resources=bank_resources.copy(),
            rng=self.rng,
        )

        # Try to add 5 resources when bank only has 2
        player.add_resource(Resource.WOOD, 5)

        # Player should only receive 2, and bank goes down to 0
        self.assertEqual(player.resources[Resource.WOOD], 2)
        self.assertEqual(player.bank_resources[Resource.WOOD], 0)

    def test_remove_resource_respects_player_limit(self):
        """Player cannot remove more resources than they have."""
        # Bank starts with 2 of each resource
        bank_resources = {res: 2 for res in Resource}
        player = Player(
            is_human=True,
            player_number=PlayerNumber.P1,
            bank_resources=bank_resources.copy(),
            rng=self.rng,
        )

        # Give player 1 wood first
        player.resources[Resource.WOOD] = 1

        # Try to remove 5 resources, only 1 should be removed
        player.remove_resource(Resource.WOOD, 5)

        # Player should only lose 1, and bank gets it back
        self.assertEqual(player.resources[Resource.WOOD], 0)
        self.assertEqual(player.bank_resources[Resource.WOOD], 3)  # 2 + 1 returned


if __name__ == "__main__":
    unittest.main()
