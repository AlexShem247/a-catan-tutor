import math
import unittest
from random import Random
from types import SimpleNamespace

from ai.actions import Action, ActionType, Phase
from ai.rule_based_ai.RuleBasedAI import RuleBasedAI
from ai.simulation.EtwEstimator import EtwEstimator
from ai.simulation.SimGame import make_sim_game_for_player
from ai.tutor.move_quality import (
    initial_road_connection_move_quality,
    initial_road_flexible_move_quality,
    initial_settlement_move_quality,
    move_quality_from_margin,
    move_quality_from_ratio,
    move_quality_label,
    strategic_turn_move_quality,
)
from game.Game import Game
from game.PlayerAssets import Buildable
from game.Resources import Resource
from game.Vertex import VertexDirection

from test_helpers import GameTestMixin


class TestAiEtwAndQuality(GameTestMixin, unittest.TestCase):
    def test_move_quality_ratio_is_clamped_to_zero_to_one(self):
        self.assertEqual(move_quality_from_ratio(8.0, 10.0), 0.8)
        self.assertEqual(move_quality_from_ratio(15.0, 10.0), 1.0)

    def test_move_quality_from_margin_normalises_by_spread(self):
        self.assertAlmostEqual(move_quality_from_margin(10.0, 8.0, 0.0), 0.2)
        self.assertEqual(move_quality_from_margin(10.0, None, 0.0), 0.0)

    def test_opening_move_quality_helpers(self):
        self.assertEqual(initial_settlement_move_quality(12.0, 12.0), 1.0)
        self.assertEqual(initial_road_connection_move_quality(1), 1.0)
        self.assertAlmostEqual(initial_road_connection_move_quality(4), 0.18946457081379978)
        self.assertEqual(initial_road_flexible_move_quality(), 0.3)

    def test_move_quality_labels_use_zero_to_one_thresholds(self):
        self.assertEqual(move_quality_label(0.9), "Excellent")
        self.assertEqual(move_quality_label(0.7), "Good")
        self.assertEqual(move_quality_label(0.5), "Okay")
        self.assertEqual(move_quality_label(0.3), "Poor")
        self.assertEqual(move_quality_label(0.4), "Okay")
        self.assertEqual(move_quality_label(0.25), "Poor")
        self.assertEqual(move_quality_label(0.1), "Poor")

    def test_strategic_turn_move_quality_uses_etw_reduction(self):
        candidate = SimpleNamespace(etw_before=20.0, etw_after=16.0, etw_delta=4.0, utility_total=12.0)
        quality = strategic_turn_move_quality(candidate, second_utility=6.0, worst_utility=0.0)
        self.assertAlmostEqual(quality, 0.3515066414812375)
        self.assertLessEqual(quality, 1.0)

    def test_strategic_turn_move_quality_defaults_low_when_no_gain(self):
        candidate = SimpleNamespace(etw_before=20.0, etw_after=20.0, etw_delta=0.0, utility_total=0.0)
        self.assertEqual(strategic_turn_move_quality(candidate), 0.0)

    def test_end_turn_candidate_can_gain_positive_utility_from_waiting(self):
        estimator = EtwEstimator()
        self.vertex.hexes = [self.hex_tile]
        self.player.settlements = [self.vertex]
        self.player.resources = {res: 0 for res in Resource}
        self.player.resources[Resource.BRICK] = 1

        sim_game = make_sim_game_for_player(self.game, self.player)
        sim_player = sim_game.overlay.get_sim_player(self.player.player_number)
        estimator.estimated_time_to_win = lambda *args, **kwargs: 7.0
        etw_before = 10.0

        end_turn_candidate = estimator._build_end_turn_candidate(sim_player, sim_game, etw_before)

        self.assertGreater(end_turn_candidate.etw_delta, 0.0)
        self.assertGreater(end_turn_candidate.utility_total, 0.0)
        self.assertEqual(end_turn_candidate.action.type, ActionType.END_TURN)

    def test_estimated_time_to_build_uses_future_tradable_production(self):
        game, player = self.build_example_midgame()
        player.resources = {res: 0 for res in Resource}
        player.resources[Resource.ORE] = 3
        player.resources[Resource.WHEAT] = 2

        estimator = EtwEstimator()
        sim_game = make_sim_game_for_player(game, player)
        sim_player = sim_game.overlay.get_sim_player(player.player_number)
        city_vertex = next(v for v in sim_player.settlements if v.pos == (2, 1, VertexDirection.BOTTOM))

        estimator._simulate_step(sim_game, sim_player, Action(ActionType.BUILD, (Buildable.CITY, city_vertex)))
        etb = estimator.estimated_time_to_build(sim_player, sim_game, Game.BUILDING_COST[Buildable.CITY])

        self.assertTrue(math.isfinite(etb))

    def test_rule_based_ai_builds_affordable_city_instead_of_ending_turn(self):
        game, player = self.build_example_midgame()
        player.resources = {res: 0 for res in Resource}
        player.resources[Resource.ORE] = 3
        player.resources[Resource.WHEAT] = 2

        ai = RuleBasedAI(Random(0))
        action, _ = ai.next_action_with_explanation(player, game, Phase.MAIN, False)

        self.assertEqual(action.type, ActionType.BUILD)
        self.assertEqual(action.payload[0], Buildable.CITY)
