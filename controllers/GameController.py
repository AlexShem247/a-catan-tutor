from concurrent.futures import Future, ThreadPoolExecutor
from random import Random
from threading import Condition, Lock
from typing import Any, Callable

from ai.actions import Action, ActionType
from ai.tutor.evaluator import TutorEvaluator
from ai.tutor.feedback import TutorFeedbackExplanation
from config.view_constants import (AI_DECISION_ANIMATION_DELAY, AI_DECISION_ANIMATION_DELAY_SIMULATION_MODE,
                                   DEMO_MODE_SEED, SHOW_AI_BUILT_LOCATIONS)
from controllers.action_handlers import ActionHandlers
from controllers.controller_support import (MAX_AI_ACTION_REQUESTS_PER_TURN, START_LAST, AITurnActionLimitExceeded,
                                            PlayerScoreSnapshot, ReturnToStart)
from controllers.demo_mode_controller import AdvanceDemoState, DemoModeController
from controllers.demo_state_capture import DemoStateSnapshot
from controllers.initial_placement import InitialPlacementController
from controllers.turn_controller import TurnController
from controllers.tutor_controller import TutorController
from game.Edge import Edge, EdgeDirection
from game.Game import Game, PlayerConfig
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Port, Vertex, VertexDirection
from view.canvas.board_display_source import BoardDisplaySource
from view.View import DemoControl, GameMode, View


class GameController(
    BoardDisplaySource,
    DemoModeController,
    TutorController,
    InitialPlacementController,
    TurnController,
    ActionHandlers,
):
    _game: Game
    game_mode = GameMode.PLAY
    GameMode = GameMode
    SHOW_AI_BUILT_LOCATIONS = SHOW_AI_BUILT_LOCATIONS

    def __init__(self, game_players: PlayerConfig, simulation_players: PlayerConfig, game_seed: int | None = None):
        self.view: View | None = None
        self.game_players = game_players
        self.simulation_players = simulation_players
        self.game_seed = game_seed
        self.game_rng = Random(self._get_active_game_seed())
        self.victory_point_history: list[tuple[int, dict[PlayerNumber, int]]] = []
        self.endgame_review_history: list[tuple[int, dict[PlayerNumber, PlayerScoreSnapshot]]] = []
        self.tutor_feedback_history: list[TutorFeedbackExplanation] = []
        self.round_limit_reached = False
        self.ai_action_limit_reached = False
        self._tutor_dev_played = False
        self._pending_tutor_robber_choice = None
        self._demo_state_index = 0
        self._demo_snapshot_cache: dict[int, DemoStateSnapshot] = {}
        self._demo_snapshot_lock = Lock()
        self._demo_snapshot_condition = Condition(self._demo_snapshot_lock)
        self._demo_snapshot_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="demo-snapshots")
        self._demo_snapshot_pipeline_future: Future[None] | None = None
        self._demo_snapshot_pipeline_error: BaseException | None = None
        self.tutor_ai = self._new_tutor_ai()
        self.tutor_evaluator = TutorEvaluator(self.tutor_ai, lambda: self.game_rng.getstate())
        self.reset_game()

    def run_tutor_decision(self, callback: Callable[[], object]) -> object:
        """Run a decision inside the tutor decision wrapper."""
        return self._run_tutor_decision(callback)

    def get_tutor_recommended_robber_choice(self, player: Player, valid_hexes: list[HexTile]):
        """Return the tutor-recommended robber placement choice."""
        return self._get_tutor_recommended_robber_choice(player, valid_hexes)

    def _resolve_player_config(self) -> PlayerConfig:
        """Resolve the active player configuration for the game mode."""
        if self.game_mode == GameMode.PLAY:
            return self.game_players
        if self.game_mode in {GameMode.TUTOR, GameMode.GUIDED}:
            players = dict(self.simulation_players)
            for player_number, policy_cls in self.game_players.items():
                if policy_cls is None:
                    players[player_number] = None
            return players
        if self.game_mode == GameMode.SIMULATION:
            return self.simulation_players
        return self.game_players

    def _get_active_game_seed(self) -> int | None:
        """Return the seed that should be used for the current game mode."""
        if self.game_mode == GameMode.GUIDED:
            return DEMO_MODE_SEED
        return self.game_seed

    def _should_explain_ai_turns(self) -> bool:
        """Return whether AI turns should render the guided explainer flow."""
        return False

    def _raise_if_view_requested_home(self) -> None:
        """Raise when the view has requested a return home."""
        if self.view is None:
            return
        if self.view.consume_return_home_request():
            raise ReturnToStart

    def _raise_if_return_home(self, value: object) -> None:
        """Raise when a return-home action is received."""
        if isinstance(value, Action) and value.type == ActionType.RETURN_HOME:
            raise ReturnToStart

    def _raise_if_next_demo_state(self, value: object) -> None:
        """Raise when demo mode should advance to the next saved state."""
        if value == DemoControl.NEXT_STATE:
            raise AdvanceDemoState

    def reset_game(self):
        """Reset the game state and supporting controllers."""
        uses_interactive_delay = self.game_mode in {GameMode.PLAY, GameMode.TUTOR}
        is_tutor_mode = self.game_mode in {GameMode.GUIDED, GameMode.TUTOR}

        self.game_rng = Random(self._get_active_game_seed())
        self.victory_point_history = []
        self.endgame_review_history = []
        self.tutor_feedback_history = []
        self.round_limit_reached = False
        self.ai_action_limit_reached = False
        self._tutor_dev_played = False
        self._pending_tutor_robber_choice = None
        self.tutor_ai = self._new_tutor_ai()
        self.tutor_evaluator = TutorEvaluator(self.tutor_ai, lambda: self.game_rng.getstate())
        self._game = Game(self._resolve_player_config(), self.game_rng)

        if self.view:
            self.view.ai_decision_animation_delay = (AI_DECISION_ANIMATION_DELAY if uses_interactive_delay else
                                                     AI_DECISION_ANIMATION_DELAY_SIMULATION_MODE)
            self.view.configure_demo_navigation(False, False)
            self.view.set_window_title_suffix(None)
            self.view.open_tutor_menu(is_tutor_mode)

    def start_game(self, max_rounds: int | None = None):
        """Start and run the full game loop."""
        while True:
            self.game_mode = self.view.display_start_screen()
            self.reset_game()

            try:
                if self.game_mode == GameMode.GUIDED:
                    self._run_demo_mode()
                    return
                self.run_initial_placement()
                while not self._game.game_over:
                    for player in self._game.players:
                        if player.is_human:
                            self.make_round_move(player)
                        else:
                            self.make_round_move_ai(player)

                        for card in player.development_cards:
                            card.playable = card.card_type != DevelopmentCardType.VICTORY_POINT

                        if self._game.game_over:
                            break

                    self._record_victory_point_snapshot()
                    if self._game.game_over:
                        break
                    if max_rounds is not None and self._game.round_num >= max_rounds:
                        self.round_limit_reached = True
                        return
                    self._game.round_num += 1
            except AITurnActionLimitExceeded:
                self.ai_action_limit_reached = True
                return
            except ReturnToStart:
                continue
            self._record_victory_point_snapshot()
            self.view.display_results()
            return

    def get_game_state(self):
        """Return the current game state object."""
        return self._game

    def get_ports(self) -> list[tuple[Port, Vertex, Vertex]]:
        """Return the board ports from the active game."""
        return self._game.get_ports()

    def get_vertex(self, q: int, r: int, corner_index: VertexDirection) -> Vertex | None:
        """Return the vertex from the active game."""
        return self._game.get_vertex(q, r, corner_index)

    def try_build_settlement(
        self,
        player: Player,
        vertex: Vertex,
        build: bool = True,
        use_resources: bool = True,
        road_restriction: bool = True,
    ) -> tuple[bool, str]:
        """Try to build a settlement through the controller workflow."""
        result = self._game.try_build_settlement(player, vertex, build, use_resources, road_restriction)
        success, _ = result
        if success and build:
            self._refresh_tutor_turn_explanation(player)
        return result

    def get_edge(self, q: int, r: int, edge_index: EdgeDirection) -> Edge | None:
        """Return the edge from the active game."""
        return self._game.get_edge(q, r, edge_index)

    def try_build_road(
        self,
        player: Player,
        edge: Edge,
        on_vertex: Vertex | None = None,
        build: bool = True,
        use_resources: bool = True,
    ) -> tuple[bool, str]:
        """Try to build a road through the controller workflow."""
        result = self._game.try_build_road(player, edge, on_vertex, build, use_resources)
        success, _ = result
        if success and build:
            self._refresh_tutor_turn_explanation(player)
        return result

    def get_buildable_options(self, player: Player) -> dict:
        """Return the buildable options from the active game."""
        return self._game.get_buildable_options(player)

    def try_build_city(
        self,
        player: Player,
        vertex: Vertex,
        build: bool = True,
        use_resources: bool = True,
    ) -> tuple[bool, str]:
        """Try to build a city through the controller workflow."""
        result = self._game.try_build_city(player, vertex, build, use_resources)
        success, _ = result
        if success and build:
            self._refresh_tutor_turn_explanation(player)
        return result

    def try_trade_with_bank(
        self,
        player: Player,
        selling: ResourceCount,
        buying: ResourceCount,
        use_resources: bool = True,
    ) -> bool:
        """Try to perform a bank trade through the controller workflow."""
        success = self._game.try_trade_with_bank(player, selling, buying, use_resources)
        if success and use_resources:
            self._refresh_tutor_turn_explanation(player)
        return success

    def trade_between_players(
        self,
        player: Player,
        selling: ResourceCount,
        buying_player: Player,
        buying: ResourceCount,
    ):
        """Run the trade flow between two players."""
        result = self._game.trade_between_players(player, selling, buying_player, buying)
        self._refresh_tutor_turn_explanation(player)
        return result

    def get_available_vertices(
        self,
        player: Player,
        building_type: Buildable,
        road_restriction: bool = True,
    ) -> list[Vertex]:
        """Return the currently available build vertices."""
        return self._game.get_available_vertices(player, building_type, road_restriction)

    def get_buildable_edges_for_vertex(self, vertex: Vertex) -> list[Edge]:
        """Return buildable edges connected to the vertex."""
        return self._game.get_buildable_edges_for_vertex(vertex)

    def get_trade_rate(self, player: Player, resource: Resource) -> int:
        """Return the trade rate for the given player and resource."""
        return self._game.get_trade_rate(player, resource)

    def get_hex_tile(self, q: int, r: int) -> HexTile | None:
        """Return the hex tile from the active game."""
        return self._game.get_hex_tile(q, r)

    def get_players_on_hex(self, hex_tile):
        """Return the players with buildings on the given hex."""
        return self._game.get_players_on_hex(hex_tile)

    def get_all_hexes(self) -> list[HexTile]:
        """Return all hexes from the active game."""
        return self._game.get_all_hexes()

    def get_hex_tiles_with_players(self):
        """Return hexes that currently contain player buildings."""
        return self._game.get_hex_tiles_with_players()

    def try_buy_development_card(self, player) -> tuple[bool, str]:
        """Try to buy a development card through the controller workflow."""
        result = self._game.try_buy_development_card(player)
        success, _ = result
        if success:
            self._refresh_tutor_turn_explanation(player)
        return result

    def get_available_edges(self, player: Player) -> list[Edge]:
        """Return the currently available build edges."""
        return self._game.get_available_edges(player)

    def get_bank_resources(self) -> ResourceCount:
        """Return the bank resources from the active game."""
        return self._game.bank_resources

    def get_all_edges(self):
        """Return all edges from the active game."""
        return self._game.get_all_edges()

    def get_all_vertices(self):
        """Return all vertices from the active game."""
        return self._game.get_all_vertices()

    def get_development_deck(self):
        """Return the development deck from the active game."""
        return self._game.development_deck

    def get_all_players(self):
        """Return all players from the active game."""
        return self._game.players

    def get_victory_point_history(self) -> list[tuple[int, dict[PlayerNumber, int]]]:
        """Return the recorded victory-point history."""
        return list(self.victory_point_history)

    def get_endgame_review_history(self) -> list[tuple[int, dict[PlayerNumber, PlayerScoreSnapshot]]]:
        """Return the recorded endgame review history."""
        return list(self.endgame_review_history)

    def get_tutor_feedback_history(self) -> list[TutorFeedbackExplanation]:
        """Return the recorded tutor feedback history."""
        return list(self.tutor_feedback_history)
