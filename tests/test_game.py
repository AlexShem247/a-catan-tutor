import math
import unittest
from dataclasses import dataclass
from random import Random
from types import SimpleNamespace
from typing import cast

from ai.RuleBasedAI import RuleBasedAI
from ai.actions import Action, ActionType, Phase
from ai.BasicAI import BasicAI
from ai.simulation.EtwEstimator import EtwEstimator
from ai.simulation.SimGame import make_sim_game_for_player
from ai.tutor.feedback import TutorDecisionType, TutorFeedbackExplanation
from ai.tutor.move_quality import (
    initial_road_connection_move_quality,
    initial_road_flexible_move_quality,
    initial_settlement_move_quality,
    move_quality_from_margin,
    move_quality_from_ratio,
    move_quality_label,
    strategic_turn_move_quality,
)
from config.player_policies import STANDARD_SINGLEPLAYER, RULE_BASED_VS_BASIC
from GameController import GameController, PlayerScoreSnapshot
from game.Edge import Edge, EdgeDirection
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.Player import PlayerNumber
from game.PlayerAssets import Buildable, DevelopmentCard, DevelopmentCardType
from game.Resources import Resource, HexType
from game.Vertex import Vertex, Building, VertexDirection, Port
from PyQt6.QtWidgets import QCheckBox
from view.View import GameMode
from view.MainWindow import MainWindow


class TestGame(unittest.TestCase):

    @dataclass
    class _ReplayMarker:
        index: int

    @staticmethod
    def _fake_player(player_number: PlayerNumber, name: str, is_human: bool = False) -> Player:
        return cast(Player, SimpleNamespace(player_number=player_number, name=name, is_human=is_human))

    @staticmethod
    def _fake_checkbox(checked: bool) -> QCheckBox:
        return cast(QCheckBox, SimpleNamespace(isChecked=lambda: checked))

    @staticmethod
    def _fake_assessment(**kwargs):
        defaults = dict(
            decision_type=TutorDecisionType.MAIN_TURN,
            internal_score=0.0,
            best_internal_score=0.0,
            label="Okay",
            judgment_sentence="",
            your_move="",
            move_context="",
            better_move=None,
            better_move_context="",
            top_strengths=[],
            top_weaknesses=[],
            better_move_reasons=[],
            tip="",
            score_gap=0.0,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    @staticmethod
    def _fake_feedback(**kwargs) -> TutorFeedbackExplanation:
        return cast(TutorFeedbackExplanation, SimpleNamespace(**kwargs))

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

    def _build_example_midgame(self):
        game = Game(STANDARD_SINGLEPLAYER, Random(0))
        p1, p2, p3, p4 = game.players

        for player, coords in [
            (p1, (0, 2, VertexDirection.TOP_RIGHT)),
            (p2, (0, 2, VertexDirection.TOP_LEFT)),
            (p3, (1, 1, VertexDirection.TOP_LEFT)),
            (p4, (-1, 3, VertexDirection.TOP_RIGHT)),
            (p1, (0, 1, VertexDirection.TOP_LEFT)),
            (p2, (1, 2, VertexDirection.BOTTOM)),
            (p3, (-1, 2, VertexDirection.BOTTOM_LEFT)),
            (p1, (0, 0, VertexDirection.TOP)),
            (p2, (2, 0, VertexDirection.TOP)),
            (p1, (1, 2, VertexDirection.TOP_RIGHT)),
        ]:
            game.try_build_settlement(player, game.get_vertex(*coords), road_restriction=False)

        for player, coords in [
            (p1, (0, 2, VertexDirection.TOP_RIGHT)),
            (p3, (1, 1, VertexDirection.TOP_LEFT)),
        ]:
            game.try_build_city(player, game.get_vertex(*coords))

        for player, coords in [
            (p1, (0, 0, EdgeDirection.NORTH_WEST)),
            (p1, (0, 0, EdgeDirection.NORTH_EAST)),
            (p2, (2, 0, EdgeDirection.NORTH_EAST)),
            (p1, (0, 2, EdgeDirection.EAST)),
            (p2, (0, 2, EdgeDirection.WEST)),
            (p3, (1, 1, EdgeDirection.NORTH_WEST)),
            (p4, (-1, 3, EdgeDirection.NORTH_EAST)),
            (p1, (0, 1, EdgeDirection.WEST)),
            (p2, (1, 2, EdgeDirection.SOUTH_EAST)),
            (p3, (-1, 2, EdgeDirection.SOUTH_WEST)),
            (p1, (1, 2, EdgeDirection.EAST)),
        ]:
            game.try_build_road(player, game.get_edge(*coords))

        return game, p1

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

    def test_endgame_review_labels_use_round_history(self):
        p1 = PlayerNumber.P1
        p2 = PlayerNumber.P2
        p3 = PlayerNumber.P3
        p4 = PlayerNumber.P4
        history = [
            (1, {
                p1: PlayerScoreSnapshot(2, 2, 2, 0, 0, 2, 0, False, False),
                p2: PlayerScoreSnapshot(2, 2, 2, 0, 0, 2, 0, False, False),
                p3: PlayerScoreSnapshot(1, 1, 1, 0, 0, 1, 0, False, False),
                p4: PlayerScoreSnapshot(2, 2, 1, 0, 0, 1, 0, False, False),
            }),
            (2, {
                p1: PlayerScoreSnapshot(4, 4, 2, 0, 0, 5, 0, True, False),
                p2: PlayerScoreSnapshot(3, 3, 3, 0, 0, 2, 0, False, False),
                p3: PlayerScoreSnapshot(2, 2, 2, 0, 0, 1, 0, False, False),
                p4: PlayerScoreSnapshot(4, 4, 2, 1, 0, 1, 0, False, False),
            }),
            (3, {
                p1: PlayerScoreSnapshot(6, 6, 2, 1, 0, 6, 0, True, False),
                p2: PlayerScoreSnapshot(4, 4, 2, 1, 0, 2, 0, False, False),
                p3: PlayerScoreSnapshot(3, 3, 3, 0, 0, 2, 0, False, False),
                p4: PlayerScoreSnapshot(5, 5, 1, 2, 0, 1, 0, False, False),
            }),
        ]
        players = [
            self._fake_player(p1, "P1"),
            self._fake_player(p2, "P2"),
            self._fake_player(p3, "P3"),
            self._fake_player(p4, "P4"),
        ]

        lead, swing, closest = MainWindow._summarise_endgame_review_labels(history, players)

        self.assertEqual(lead, "P1 took the lead in Round 3 and held it through Round 3.")
        self.assertEqual(swing, "Round 2: P1 gained Longest Road and jumped by 2 VP.")
        self.assertEqual(closest, "Round 2: P1 and P4 were tied at 4 VP.")

    def test_endgame_plot_tooltip_lists_scores_leader_and_multiple_events(self):
        p1 = PlayerNumber.P1
        p2 = PlayerNumber.P2
        p3 = PlayerNumber.P3
        p4 = PlayerNumber.P4
        history = [
            (17, {
                p1: PlayerScoreSnapshot(5, 5, 3, 1, 0, 4, 0, False, False),
                p2: PlayerScoreSnapshot(4, 4, 2, 1, 0, 4, 0, False, False),
                p3: PlayerScoreSnapshot(5, 5, 3, 1, 0, 4, 0, False, False),
                p4: PlayerScoreSnapshot(7, 7, 3, 2, 0, 5, 0, True, False),
            }),
            (18, {
                p1: PlayerScoreSnapshot(6, 6, 2, 2, 0, 4, 0, False, False),
                p2: PlayerScoreSnapshot(4, 4, 2, 1, 0, 4, 0, False, False),
                p3: PlayerScoreSnapshot(5, 5, 3, 1, 0, 4, 0, False, False),
                p4: PlayerScoreSnapshot(5, 5, 3, 2, 0, 4, 0, False, False),
            }),
        ]
        players = [
            self._fake_player(p1, "P1"),
            self._fake_player(p2, "P2"),
            self._fake_player(p3, "P3"),
            self._fake_player(p4, "P4"),
        ]

        tooltips = MainWindow._build_endgame_plot_tooltips(history, players)

        self.assertEqual(
            tooltips[18],
            "\n".join([
                "Turn 18",
                "",
                "P1: 6 VP",
                "P2: 4 VP",
                "P3: 5 VP",
                "P4: 5 VP",
                "",
                "Leader: P1",
                "Event:",
                "- P1 built a city",
                "- P4 lost Longest Road",
            ])
        )

    def test_endgame_plot_tooltip_marks_tied_leader(self):
        p1 = PlayerNumber.P1
        p2 = PlayerNumber.P2
        history = [
            (18, {
                p1: PlayerScoreSnapshot(6, 6, 2, 2, 0, 4, 0, False, False),
                p2: PlayerScoreSnapshot(6, 6, 2, 2, 0, 4, 0, False, False),
            }),
        ]
        players = [
            self._fake_player(p1, "P1"),
            self._fake_player(p2, "P2"),
        ]

        tooltips = MainWindow._build_endgame_plot_tooltips(history, players)

        self.assertIn("Leader: P1 and P2 (tied)", tooltips[18])

    def test_replay_feedback_details_include_turn_action_and_advice(self):
        assessment = self._fake_assessment(
            your_move="Build a road",
            internal_score=0.53,
            score_gap=0.35,
            judgment_sentence="This road was playable, but it delayed a stronger city plan.",
            better_move="End the turn",
            tip="Preserve resources for the city upgrade.",
        )
        feedback = self._fake_feedback(
            board_snapshot=SimpleNamespace(
                game_state=SimpleNamespace(round_num=18),
                get_all_players=lambda: [self._fake_player(PlayerNumber.P1, "P1", is_human=True)],
            ),
            assessment=assessment,
            label="Okay",
            title="Main Turn",
            history_summary="[Okay] This road was playable.",
        )

        details = MainWindow._format_replay_feedback_details(feedback, 42)

        self.assertEqual(details["turn_and_player"], "Turn 18 - P1")
        self.assertEqual(details["action"], "Action: Build a road")
        self.assertEqual(details["badge"], "Okay")
        self.assertEqual(details["score"], "Score: 0.53 · Gap: +0.35")
        self.assertEqual(
            details["tutor_feedback"],
            "Tutor feedback: This road was playable, but it delayed a stronger city plan.",
        )
        self.assertEqual(
            details["advice"],
            "Better move: End the turn\nTakeaway: Preserve resources for the city upgrade.",
        )
        self.assertEqual(details["turn_label"], "Turn 18 / 42")

    def test_replay_feedback_details_include_resource_context_for_trade_feedback(self):
        assessment = self._fake_assessment(
            your_move="Offer 2 Wood in exchange for 1 Brick.",
            move_context="Exchange: give 2 Wood for 1 Brick",
            internal_score=0.41,
            score_gap=0.22,
            judgment_sentence="The trade was legal, but it paid too much.",
            better_move="Offer 1 Wood in exchange for 1 Brick.",
            better_move_context="Exchange: give 1 Wood for 1 Brick",
            tip="Keep more flexibility for the build after the trade.",
        )
        feedback = self._fake_feedback(
            board_snapshot=SimpleNamespace(
                game_state=SimpleNamespace(round_num=7),
                get_all_players=lambda: [self._fake_player(PlayerNumber.P1, "P1", is_human=True)],
            ),
            assessment=assessment,
            label="Okay",
            title="Trade",
            history_summary="[Okay] The trade was legal.",
        )

        details = MainWindow._format_replay_feedback_details(feedback, 20)

        self.assertEqual(
            details["action"],
            "Action: Offer 2 Wood in exchange for 1 Brick.\nExchange: give 2 Wood for 1 Brick",
        )
        self.assertEqual(
            details["advice"],
            "Better move: Offer 1 Wood in exchange for 1 Brick.\n"
            "Exchange: give 1 Wood for 1 Brick\n"
            "Takeaway: Keep more flexibility for the build after the trade.",
        )

    def test_feedback_card_title_uses_turn_and_compact_action(self):
        feedback = self._fake_feedback(
            board_snapshot=SimpleNamespace(game_state=SimpleNamespace(round_num=18)),
            assessment=self._fake_assessment(your_move="building a road"),
            title="Main Turn",
        )

        title = MainWindow._feedback_card_title(feedback)

        self.assertEqual(title, "Turn 18 - Built Road")

    def test_feedback_filter_maps_labels_to_requested_groups(self):
        window = MainWindow.__new__(MainWindow)
        window.endgame_feedback_filter_checkboxes = cast(dict[str, QCheckBox], {
            "biggest mistakes": self._fake_checkbox(True),
            "okay moves": self._fake_checkbox(False),
            "good moves": self._fake_checkbox(True),
            "excellent moves": self._fake_checkbox(False),
        })

        self.assertTrue(MainWindow._feedback_matches_filter(window, self._fake_feedback(label="Poor")))
        self.assertFalse(MainWindow._feedback_matches_filter(window, self._fake_feedback(label="Okay")))
        self.assertTrue(MainWindow._feedback_matches_filter(window, self._fake_feedback(label="Good")))
        self.assertFalse(MainWindow._feedback_matches_filter(window, self._fake_feedback(label="Excellent")))

    def test_feedback_filter_maps_poor_okay_good_and_excellent(self):
        window = MainWindow.__new__(MainWindow)
        window.endgame_feedback_filter_checkboxes = cast(dict[str, QCheckBox], {
            "biggest mistakes": self._fake_checkbox(True),
            "okay moves": self._fake_checkbox(False),
            "good moves": self._fake_checkbox(True),
            "excellent moves": self._fake_checkbox(False),
        })

        poor_feedback = self._fake_feedback(label="Poor")
        okay_feedback = self._fake_feedback(label="Okay")
        good_feedback = self._fake_feedback(label="Good")
        excellent_feedback = self._fake_feedback(label="Excellent")

        self.assertTrue(MainWindow._feedback_matches_filter(window, poor_feedback))
        self.assertFalse(MainWindow._feedback_matches_filter(window, okay_feedback))
        self.assertTrue(MainWindow._feedback_matches_filter(window, good_feedback))
        self.assertFalse(MainWindow._feedback_matches_filter(window, excellent_feedback))

    def test_overall_performance_summary_uses_final_summary_format(self):
        feedbacks = cast(list[TutorFeedbackExplanation], [
            self._fake_feedback(assessment=self._fake_assessment(
                decision_type=TutorDecisionType.ROBBER, your_move="Move the robber", internal_score=0.9
            )),
            self._fake_feedback(assessment=self._fake_assessment(
                decision_type=TutorDecisionType.MAIN_TURN, your_move="Ending the turn", internal_score=0.75
            )),
            self._fake_feedback(assessment=self._fake_assessment(
                decision_type=TutorDecisionType.DISCARD, your_move="Discard resources", internal_score=0.2
            )),
            self._fake_feedback(assessment=self._fake_assessment(
                decision_type=TutorDecisionType.MAIN_TURN, your_move="Upgrading to a city", internal_score=0.3
            )),
        ])

        final_snapshot = PlayerScoreSnapshot(3, 3, 3, 0, 0, 3, 0, False, False)
        summary = MainWindow._overall_performance_summary(feedbacks, final_snapshot, leader_vp=10)

        self.assertEqual(summary["turn_and_player"], "")
        self.assertEqual(summary["action"], "Your Performance")
        self.assertEqual(summary["badge"], "Poor")
        self.assertEqual(summary["score"], "Overall: Poor (0.34) | Moves 0.54 | VP 0.30 | Win 0.00")
        self.assertIn("Robber placement", summary["tutor_feedback"])
        self.assertIn("finished on only 3 VP", summary["advice"])
        self.assertIn("Discard decisions", summary["advice"])

    def test_overall_performance_summary_does_not_rate_two_vp_finish_as_good(self):
        feedbacks = cast(list[TutorFeedbackExplanation], [
            self._fake_feedback(assessment=self._fake_assessment(
                decision_type=TutorDecisionType.MAIN_TURN,
                your_move="Building a road",
                internal_score=0.8,
            )),
        ])

        summary = MainWindow._overall_performance_summary(
            feedbacks,
            PlayerScoreSnapshot(2, 2, 2, 0, 0, 2, 0, False, False),
            leader_vp=10,
        )

        self.assertEqual(summary["badge"], "Poor")

    def test_tutor_replay_history_is_not_trimmed_with_sidebar_history(self):
        window = MainWindow.__new__(MainWindow)
        window.tutor_feedback_history = []
        window.tutor_feedback_replay_history = []
        window._update_previous_feedback_button = lambda: None

        feedbacks = [self._ReplayMarker(index=i) for i in range(105)]
        for feedback in feedbacks:
            MainWindow._append_tutor_feedback_history(window, cast(TutorFeedbackExplanation, feedback))

        self.assertEqual(len(window.tutor_feedback_history), 100)
        self.assertEqual(len(window.tutor_feedback_replay_history), 105)
        self.assertEqual(cast(self._ReplayMarker, window.tutor_feedback_replay_history[0]).index, 0)
        self.assertEqual(cast(self._ReplayMarker, window.tutor_feedback_history[0]).index, 5)

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
        game, player = self._build_example_midgame()
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
        game, player = self._build_example_midgame()
        player.resources = {res: 0 for res in Resource}
        player.resources[Resource.ORE] = 3
        player.resources[Resource.WHEAT] = 2

        ai = RuleBasedAI(Random(0))
        action, _ = ai.next_action_with_explanation(player, game, Phase.MAIN, False)

        self.assertEqual(action.type, ActionType.BUILD)
        self.assertEqual(action.payload[0], Buildable.CITY)


if __name__ == "__main__":
    unittest.main()
