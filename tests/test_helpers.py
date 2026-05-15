from dataclasses import dataclass
from random import Random
from types import SimpleNamespace
from typing import Any, cast

from PyQt6.QtWidgets import QCheckBox

from ai.actions import Action, ActionType, Phase
from ai.BasicAI import BasicAI
from ai.tutor.feedback import TutorDecisionType, TutorFeedbackExplanation
from config.player_policies import STANDARD_SINGLEPLAYER
from controllers.GameController import GameController
from game.Edge import Edge, EdgeDirection
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.PlayerAssets import Buildable
from game.Resources import HexType, Resource
from game.Vertex import Vertex, VertexDirection
from view.HeadlessView import HeadlessView


class InvalidLoopAI(BasicAI):

    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        return Action(ActionType.BUILD, (Buildable.CITY, None))


class HomeRequestingView(HeadlessView):

    def __init__(self):
        self._return_home_requested = False

    def display_board_turn_ai(self, player: Player, dice_info, msg: str, increase_delay=False) -> None:
        self._return_home_requested = True

    def consume_return_home_request(self) -> bool:
        requested = self._return_home_requested
        self._return_home_requested = False
        return requested


class TutorFollowingView(HeadlessView):

    def __init__(self, controller: GameController):
        self.controller = controller
        self.current_player: Player | None = None
        self.last_selected_hex: HexTile | None = None

    def display_board(self, player: Player | None = None, msg: str | None = None) -> None:
        self.current_player = player

    def display_board_turn(self, player: Player, dice_info, played_dev_card: bool = False) -> Action:
        self.current_player = player
        return self.controller.get_tutor_recommended_main_action(player, played_dev_card)

    def draw_selectable_vertices(self, vertices, disable_interactivity: bool = False):
        player = self.current_player
        game = self.controller.get_game_state()
        if player is None:
            return vertices[0]

        if self.last_selected_hex is not None:
            selected_owner = self.controller.get_tutor_recommended_robber_choice(player, [self.last_selected_hex])[1]
            if selected_owner is not None:
                for building in vertices:
                    if building.owner == selected_owner:
                        return building

        return self.controller.run_tutor_decision(
            lambda: self.controller.tutor_ai.select_initial_settlement_location(player, game, vertices))

    def draw_selectable_edges(self, edges, disable_interactivity: bool = False):
        player = self.current_player
        if player is None:
            return edges[0]
        return self.controller.run_tutor_decision(lambda: self.controller.tutor_ai.select_initial_road_location(
            player,
            self.controller.get_game_state(),
            edges,
        ))

    def draw_selectable_tiles(self, tiles):
        player = self.current_player
        if player is None:
            return tiles[0]
        self.last_selected_hex = self.controller.get_tutor_recommended_robber_choice(player, tiles)[0]
        return self.last_selected_hex

    def show_resource_chooser(self, player: Player, num_resources: int, title: str, resource_caps=None):
        game = self.controller.get_game_state()
        title_lower = title.lower()
        if "robber has been rolled" in title_lower:
            return self.controller.run_tutor_decision(
                lambda: self.controller.tutor_ai.select_discard_resources(player, game, num_resources))
        if "year of plenty" in title_lower:
            return self.controller.run_tutor_decision(
                lambda: self.controller.tutor_ai.select_year_of_plenty_resources(player, game))
        if "monopoly" in title_lower:
            chosen_resource = self.controller.run_tutor_decision(
                lambda: self.controller.tutor_ai.select_monopoly_resource(player, game))
            return {chosen_resource: 1}
        return {}

    def display_trade_manager(self, player: Player, selling, buying, selling_player: Player):
        return self.controller.run_tutor_decision(lambda: self.controller.tutor_ai.respond_to_trade(
            player,
            self.controller.get_game_state(),
            selling_player,
            selling,
            buying,
        ))

    def select_player_trade_offer(self, player: Player, selling, buying, willing_players):
        return self.controller.run_tutor_decision(lambda: self.controller.tutor_ai.choose_trade_partner(
            player,
            self.controller.get_game_state(),
            selling,
            buying,
            willing_players,
        ))

    def pre_roll(self, player: Player):
        action: Any = self.controller.run_tutor_decision(lambda: self.controller.tutor_ai.next_action(
            player,
            self.controller.get_game_state(),
            Phase.PRE_ROLL,
            False,
        ))
        if action.type == ActionType.PLAY_DEV_CARD:
            return action.payload
        return False


@dataclass
class ReplayMarker:
    index: int


class GameTestMixin:
    game: Game
    player: Player
    opponent: Player
    hex_tile: HexTile
    vertex: Vertex
    edge: Edge

    @staticmethod
    def fake_player(player_number: PlayerNumber, name: str, is_human: bool = False) -> Player:
        return cast(Player, SimpleNamespace(player_number=player_number, name=name, is_human=is_human))

    @staticmethod
    def fake_checkbox(checked: bool) -> QCheckBox:
        return cast(QCheckBox, SimpleNamespace(isChecked=lambda: checked))

    @staticmethod
    def fake_assessment(**kwargs):
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
    def fake_feedback(**kwargs) -> TutorFeedbackExplanation:
        return cast(TutorFeedbackExplanation, SimpleNamespace(**kwargs))

    @staticmethod
    def controller_state_snapshot(controller: GameController, include_roles: bool = True):

        def normalize_pos(position):
            return tuple(getattr(part, "value", part) for part in position)

        game = controller.get_game_state()
        robber_tile = next((tile for tile in game.get_all_hexes() if tile.robber), None)
        robber_pos = None if robber_tile is None else (robber_tile.q, robber_tile.r)

        player_snapshots = tuple((
            player.player_number.name,
            player.is_human if include_roles else None,
            (None if player.policy is None else player.policy.policy_name) if include_roles else None,
            tuple((resource.name, player.resources.get(resource, 0)) for resource in Resource),
            tuple(sorted(normalize_pos(vertex.pos) for vertex in player.settlements)),
            tuple(sorted(normalize_pos(vertex.pos) for vertex in player.cities)),
            tuple(sorted(normalize_pos(edge.pos) for edge in player.roads)),
            tuple(sorted((card.card_type.name, card.playable) for card in player.development_cards)),
            player.army_size,
            player.longest_road_length,
            player.has_longest_road,
            player.has_largest_army,
        ) for player in game.players)
        bank_resources = tuple((resource.name, game.bank_resources[resource]) for resource in Resource)
        development_deck = tuple(card.card_type.name for card in game.development_deck.cards())
        played_cards = tuple((card_type.name, count) for card_type, count in sorted(
            game.development_deck.played_counts().items(), key=lambda item: item[0].name))

        return (
            game.round_num,
            game.game_over,
            robber_pos,
            bank_resources,
            player_snapshots,
            development_deck,
            played_cards,
        )

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
        self.player.resources = {res: 5 for res in Resource}
        self.opponent.resources = {res: 5 for res in Resource}
        self.hex_tile = HexTile(q=0, r=0, hex_type=HexType.FOREST, production_number=8)
        self.vertex = Vertex(pos=(0, 0, VertexDirection.TOP))
        v2 = Vertex(pos=(0, 0, VertexDirection.TOP_RIGHT))
        self.edge = Edge(self.vertex, v2, pos=(0, 0, EdgeDirection.NORTH_EAST))

    def build_example_midgame(self):
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
