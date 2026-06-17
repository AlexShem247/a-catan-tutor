from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from random import Random
from threading import Condition, Lock
from typing import Any, Callable, Dict, List, Optional, Tuple

from ai.actions import Action, ActionType, Phase
from ai.tutor.evaluator import TutorEvaluator
from ai.tutor.feedback import TutorFeedbackExplanation
from ai.tutor.tutor import TutorStage
from config.demo_states import DEMO_MODE_STATES, DemoStateDefinition
from config.view_constants import (AI_DECISION_ANIMATION_DELAY, AI_DECISION_ANIMATION_DELAY_SIMULATION_MODE,
                                   DEMO_MODE_SEED, SHOW_AI_BUILT_LOCATIONS)
from controllers.action_handlers import ActionHandlers
from controllers.controller_support import (MAX_AI_ACTION_REQUESTS_PER_TURN, START_LAST, AITurnActionLimitExceeded,
                                            PlayerScoreSnapshot, ReturnToStart)
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
from view.HeadlessView import HeadlessView
from view.canvas.board_display_source import BoardDisplaySource
from view.View import DemoControl, GameMode, View


class AdvanceDemoState(Exception):
    pass


_DEMO_CAPTURE_LOCK = Lock()


@dataclass
class DemoStateSnapshot:
    definition: DemoStateDefinition
    decision_kind: str
    game_state: Game
    game_rng_state: object
    victory_point_history: List[Tuple[int, Dict[PlayerNumber, int]]]
    endgame_review_history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]]
    player_number: PlayerNumber
    dice_info: Optional[Tuple[int, int, int]] = None
    played_dev_card: bool = False


class GameController(
        BoardDisplaySource,
        TutorController,
        InitialPlacementController,
        TurnController,
        ActionHandlers,
):
    _game: Game
    game_mode = GameMode.PLAY
    GameMode = GameMode
    SHOW_AI_BUILT_LOCATIONS = SHOW_AI_BUILT_LOCATIONS

    def __init__(self, game_players: PlayerConfig, simulation_players: PlayerConfig, game_seed: Optional[int] = None):
        self.view: View | None = None
        self.game_players = game_players
        self.simulation_players = simulation_players
        self.game_seed = game_seed
        self.game_rng = Random(self._get_active_game_seed())
        self.victory_point_history: List[Tuple[int, Dict[PlayerNumber, int]]] = []
        self.endgame_review_history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]] = []
        self.tutor_feedback_history: List[TutorFeedbackExplanation] = []
        self.round_limit_reached = False
        self.ai_action_limit_reached = False
        self._tutor_dev_played = False
        self._pending_tutor_robber_choice = None
        self._demo_state_index = 0
        self._demo_snapshot_cache: Dict[int, DemoStateSnapshot] = {}
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

    def _get_active_game_seed(self) -> Optional[int]:
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

    @staticmethod
    def _raise_if_next_demo_state(value: object) -> None:
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

    def start_game(self, max_rounds: Optional[int] = None):
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

    def _run_demo_mode(self) -> None:
        """Run demo mode by loading hardcoded tutor states on demand."""
        self._demo_state_index = 0
        self._prefetch_demo_states(0)
        while True:
            definition = DEMO_MODE_STATES[self._demo_state_index]
            has_next = self._demo_state_index < len(DEMO_MODE_STATES) - 1
            try:
                self._run_demo_state(definition, has_next)
                navigation = self.view.wait_for_demo_next_state()
                self._raise_if_return_home(navigation)
                self._raise_if_next_demo_state(navigation)
            except AdvanceDemoState:
                if has_next:
                    self._demo_state_index += 1
                    continue
                self._finish_demo_from_state(definition)
                return

    def _run_demo_state(self, definition: DemoStateDefinition, has_next: bool) -> None:
        """Load a single demo state and run the resumed tutor flow."""
        snapshot = self._get_demo_state_snapshot(definition)
        self._restore_demo_state(snapshot)
        self.view.configure_demo_navigation(True, has_next)
        self.view.set_window_title_suffix(
            f"State {definition.demoStateNumber}/{len(DEMO_MODE_STATES)} - {definition.description}")
        self._prefetch_demo_states(self._demo_state_index + 1)
        if snapshot.decision_kind == "INITIAL_SETTLEMENT":
            self._run_demo_initial_settlement(snapshot)
        elif snapshot.decision_kind == "INITIAL_ROAD":
            self._run_demo_initial_road(snapshot)
        elif snapshot.decision_kind == "DISCARD":
            self._run_demo_discard(snapshot)
        elif snapshot.decision_kind == "ROBBER_PLACEMENT":
            self._run_demo_robber_placement(snapshot)
        elif snapshot.decision_kind == "ROBBER_STEAL_TARGET":
            self._run_demo_robber_steal_target(snapshot)
        elif snapshot.decision_kind == "MAIN_TURN":
            self._run_demo_main_turn(snapshot)
        else:
            raise RuntimeError(f"Unsupported demo decision kind: {snapshot.decision_kind}")

    def _get_demo_state_snapshot(self, definition: DemoStateDefinition) -> DemoStateSnapshot:
        """Return a cached demo snapshot, waiting for background work when available."""
        self._prefetch_demo_states(self._demo_state_index)
        with self._demo_snapshot_condition:
            while True:
                cached = self._demo_snapshot_cache.get(definition.moveNumber)
                if cached is not None:
                    return cached
                if self._demo_snapshot_pipeline_error is not None:
                    raise RuntimeError("Demo snapshot precompute failed.") from self._demo_snapshot_pipeline_error
                future = self._demo_snapshot_pipeline_future
                if future is None or future.done():
                    break
                self._demo_snapshot_condition.wait()

        snapshot = self._capture_demo_state(definition)
        with self._demo_snapshot_condition:
            self._demo_snapshot_cache[definition.moveNumber] = snapshot
            self._demo_snapshot_condition.notify_all()
        return snapshot

    def _prefetch_demo_states(self, start_index: int) -> None:
        """Ensure a forward background replay is generating later demo states."""
        if start_index >= len(DEMO_MODE_STATES):
            return
        with self._demo_snapshot_condition:
            remaining_definitions = DEMO_MODE_STATES[start_index:]
            if all(definition.moveNumber in self._demo_snapshot_cache for definition in remaining_definitions):
                return
            if self._demo_snapshot_pipeline_future is not None and not self._demo_snapshot_pipeline_future.done():
                return
            self._demo_snapshot_pipeline_error = None
            self._demo_snapshot_pipeline_future = self._demo_snapshot_executor.submit(
                self._capture_demo_state_sequence,
                start_index,
            )

    def _capture_demo_state(self, definition: DemoStateDefinition) -> DemoStateSnapshot:
        """Simulate the fixed-seed tutor game until the requested move number."""
        with _DEMO_CAPTURE_LOCK:
            return self._capture_demo_state_unlocked(definition)

    def _capture_demo_state_sequence(self, start_index: int) -> None:
        """Generate remaining demo snapshots in one deterministic forward replay."""
        try:
            with _DEMO_CAPTURE_LOCK:
                self._capture_demo_state_sequence_unlocked(start_index)
        except BaseException as exc:
            with self._demo_snapshot_condition:
                self._demo_snapshot_pipeline_error = exc
                self._demo_snapshot_condition.notify_all()
            raise
        else:
            with self._demo_snapshot_condition:
                self._demo_snapshot_condition.notify_all()

    def _capture_demo_state_sequence_unlocked(self, start_index: int) -> None:
        """Simulate once and capture all remaining configured demo states in order."""
        definitions = DEMO_MODE_STATES[start_index:]
        if not definitions:
            return

        collector = _DemoStateCollectorController(
            game_players=self.game_players,
            simulation_players=self.simulation_players,
            game_seed=DEMO_MODE_SEED,
        )
        collector.game_mode = GameMode.TUTOR
        collector.reset_game()
        collector_view = _DemoStateSequenceCollectorView(collector, definitions, self._store_demo_state_snapshot)
        collector.view = collector_view
        try:
            collector.start_game()
        except _DemoStateSequenceCapturedAll:
            return
        missing_move = next(
            (definition.moveNumber for definition in definitions
             if definition.moveNumber not in self._demo_snapshot_cache),
            None,
        )
        if missing_move is not None:
            raise RuntimeError(f"Demo state move {missing_move} was not found.")

    def _store_demo_state_snapshot(self, snapshot: DemoStateSnapshot) -> None:
        """Store a demo snapshot produced by the background replay worker."""
        with self._demo_snapshot_condition:
            self._demo_snapshot_cache[snapshot.definition.moveNumber] = snapshot
            self._demo_snapshot_condition.notify_all()

    def _capture_demo_state_unlocked(self, definition: DemoStateDefinition) -> DemoStateSnapshot:
        """Simulate the fixed-seed tutor game until the requested move number."""
        collector = _DemoStateCollectorController(
            game_players=self.game_players,
            simulation_players=self.simulation_players,
            game_seed=DEMO_MODE_SEED,
        )
        collector.game_mode = GameMode.TUTOR
        collector.reset_game()
        collector_view = _DemoStateCollectorView(collector, definition)
        collector.view = collector_view
        try:
            collector.start_game()
        except _DemoStateCaptured as captured:
            return captured.snapshot
        raise RuntimeError(f"Demo state move {definition.moveNumber} was not found.")

    def _restore_demo_state(self, snapshot: DemoStateSnapshot) -> None:
        """Restore the live controller to the captured demo snapshot."""
        self._game = deepcopy(snapshot.game_state)
        self.game_rng = Random()
        self.game_rng.setstate(snapshot.game_rng_state)
        self._bind_restored_game_rng()
        self._pending_tutor_robber_choice = None
        self._tutor_dev_played = snapshot.played_dev_card
        self.victory_point_history = deepcopy(snapshot.victory_point_history)
        self.endgame_review_history = deepcopy(snapshot.endgame_review_history)
        self.tutor_ai = self._new_tutor_ai()
        self.tutor_evaluator = TutorEvaluator(self.tutor_ai, lambda: self.game_rng.getstate())
        self.view.open_tutor_menu(True)

    def _bind_restored_game_rng(self) -> None:
        """Point all restored game RNG references at the controller RNG."""
        self._game.rng = self.game_rng
        self._bind_rng_references(self._game, set())

    def _bind_rng_references(self, value: object, visited: set[int]) -> None:
        """Recursively replace copied RNG references in a restored object graph."""
        value_id = id(value)
        if value_id in visited:
            return
        visited.add(value_id)

        if isinstance(value, dict):
            for key, item in value.items():
                self._bind_rng_references(key, visited)
                self._bind_rng_references(item, visited)
            return

        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                self._bind_rng_references(item, visited)
            return

        attributes = getattr(value, "__dict__", None)
        if attributes is None:
            return

        if "rng" in attributes:
            setattr(value, "rng", self.game_rng)
        for item in attributes.values():
            if isinstance(item, Random):
                continue
            self._bind_rng_references(item, visited)

    def _find_player(self, player_number: PlayerNumber) -> Player:
        """Return the current game player for the given player number."""
        return next(player for player in self._game.players if player.player_number == player_number)

    def _run_demo_initial_settlement(self, snapshot: DemoStateSnapshot) -> None:
        """Resume the opening settlement segment for the captured demo state."""
        player = self._find_player(snapshot.player_number)
        vertices = self._game.get_available_vertices(player, Buildable.SETTLEMENT, road_restriction=False)
        explanation = self._preview_tutor_explanation(
            lambda: self.tutor_ai.select_initial_settlement_location_with_explanation(
                player,
                self._game,
                vertices,
            ))
        self.view.display_tutor_init(player, TutorStage.INITIAL_SETTLEMENT, explanation)
        self.view.display_board(player, "Select a position to build your settlement")

        def select_tutor_initial_settlement() -> Optional[Vertex]:
            return self._run_tutor_decision(
                lambda: self.tutor_ai.select_initial_settlement_location(player, self._game, vertices))

        self._set_tutor_shortcut_handlers(select_tutor_initial_settlement)
        try:
            vertex = self.view.draw_selectable_vertices(vertices)
        finally:
            self._set_tutor_shortcut_handlers(None)
        self._raise_if_return_home(vertex)
        self._raise_if_next_demo_state(vertex)
        opening_settlement_feedback = self.tutor_evaluator.evaluate_opening_settlement_choice(
            player,
            self._game,
            vertices,
            vertex,
            title="Opening Settlement",
        )
        self._game.try_build_settlement(
            player,
            vertex,
            use_resources=False,
            road_restriction=False,
            gain_resources=False,
        )
        self._show_tutor_action_feedback(player, opening_settlement_feedback)

        available_edges = [edge for edge in self._game.get_available_edges(player) if vertex in edge.vertices]
        explanation = self._preview_tutor_explanation(
            lambda: self.tutor_ai.select_initial_road_location_with_explanation(
                player,
                self._game,
                available_edges,
            ))
        self.view.display_tutor_init(player, TutorStage.INITIAL_ROAD, explanation)
        edge = self.get_road_choice(
            player,
            vertex,
            selector=lambda candidate_edges: self.tutor_ai.select_initial_road_location(
                player, self._game, candidate_edges),
        )
        self._raise_if_next_demo_state(edge)
        opening_road_feedback = self.tutor_evaluator.evaluate_opening_road_choice(
            player,
            self._game,
            available_edges,
            edge,
            title="Opening Road",
        )
        self._game.try_build_road(player, edge, use_resources=False)
        self._show_tutor_action_feedback(player, opening_road_feedback)

    def _run_demo_initial_road(self, snapshot: DemoStateSnapshot) -> None:
        """Resume the opening road segment for the captured demo state."""
        player = self._find_player(snapshot.player_number)
        if not player.settlements:
            raise RuntimeError("Initial-road demo state is missing the player's opening settlement.")

        settlement = player.settlements[-1]
        available_edges = [edge for edge in self._game.get_available_edges(player) if settlement in edge.vertices]
        explanation = self._preview_tutor_explanation(
            lambda: self.tutor_ai.select_initial_road_location_with_explanation(
                player,
                self._game,
                available_edges,
            ))
        self.view.display_tutor_init(player, TutorStage.INITIAL_ROAD, explanation)
        edge = self.get_road_choice(
            player,
            settlement,
            selector=lambda candidate_edges: self.tutor_ai.select_initial_road_location(
                player, self._game, candidate_edges),
        )
        self._raise_if_next_demo_state(edge)
        opening_road_feedback = self.tutor_evaluator.evaluate_opening_road_choice(
            player,
            self._game,
            available_edges,
            edge,
            title="Opening Road",
        )
        self._game.try_build_road(player, edge, use_resources=False)
        self._show_tutor_action_feedback(player, opening_road_feedback)

    def _run_demo_discard(self, snapshot: DemoStateSnapshot) -> None:
        """Resume a robber discard decision for the captured demo state."""
        player = self._find_player(snapshot.player_number)
        discard_count = player.calculate_discard_count()
        if discard_count <= 0:
            raise RuntimeError("Discard demo state has no resources to discard.")

        explanation = self._preview_tutor_explanation(
            lambda: self.tutor_ai.select_discard_resources_with_explanation(
                player,
                self._game,
                discard_count,
            ))
        self._show_tutor_init(player, TutorStage.DISCARD_RESOURCES, explanation)

        def select_tutor_discard_resources() -> ResourceCount:
            return self._run_tutor_decision(
                lambda: self.tutor_ai.select_discard_resources(player, self._game, discard_count))

        self._set_tutor_shortcut_handlers(select_tutor_discard_resources)
        try:
            resources_to_discard = self.view.show_resource_chooser(
                player,
                discard_count,
                "The robber has been rolled!",
                player.resources,
            )
        finally:
            self._set_tutor_shortcut_handlers(None)
        self._raise_if_return_home(resources_to_discard)
        self._raise_if_next_demo_state(resources_to_discard)
        discard_feedback = self.tutor_evaluator.evaluate_discard_choice(
            player,
            self._game,
            resources_to_discard,
            discard_count,
            title="Discard",
        )
        player.remove_resources(resources_to_discard)
        self._show_tutor_action_feedback(player, discard_feedback)

    def _run_demo_robber_placement(self, snapshot: DemoStateSnapshot) -> None:
        """Resume a robber placement decision for the captured demo state."""
        player = self._find_player(snapshot.player_number)
        available_hexes = [tile for tile in self._game.get_all_hexes() if not tile.robber]
        explanation = self._preview_tutor_explanation(
            lambda: self.tutor_ai.select_robber_target_with_explanation(
                player,
                self._game,
                available_hexes,
            ))
        self._show_tutor_init(player, TutorStage.ROBBER_PLACEMENT, explanation)
        self.view.display_board(player, "Select a hex to move the robber")

        def select_tutor_robber_hex() -> HexTile:
            return self._get_tutor_recommended_robber_choice(player, available_hexes)[0]

        self._set_tutor_shortcut_handlers(select_tutor_robber_hex)
        try:
            selected_hex = self.view.draw_selectable_tiles(available_hexes)
        finally:
            self._set_tutor_shortcut_handlers(None)
        self._raise_if_return_home(selected_hex)
        self._raise_if_next_demo_state(selected_hex)
        robber_placement_feedback = self.tutor_evaluator.evaluate_robber_choice(
            player,
            self._game,
            available_hexes,
            selected_hex,
            None,
            title="Robber",
        )
        self._game.set_robber(selected_hex)
        self._show_tutor_action_feedback(player, robber_placement_feedback)

        adjacent_player_buildings = [
            vertex for vertex in selected_hex.vertices
            if vertex.owner is not None and vertex.owner != player and any(vertex.owner.resources.values())
        ]
        if adjacent_player_buildings:
            self._run_demo_robber_steal_target(snapshot)

    def _run_demo_robber_steal_target(self, snapshot: DemoStateSnapshot) -> None:
        """Resume a robber steal-target decision for the captured demo state."""
        player = self._find_player(snapshot.player_number)
        selected_hex = self._game.get_robber_tile()
        adjacent_player_buildings = [
            vertex for vertex in selected_hex.vertices
            if vertex.owner is not None and vertex.owner != player and any(vertex.owner.resources.values())
        ]
        if not adjacent_player_buildings:
            return

        explanation = self._preview_tutor_explanation(
            lambda: self.tutor_ai.select_robber_target_with_explanation(
                player,
                self._game,
                [selected_hex],
            ))
        self._show_tutor_init(player, TutorStage.ROBBER_STEAL_TARGET, explanation)
        self.view.display_board(player, "Select a player to steal from")

        def select_tutor_robber_target_building() -> Vertex:
            selected_owner = self._get_tutor_recommended_robber_choice(player, [selected_hex])[1]
            return next(
                (building for building in adjacent_player_buildings if building.owner == selected_owner),
                adjacent_player_buildings[0],
            )

        self._set_tutor_shortcut_handlers(select_tutor_robber_target_building)
        try:
            selected_player_building = self.view.draw_selectable_vertices(adjacent_player_buildings)
        finally:
            self._set_tutor_shortcut_handlers(None)
        self._raise_if_return_home(selected_player_building)
        self._raise_if_next_demo_state(selected_player_building)
        selected_player = selected_player_building.owner
        robber_target_feedback = self.tutor_evaluator.evaluate_robber_choice(
            player,
            self._game,
            [selected_hex],
            selected_hex,
            selected_player,
            title="Robber",
        )
        self._show_tutor_action_feedback(player, robber_target_feedback)

        if selected_player is not None:
            resource = selected_player.random_resource()
            if resource:
                self._game.trade_between_players(player, {}, selected_player, resource)

    def _run_demo_main_turn(self, snapshot: DemoStateSnapshot) -> None:
        """Resume the captured main-turn state without simulating later AI turns."""
        player = self._find_player(snapshot.player_number)
        if snapshot.dice_info is None:
            raise RuntimeError("Main-turn demo state is missing dice information.")
        self._tutor_dev_played = snapshot.played_dev_card
        self._run_main_turn_loop(player, snapshot.dice_info, snapshot.played_dev_card)

    def _finish_demo_from_state(self, definition: DemoStateDefinition) -> None:
        """Ignore the live demo move, replay the final demo state with tutor choices, and finish the game."""
        snapshot = self._get_demo_state_snapshot(definition)
        self._restore_demo_state(snapshot)
        original_view = self.view
        auto_view = _DemoAutoPlayView(self)
        self.view = auto_view
        try:
            if snapshot.decision_kind == "MAIN_TURN":
                player = self._find_player(snapshot.player_number)
                if snapshot.dice_info is None:
                    raise RuntimeError("Main-turn demo state is missing dice information.")
                self._tutor_dev_played = snapshot.played_dev_card
                self._run_main_turn_loop(player, snapshot.dice_info, snapshot.played_dev_card)
                self._complete_game_after_player_turn(snapshot.player_number)
            elif snapshot.decision_kind in {"DISCARD", "ROBBER_PLACEMENT", "ROBBER_STEAL_TARGET"}:
                self._finish_demo_from_robber_state(snapshot)
            else:
                raise RuntimeError(f"Finish-demo flow does not support {snapshot.decision_kind}.")
        finally:
            self.view = original_view
            if self.view is not None:
                self.view.configure_demo_navigation(False, False)
                self.view.set_window_title_suffix(None)
        self._record_victory_point_snapshot()
        self.view.display_results()

    def _finish_demo_from_robber_state(self, snapshot: DemoStateSnapshot) -> None:
        """Replay a captured robber-flow decision and continue the game."""
        player = self._find_player(snapshot.player_number)
        if snapshot.dice_info is None:
            raise RuntimeError(f"{snapshot.decision_kind} demo state is missing dice information.")

        if snapshot.decision_kind == "DISCARD":
            self._run_demo_discard(snapshot)
            self.handle_robber_action(player)
        elif snapshot.decision_kind == "ROBBER_PLACEMENT":
            self._run_demo_robber_placement(snapshot)
        elif snapshot.decision_kind == "ROBBER_STEAL_TARGET":
            self._run_demo_robber_steal_target(snapshot)

        self._run_main_turn_loop(player, snapshot.dice_info, snapshot.played_dev_card)
        self._complete_game_after_player_turn(snapshot.player_number)

    def _complete_game_after_player_turn(self, completed_player_number: PlayerNumber) -> None:
        """Finish the current game after the given player's turn has completed."""
        player_order = self._game.players
        start_index = next(
            index for index, player in enumerate(player_order) if player.player_number == completed_player_number)

        next_index = start_index + 1
        while not self._game.game_over:
            for player in player_order[next_index:]:
                if player.is_human:
                    self.make_round_move(player)
                else:
                    self.make_round_move_ai(player)

                for card in player.development_cards:
                    card.playable = card.card_type != DevelopmentCardType.VICTORY_POINT

                if self._game.game_over:
                    break

            if self._game.game_over:
                break

            self._record_victory_point_snapshot()
            self._game.round_num += 1
            next_index = 0

    def _record_victory_point_snapshot(self) -> None:
        """Record the current victory-point snapshot."""
        review_snapshot = {
            player.player_number: self._build_player_score_snapshot(player)
            for player in self._game.players
        }
        snapshot = {
            player_number: player_snapshot.total_vp
            for player_number, player_snapshot in review_snapshot.items()
        }
        round_num = self._game.round_num
        if self.victory_point_history and self.victory_point_history[-1] == (round_num, snapshot):
            return
        self.victory_point_history.append((round_num, snapshot))
        self.endgame_review_history.append((round_num, review_snapshot))

    @staticmethod
    def _build_player_score_snapshot(player: Player) -> PlayerScoreSnapshot:
        """Build a score snapshot for the given player."""
        visible_vp, total_vp = player.calc_victory_points()
        return PlayerScoreSnapshot(
            total_vp=total_vp,
            visible_vp=visible_vp,
            settlements=len(player.settlements),
            cities=len(player.cities),
            hidden_vp_cards=total_vp - visible_vp,
            longest_road_length=player.longest_road_length,
            army_size=player.army_size,
            has_longest_road=player.has_longest_road,
            has_largest_army=player.has_largest_army,
        )

    def get_game_state(self):
        """Return the current game state object."""
        return self._game

    def get_ports(self) -> List[Tuple[Port, Vertex, Vertex]]:
        """Return the board ports from the active game."""
        return self._game.get_ports()

    def get_vertex(self, q: int, r: int, corner_index: VertexDirection) -> Optional[Vertex]:
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

    def get_edge(self, q: int, r: int, edge_index: EdgeDirection) -> Optional[Edge]:
        """Return the edge from the active game."""
        return self._game.get_edge(q, r, edge_index)

    def try_build_road(
        self,
        player: Player,
        edge: Edge,
        on_vertex: Optional[Vertex] = None,
        build: bool = True,
        use_resources: bool = True,
    ) -> tuple[bool, str]:
        """Try to build a road through the controller workflow."""
        result = self._game.try_build_road(player, edge, on_vertex, build, use_resources)
        success, _ = result
        if success and build:
            self._refresh_tutor_turn_explanation(player)
        return result

    def get_buildable_options(self, player: Player) -> Dict:
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

    def try_trade_with_bank(self, player: Player, selling: ResourceCount, buying: ResourceCount,
                            use_resources: bool = True) -> bool:
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

    def get_available_vertices(self, player: Player, building_type: Buildable,
                               road_restriction: bool = True) -> List[Vertex]:
        """Return the currently available build vertices."""
        return self._game.get_available_vertices(player, building_type, road_restriction)

    def get_buildable_edges_for_vertex(self, vertex: Vertex) -> List[Edge]:
        """Return buildable edges connected to the vertex."""
        return self._game.get_buildable_edges_for_vertex(vertex)

    def get_trade_rate(self, player: Player, resource: Resource) -> int:
        """Return the trade rate for the given player and resource."""
        return self._game.get_trade_rate(player, resource)

    def get_hex_tile(self, q: int, r: int) -> Optional[HexTile]:
        """Return the hex tile from the active game."""
        return self._game.get_hex_tile(q, r)

    def get_players_on_hex(self, hex_tile):
        """Return the players with buildings on the given hex."""
        return self._game.get_players_on_hex(hex_tile)

    def get_all_hexes(self) -> List[HexTile]:
        """Return all hexes from the active game."""
        return self._game.get_all_hexes()

    def get_hex_tiles_with_players(self):
        """Return hexes that currently contain player buildings."""
        return self._game.get_hex_tiles_with_players()

    def try_buy_development_card(self, player) -> Tuple[bool, str]:
        """Try to buy a development card through the controller workflow."""
        result = self._game.try_buy_development_card(player)
        success, _ = result
        if success:
            self._refresh_tutor_turn_explanation(player)
        return result

    def get_available_edges(self, player: Player) -> List[Edge]:
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

    def get_victory_point_history(self) -> List[Tuple[int, Dict[PlayerNumber, int]]]:
        """Return the recorded victory-point history."""
        return list(self.victory_point_history)

    def get_endgame_review_history(self) -> List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]]:
        """Return the recorded endgame review history."""
        return list(self.endgame_review_history)

    def get_tutor_feedback_history(self) -> List[TutorFeedbackExplanation]:
        """Return the recorded tutor feedback history."""
        return list(self.tutor_feedback_history)


class _DemoStateCaptured(Exception):
    def __init__(self, snapshot: DemoStateSnapshot):
        self.snapshot = snapshot
        super().__init__(f"Captured demo state for move {snapshot.definition.moveNumber}.")


class _DemoStateSequenceCapturedAll(Exception):
    pass


class _DemoStateCollectorController(GameController):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_human_player: Optional[Player] = None
        self.current_dice_info: Optional[Tuple[int, int, int]] = None

    def make_round_move(self, player: Player):
        self.current_human_player = player
        try:
            return super().make_round_move(player)
        finally:
            self.current_human_player = None
            self.current_dice_info = None

    def roll_dice(self, player: Player):
        result = super().roll_dice(player)
        self.current_dice_info = result[:3]
        return result

    def _record_current_dice_info(self, dice_info: Tuple[int, int, int]) -> None:
        """Record dice info as soon as it is available during capture."""
        self.current_dice_info = dice_info


class _DemoStateCollectorView(HeadlessView):
    def __init__(self, controller: _DemoStateCollectorController, definition: DemoStateDefinition):
        self.controller = controller
        self.definition = definition
        self._decision_index = 0
        self._debug_tutor_shortcut_handler: Optional[Callable[[], Any]] = None
        self._latest_stage: Optional[TutorStage] = None
        self._latest_player: Optional[Player] = None

    def display_start_screen(self) -> GameMode:
        return GameMode.TUTOR

    def set_debug_tutor_shortcut_handler(self, handler):
        self._debug_tutor_shortcut_handler = handler

    def display_tutor_init(self, player: Player, stage: TutorStage, explanation) -> None:
        self._latest_stage = stage
        self._latest_player = player

    def display_board_turn(self, player: Player, dice_info: Tuple[int, int, int], played_dev_card: bool = False):
        self._increment_or_capture(
            decision_kind="MAIN_TURN",
            player=player,
            dice_info=dice_info,
            played_dev_card=played_dev_card,
        )
        return self.controller.get_tutor_recommended_main_action(player, played_dev_card)

    def pre_roll(self, player: Player):
        self._increment_or_capture("PRE_ROLL", player)
        recommended_action = self.controller._run_tutor_decision(
            lambda: self.controller.tutor_ai.next_action(player, self.controller.get_game_state(), Phase.PRE_ROLL, False))
        if recommended_action.type == ActionType.PLAY_DEV_CARD:
            return recommended_action.payload
        return False

    def draw_selectable_vertices(self, vertices: List[Vertex], disable_interactivity: bool = False) -> Vertex:
        if disable_interactivity:
            return vertices[0]
        if self._latest_stage == TutorStage.INITIAL_SETTLEMENT:
            decision_kind = "INITIAL_SETTLEMENT"
        elif self._latest_stage == TutorStage.ROBBER_STEAL_TARGET:
            decision_kind = "ROBBER_STEAL_TARGET"
        else:
            decision_kind = "VERTEX"
        self._increment_or_capture(decision_kind, self._latest_player or self.controller.current_human_player)
        choice = self._call_debug_handler(vertices[0])
        self._latest_stage = None
        self._latest_player = None
        return choice

    def draw_selectable_edges(self, edges: List[Edge], disable_interactivity: bool = False) -> Edge:
        if disable_interactivity:
            return edges[0]
        self._increment_or_capture("INITIAL_ROAD" if self._latest_stage == TutorStage.INITIAL_ROAD else "EDGE",
                                   self._latest_player or self.controller.current_human_player)
        choice = self._call_debug_handler(edges[0])
        self._latest_stage = None
        self._latest_player = None
        return choice

    def draw_selectable_tiles(self, tiles: List[HexTile]) -> HexTile:
        self._increment_or_capture("ROBBER_PLACEMENT", self._latest_player or self.controller.current_human_player)
        self._latest_stage = None
        self._latest_player = None
        return self._call_debug_handler(tiles[0])

    def show_resource_chooser(self, player: Player, num_resources: int, title: str,
                              resource_caps: Optional[ResourceCount] = None) -> ResourceCount:
        if self._latest_stage == TutorStage.DISCARD_RESOURCES:
            decision_kind = "DISCARD"
        elif self._latest_stage == TutorStage.YEAR_OF_PLENTY:
            decision_kind = "YEAR_OF_PLENTY"
        elif self._latest_stage == TutorStage.MONOPOLY:
            decision_kind = "MONOPOLY"
        else:
            decision_kind = "RESOURCE_CHOICE"
        self._increment_or_capture(decision_kind, player)
        self._latest_stage = None
        self._latest_player = None
        return self._call_debug_handler({})

    def display_trade_manager(self, player: Player, selling: ResourceCount, buying: ResourceCount,
                              selling_player: Player):
        self._increment_or_capture("TRADE_RESPONSE", player)
        self._latest_stage = None
        self._latest_player = None
        return self._call_debug_handler((False, None))

    def select_player_trade_offer(
        self,
        player: Player,
        selling: ResourceCount,
        buying: ResourceCount,
        willing_players: List[Tuple[Player, Optional[ResourceCount]]],
    ):
        self._increment_or_capture("TRADE_PARTNER", player)
        self._latest_stage = None
        self._latest_player = None
        return self._call_debug_handler(willing_players[0] if willing_players else None)

    def _call_debug_handler(self, fallback: Any) -> Any:
        if self._debug_tutor_shortcut_handler is None:
            return fallback
        result = self._debug_tutor_shortcut_handler()
        return fallback if result is None else result

    def _increment_or_capture(
        self,
        decision_kind: str,
        player: Optional[Player],
        dice_info: Optional[Tuple[int, int, int]] = None,
        played_dev_card: bool = False,
    ) -> None:
        self._decision_index += 1
        if self._decision_index != self.definition.moveNumber:
            return
        snapshot = self._build_snapshot(decision_kind, player, dice_info, played_dev_card, self.definition)
        raise _DemoStateCaptured(snapshot)

    def _build_snapshot(
        self,
        decision_kind: str,
        player: Optional[Player],
        dice_info: Optional[Tuple[int, int, int]],
        played_dev_card: bool,
        definition: DemoStateDefinition,
    ) -> DemoStateSnapshot:
        """Build a demo snapshot from the collector's current state."""
        if decision_kind not in {
            "INITIAL_SETTLEMENT",
            "INITIAL_ROAD",
            "DISCARD",
            "ROBBER_PLACEMENT",
            "ROBBER_STEAL_TARGET",
            "MAIN_TURN",
        }:
            raise RuntimeError(
                f"Demo state move {definition.moveNumber} resolved to unsupported phase {decision_kind}.")
        if player is None:
            raise RuntimeError("Demo state capture did not resolve a player.")
        return DemoStateSnapshot(
            definition=definition,
            decision_kind=decision_kind,
            game_state=deepcopy(self.controller.get_game_state()),
            game_rng_state=self.controller.game_rng.getstate(),
            victory_point_history=deepcopy(self.controller.get_victory_point_history()),
            endgame_review_history=deepcopy(self.controller.get_endgame_review_history()),
            player_number=player.player_number,
            dice_info=dice_info or self.controller.current_dice_info,
            played_dev_card=played_dev_card,
        )


class _DemoStateSequenceCollectorView(_DemoStateCollectorView):
    def __init__(
        self,
        controller: _DemoStateCollectorController,
        definitions: List[DemoStateDefinition],
        snapshot_callback: Callable[[DemoStateSnapshot], None],
    ):
        super().__init__(controller, definitions[0])
        self.definitions = definitions
        self.snapshot_callback = snapshot_callback
        self._target_index = 0

    def _increment_or_capture(
        self,
        decision_kind: str,
        player: Optional[Player],
        dice_info: Optional[Tuple[int, int, int]] = None,
        played_dev_card: bool = False,
    ) -> None:
        self._decision_index += 1
        while self._target_index < len(self.definitions):
            definition = self.definitions[self._target_index]
            if self._decision_index < definition.moveNumber:
                return
            if self._decision_index > definition.moveNumber:
                raise RuntimeError(f"Demo state move {definition.moveNumber} was skipped during precompute.")
            snapshot = self._build_snapshot(decision_kind, player, dice_info, played_dev_card, definition)
            self.snapshot_callback(snapshot)
            self._target_index += 1
            if self._target_index >= len(self.definitions):
                raise _DemoStateSequenceCapturedAll
            return


class _DemoAutoPlayView(HeadlessView):
    def __init__(self, controller: GameController):
        self.controller = controller
        self._latest_stage: Optional[TutorStage] = None
        self._latest_player: Optional[Player] = None
        self._latest_robber_hex: Optional[HexTile] = None

    def display_tutor_init(self, player: Player, stage: TutorStage, explanation) -> None:
        self._latest_stage = stage
        self._latest_player = player

    def display_board_turn(self, player: Player, dice_info: Tuple[int, int, int], played_dev_card: bool = False):
        return self.controller.get_tutor_recommended_main_action(player, played_dev_card)

    def pre_roll(self, player: Player):
        recommended_action = self.controller._run_tutor_decision(
            lambda: self.controller.tutor_ai.next_action(player, self.controller.get_game_state(), Phase.PRE_ROLL, False))
        if recommended_action.type == ActionType.PLAY_DEV_CARD:
            return recommended_action.payload
        return False

    def draw_selectable_vertices(self, vertices: List[Vertex], disable_interactivity: bool = False) -> Vertex:
        if disable_interactivity:
            return vertices[0]
        player = self._latest_player
        if player is not None and self._latest_stage == TutorStage.ROBBER_STEAL_TARGET:
            robber_hex = self._latest_robber_hex or self.controller.get_game_state().get_robber_tile()
            _, selected_owner = self.controller.get_tutor_recommended_robber_choice(player, [robber_hex])
            for vertex in vertices:
                if vertex.owner == selected_owner:
                    return vertex
        return vertices[0]

    def draw_selectable_edges(self, edges: List[Edge], disable_interactivity: bool = False) -> Edge:
        if disable_interactivity:
            return edges[0]
        player = self._latest_player
        if player is not None:
            if self._latest_stage == TutorStage.ROAD_BUILDING:
                return self.controller._run_tutor_decision(
                    lambda: self.controller.tutor_ai.road_building_placement(player, self.controller.get_game_state(), edges))
            if self._latest_stage == TutorStage.INITIAL_ROAD:
                return self.controller._run_tutor_decision(
                    lambda: self.controller.tutor_ai.select_initial_road_location(player, self.controller.get_game_state(), edges))
        return edges[0]

    def draw_selectable_tiles(self, tiles: List[HexTile]) -> HexTile:
        player = self._latest_player
        if player is not None:
            chosen_hex, _ = self.controller.get_tutor_recommended_robber_choice(player, tiles)
            self._latest_robber_hex = chosen_hex
            return chosen_hex
        return tiles[0]

    def show_resource_chooser(self, player: Player, num_resources: int, title: str,
                              resource_caps: Optional[ResourceCount] = None) -> ResourceCount:
        if self._latest_stage == TutorStage.DISCARD_RESOURCES:
            return self.controller._run_tutor_decision(
                lambda: self.controller.tutor_ai.select_discard_resources(player, self.controller.get_game_state(), num_resources))
        if self._latest_stage == TutorStage.YEAR_OF_PLENTY:
            return self.controller._run_tutor_decision(
                lambda: self.controller.tutor_ai.select_year_of_plenty_resources(player, self.controller.get_game_state()))
        if self._latest_stage == TutorStage.MONOPOLY:
            resource = self.controller._run_tutor_decision(
                lambda: self.controller.tutor_ai.select_monopoly_resource(player, self.controller.get_game_state()))
            return {resource: 1}
        return {}

    def display_trade_manager(self, player: Player, selling: ResourceCount, buying: ResourceCount,
                              selling_player: Player):
        return self.controller._run_tutor_decision(
            lambda: self.controller.tutor_ai.respond_to_trade(
                player,
                self.controller.get_game_state(),
                selling_player,
                selling,
                buying,
            ))

    def select_player_trade_offer(
        self,
        player: Player,
        selling: ResourceCount,
        buying: ResourceCount,
        willing_players: List[Tuple[Player, Optional[ResourceCount]]],
    ):
        affordable_offers = [
            (candidate_player, counter)
            for candidate_player, counter in willing_players
            if counter is None or player.can_afford(counter)
        ]
        if not affordable_offers:
            return None
        return self.controller._run_tutor_decision(
            lambda: self.controller.tutor_ai.choose_trade_partner(
                player,
                self.controller.get_game_state(),
                selling,
                buying,
                affordable_offers,
            ))
