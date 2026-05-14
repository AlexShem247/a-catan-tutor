import unittest

import controllers.GameController as GameControllerModule

from ai.BasicAI import BasicAI
from config.player_policies import EVO_VS_RULE_BASED, RULE_BASED_VS_BASIC, STANDARD_SINGLEPLAYER
from controllers.GameController import GameController, PlayerScoreSnapshot
from game.Player import PlayerNumber
from game.PlayerAssets import DevelopmentCard, DevelopmentCardType
from game.Vertex import Vertex, VertexDirection
from view.HeadlessView import HeadlessView
from view.View import GameMode

from test_helpers import (
    GameTestMixin,
    HomeRequestingView,
    InvalidLoopAI,
    TutorFollowingView,
)


class TestControllerModes(GameTestMixin, unittest.TestCase):
    def test_tutor_mode_uses_simulation_opponent_policies(self):
        controller = GameController(STANDARD_SINGLEPLAYER, RULE_BASED_VS_BASIC, game_seed=0)
        controller.game_mode = GameMode.TUTOR
        controller.reset_game()

        self.assertTrue(controller.get_all_players()[0].is_human)
        self.assertIsInstance(controller.get_all_players()[1].policy, BasicAI)
        self.assertIsInstance(controller.get_all_players()[2].policy, BasicAI)
        self.assertIsInstance(controller.get_all_players()[3].policy, BasicAI)

    def test_tutor_ai_uses_dedicated_rng(self):
        controller = GameController(STANDARD_SINGLEPLAYER, RULE_BASED_VS_BASIC, game_seed=0)
        self.assertIsNot(controller.tutor_ai.rng, controller.game_rng)

    def test_tutor_mode_uses_simulation_policy_for_tutor_ai(self):
        controller = GameController(STANDARD_SINGLEPLAYER, EVO_VS_RULE_BASED, game_seed=0)
        controller.game_mode = GameMode.TUTOR
        controller.reset_game()

        self.assertEqual(controller.tutor_ai.policy_name, "RuleBasedAI Evo")

    def test_quick_and_guided_simulations_share_same_seeded_game(self):
        controllers = {}
        for mode in (GameMode.SIMULATION, GameMode.GUIDED):
            controller = GameController(STANDARD_SINGLEPLAYER, EVO_VS_RULE_BASED, game_seed=0)
            controller.view = HeadlessView()
            controller.game_mode = mode
            controller.reset_game()
            controllers[mode] = controller

        for controller in controllers.values():
            players = controller.get_all_players()
            self.assertFalse(players[0].is_human)
            self.assertEqual(players[0].policy.policy_name, "RuleBasedAI Evo")
            self.assertEqual(players[1].policy.policy_name, "RuleBasedAI Original")
            self.assertEqual(players[2].policy.policy_name, "RuleBasedAI Original")
            self.assertEqual(players[3].policy.policy_name, "RuleBasedAI Original")

            controller.run_initial_placement()
            for player in controller.get_all_players():
                controller.make_round_move_ai(player)
            controller.get_game_state().round_num += 1

        self.assertEqual(
            self.controller_state_snapshot(controllers[GameMode.SIMULATION]),
            self.controller_state_snapshot(controllers[GameMode.GUIDED]),
        )

    def test_quick_simulation_home_request_interrupts_ai_turn(self):
        controller = GameController(STANDARD_SINGLEPLAYER, EVO_VS_RULE_BASED, game_seed=0)
        controller.view = HomeRequestingView()
        controller.game_mode = GameMode.SIMULATION
        controller.reset_game()
        controller.run_initial_placement()

        with self.assertRaises(GameControllerModule.ReturnToStart):
            controller.make_round_move_ai(controller.get_all_players()[0])

    def test_tutor_following_recommendations_matches_guided_simulation(self):
        guided = GameController(STANDARD_SINGLEPLAYER, EVO_VS_RULE_BASED, game_seed=0)
        guided.view = HeadlessView()
        guided.game_mode = GameMode.GUIDED
        guided.reset_game()

        tutor = GameController(STANDARD_SINGLEPLAYER, EVO_VS_RULE_BASED, game_seed=0)
        tutor.game_mode = GameMode.TUTOR
        tutor.view = TutorFollowingView(tutor)
        tutor.reset_game()

        guided.run_initial_placement()
        tutor.run_initial_placement()

        for player in guided.get_all_players():
            guided.make_round_move_ai(player)

        for player in tutor.get_all_players():
            if player.is_human:
                tutor.make_round_move(player)
            else:
                tutor.make_round_move_ai(player)

        self.assertEqual(
            self.controller_state_snapshot(guided, include_roles=False),
            self.controller_state_snapshot(tutor, include_roles=False),
        )

    def test_quick_simulation_repeats_identically_with_fixed_seed(self):
        snapshots = []

        for _ in range(4):
            controller = GameController(STANDARD_SINGLEPLAYER, EVO_VS_RULE_BASED, game_seed=0)
            controller.view = HeadlessView()
            controller.game_mode = GameMode.SIMULATION
            controller.reset_game()
            controller.run_initial_placement()

            for _ in range(5):
                for player in controller.get_all_players():
                    controller.make_round_move_ai(player)
                    if controller.get_game_state().game_over:
                        break
                if controller.get_game_state().game_over:
                    break
                controller.get_game_state().round_num += 1

            snapshots.append(self.controller_state_snapshot(controller, include_roles=False))

        for snapshot in snapshots[1:]:
            self.assertEqual(snapshot, snapshots[0])

    def test_play_mode_tutor_following_matches_quick_simulation(self):
        simulation = GameController(STANDARD_SINGLEPLAYER, EVO_VS_RULE_BASED, game_seed=0)
        simulation.view = HeadlessView()
        simulation.game_mode = GameMode.SIMULATION
        simulation.reset_game()

        play_mode = GameController(STANDARD_SINGLEPLAYER, EVO_VS_RULE_BASED, game_seed=0)
        play_mode.game_mode = GameMode.PLAY
        play_mode.view = TutorFollowingView(play_mode)
        play_mode.reset_game()

        simulation.run_initial_placement()
        play_mode.run_initial_placement()

        for _ in range(3):
            for simulation_player, play_player in zip(simulation.get_all_players(), play_mode.get_all_players()):
                simulation.make_round_move_ai(simulation_player)
                if play_player.is_human:
                    play_mode.make_round_move(play_player)
                else:
                    play_mode.make_round_move_ai(play_player)
                if simulation.get_game_state().game_over or play_mode.get_game_state().game_over:
                    break
            if simulation.get_game_state().game_over or play_mode.get_game_state().game_over:
                break
            simulation.get_game_state().round_num += 1
            play_mode.get_game_state().round_num += 1

        self.assertEqual(
            self.controller_state_snapshot(simulation, include_roles=False),
            self.controller_state_snapshot(play_mode, include_roles=False),
        )

    def test_victory_point_history_records_true_points(self):
        controller = GameController(STANDARD_SINGLEPLAYER, RULE_BASED_VS_BASIC, game_seed=0)
        player = controller.get_all_players()[0]
        player.settlements.append(Vertex(pos=(0, 0, VertexDirection.TOP)))
        player.development_cards.append(DevelopmentCard(DevelopmentCardType.VICTORY_POINT))

        controller._record_victory_point_snapshot()
        history = controller.get_victory_point_history()

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0][0], 1)
        self.assertEqual(history[0][1][player.player_number], 2)

    def test_endgame_review_history_records_point_breakdown(self):
        controller = GameController(STANDARD_SINGLEPLAYER, RULE_BASED_VS_BASIC, game_seed=0)
        player = controller.get_all_players()[0]
        player.settlements.append(Vertex(pos=(0, 0, VertexDirection.TOP)))
        player.longest_road_length = 5
        player.has_longest_road = True
        player.development_cards.append(DevelopmentCard(DevelopmentCardType.VICTORY_POINT))

        controller._record_victory_point_snapshot()
        history = controller.get_endgame_review_history()

        self.assertEqual(len(history), 1)
        snapshot = history[0][1][player.player_number]
        self.assertEqual(
            snapshot,
            PlayerScoreSnapshot(
                total_vp=4,
                visible_vp=3,
                settlements=1,
                cities=0,
                hidden_vp_cards=1,
                longest_road_length=5,
                army_size=0,
                has_longest_road=True,
                has_largest_army=False,
            ),
        )

    def test_start_game_aborts_when_ai_exceeds_action_request_limit(self):
        original_limit = GameControllerModule.MAX_AI_ACTION_REQUESTS_PER_TURN
        GameControllerModule.MAX_AI_ACTION_REQUESTS_PER_TURN = 5
        try:
            simulation_players = {
                PlayerNumber.P1: InvalidLoopAI,
                PlayerNumber.P2: BasicAI,
                PlayerNumber.P3: BasicAI,
                PlayerNumber.P4: BasicAI,
            }
            controller = GameController({}, simulation_players, game_seed=0)
            controller.view = HeadlessView()

            controller.start_game(max_rounds=20)

            self.assertTrue(controller.ai_action_limit_reached)
            self.assertFalse(controller.round_limit_reached)
        finally:
            GameControllerModule.MAX_AI_ACTION_REQUESTS_PER_TURN = original_limit
