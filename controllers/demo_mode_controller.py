from __future__ import annotations

from abc import ABC
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from random import Random
from threading import Condition, Lock

from ai.actions import Action, ActionType
from ai.tutor.evaluator import TutorEvaluator
from ai.tutor.tutor import TutorStage
from config.demo_states import DEMO_MODE_STATES, DemoStateDefinition
from config.view_constants import DEMO_MODE_SEED
from controllers.controller_support import ControllerSupport, PlayerScoreSnapshot
from controllers.demo_state_capture import (DemoAutoPlayView, DemoStateCollectorView, DemoStateSequenceCollectorView,
                                            DemoStateSnapshot, _DemoStateCaptured, _DemoStateSequenceCapturedAll,
                                            create_demo_state_collector_controller)
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import ResourceCount
from game.Vertex import Vertex
from view.View import DemoControl, GameMode


class AdvanceDemoState(Exception):
    pass


_DEMO_CAPTURE_LOCK = Lock()


class DemoModeController(ControllerSupport, ABC):
    _demo_state_index: int
    _demo_snapshot_cache: dict[int, DemoStateSnapshot]
    _demo_snapshot_lock: Lock
    _demo_snapshot_condition: Condition
    _demo_snapshot_executor: ThreadPoolExecutor
    _demo_snapshot_pipeline_future: Future[None] | None
    _demo_snapshot_pipeline_error: BaseException | None
    victory_point_history: list[tuple[int, dict[PlayerNumber, int]]]
    endgame_review_history: list[tuple[int, dict[PlayerNumber, PlayerScoreSnapshot]]]

    def _run_demo_mode(self) -> None:
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
        with _DEMO_CAPTURE_LOCK:
            return self._capture_demo_state_unlocked(definition)

    def _capture_demo_state_sequence(self, start_index: int) -> None:
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
        definitions = DEMO_MODE_STATES[start_index:]
        if not definitions:
            return

        collector_cls = create_demo_state_collector_controller(type(self))
        collector = collector_cls(
            game_players=self.game_players,
            simulation_players=self.simulation_players,
            game_seed=DEMO_MODE_SEED,
        )
        collector.game_mode = GameMode.TUTOR
        collector.reset_game()
        collector.view = DemoStateSequenceCollectorView(collector, definitions, self._store_demo_state_snapshot)
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
        with self._demo_snapshot_condition:
            self._demo_snapshot_cache[snapshot.definition.moveNumber] = snapshot
            self._demo_snapshot_condition.notify_all()

    def _capture_demo_state_unlocked(self, definition: DemoStateDefinition) -> DemoStateSnapshot:
        collector_cls = create_demo_state_collector_controller(type(self))
        collector = collector_cls(
            game_players=self.game_players,
            simulation_players=self.simulation_players,
            game_seed=DEMO_MODE_SEED,
        )
        collector.game_mode = GameMode.TUTOR
        collector.reset_game()
        collector.view = DemoStateCollectorView(collector, definition)
        try:
            collector.start_game()
        except _DemoStateCaptured as captured:
            return captured.snapshot
        raise RuntimeError(f"Demo state move {definition.moveNumber} was not found.")

    def _restore_demo_state(self, snapshot: DemoStateSnapshot) -> None:
        self._game = deepcopy(snapshot.game_state)  # type: ignore
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
        self._game.rng = self.game_rng
        self._bind_rng_references(self._game, set())

    def _bind_rng_references(self, value: object, visited: set[int]) -> None:
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
        return next(player for player in self._game.players if player.player_number == player_number)

    def _run_demo_initial_settlement(self, snapshot: DemoStateSnapshot) -> None:
        player = self._find_player(snapshot.player_number)
        vertices = self._game.get_available_vertices(player, Buildable.SETTLEMENT, road_restriction=False)
        explanation = self._preview_tutor_explanation(
            lambda: self.tutor_ai.select_initial_settlement_location_with_explanation(player, self._game, vertices))
        self.view.display_tutor_init(player, TutorStage.INITIAL_SETTLEMENT, explanation)
        self.view.display_board(player, "Select a position to build your settlement")

        def select_tutor_initial_settlement() -> Vertex | None:
            return self._run_tutor_decision(
                lambda: self.tutor_ai.select_initial_settlement_location(player, self._game, vertices))

        self._set_tutor_shortcut_handlers(select_tutor_initial_settlement)
        try:
            vertex = self.view.draw_selectable_vertices(vertices)
        finally:
            self._set_tutor_shortcut_handlers(None)
        self._raise_if_return_home(vertex)
        self._raise_if_next_demo_state(vertex)
        feedback = self.tutor_evaluator.evaluate_opening_settlement_choice(
            player, self._game, vertices, vertex, title="Opening Settlement")
        self._game.try_build_settlement(
            player, vertex, use_resources=False, road_restriction=False, gain_resources=False)
        self._show_tutor_action_feedback(player, feedback)

        available_edges = [edge for edge in self._game.get_available_edges(player) if vertex in edge.vertices]
        explanation = self._preview_tutor_explanation(
            lambda: self.tutor_ai.select_initial_road_location_with_explanation(
                player, self._game, available_edges))
        self.view.display_tutor_init(player, TutorStage.INITIAL_ROAD, explanation)
        edge = self.get_road_choice(
            player,
            vertex,
            selector=lambda candidate_edges: self.tutor_ai.select_initial_road_location(
                player, self._game, candidate_edges),
        )
        self._raise_if_next_demo_state(edge)
        feedback = self.tutor_evaluator.evaluate_opening_road_choice(
            player, self._game, available_edges, edge, title="Opening Road")
        self._game.try_build_road(player, edge, use_resources=False)
        self._show_tutor_action_feedback(player, feedback)

    def _run_demo_initial_road(self, snapshot: DemoStateSnapshot) -> None:
        player = self._find_player(snapshot.player_number)
        if not player.settlements:
            raise RuntimeError("Initial-road demo state is missing the player's opening settlement.")

        settlement = player.settlements[-1]
        available_edges = [edge for edge in self._game.get_available_edges(player) if settlement in edge.vertices]
        explanation = self._preview_tutor_explanation(
            lambda: self.tutor_ai.select_initial_road_location_with_explanation(
                player, self._game, available_edges))
        self.view.display_tutor_init(player, TutorStage.INITIAL_ROAD, explanation)
        edge = self.get_road_choice(
            player,
            settlement,
            selector=lambda candidate_edges: self.tutor_ai.select_initial_road_location(
                player, self._game, candidate_edges),
        )
        self._raise_if_next_demo_state(edge)
        feedback = self.tutor_evaluator.evaluate_opening_road_choice(
            player, self._game, available_edges, edge, title="Opening Road")
        self._game.try_build_road(player, edge, use_resources=False)
        self._show_tutor_action_feedback(player, feedback)

    def _run_demo_discard(self, snapshot: DemoStateSnapshot) -> None:
        player = self._find_player(snapshot.player_number)
        discard_count = player.calculate_discard_count()
        if discard_count <= 0:
            raise RuntimeError("Discard demo state has no resources to discard.")

        explanation = self._preview_tutor_explanation(
            lambda: self.tutor_ai.select_discard_resources_with_explanation(player, self._game, discard_count))
        self._show_tutor_init(player, TutorStage.DISCARD_RESOURCES, explanation)

        def select_tutor_discard_resources() -> ResourceCount:
            return self._run_tutor_decision(
                lambda: self.tutor_ai.select_discard_resources(player, self._game, discard_count))

        self._set_tutor_shortcut_handlers(select_tutor_discard_resources)
        try:
            resources_to_discard = self.view.show_resource_chooser(
                player, discard_count, "The robber has been rolled!", player.resources)
        finally:
            self._set_tutor_shortcut_handlers(None)
        self._raise_if_return_home(resources_to_discard)
        self._raise_if_next_demo_state(resources_to_discard)
        feedback = self.tutor_evaluator.evaluate_discard_choice(
            player, self._game, resources_to_discard, discard_count, title="Discard")
        player.remove_resources(resources_to_discard)
        self._show_tutor_action_feedback(player, feedback)

    def _run_demo_robber_placement(self, snapshot: DemoStateSnapshot) -> None:
        player = self._find_player(snapshot.player_number)
        available_hexes = [tile for tile in self._game.get_all_hexes() if not tile.robber]
        explanation = self._preview_tutor_explanation(
            lambda: self.tutor_ai.select_robber_target_with_explanation(player, self._game, available_hexes))
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
        feedback = self.tutor_evaluator.evaluate_robber_choice(
            player, self._game, available_hexes, selected_hex, None, title="Robber")
        self._game.set_robber(selected_hex)
        self._show_tutor_action_feedback(player, feedback)

        adjacent_player_buildings = [
            vertex for vertex in selected_hex.vertices
            if vertex.owner is not None and vertex.owner != player and any(vertex.owner.resources.values())
        ]
        if adjacent_player_buildings:
            self._run_demo_robber_steal_target(snapshot)

    def _run_demo_robber_steal_target(self, snapshot: DemoStateSnapshot) -> None:
        player = self._find_player(snapshot.player_number)
        selected_hex = self._game.get_robber_tile()
        adjacent_player_buildings = [
            vertex for vertex in selected_hex.vertices
            if vertex.owner is not None and vertex.owner != player and any(vertex.owner.resources.values())
        ]
        if not adjacent_player_buildings:
            return

        explanation = self._preview_tutor_explanation(
            lambda: self.tutor_ai.select_robber_target_with_explanation(player, self._game, [selected_hex]))
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
        feedback = self.tutor_evaluator.evaluate_robber_choice(
            player, self._game, [selected_hex], selected_hex, selected_player, title="Robber")
        self._show_tutor_action_feedback(player, feedback)

        if selected_player is not None:
            resource = selected_player.random_resource()
            if resource:
                self._game.trade_between_players(player, {}, selected_player, resource)

    def _run_demo_main_turn(self, snapshot: DemoStateSnapshot) -> None:
        player = self._find_player(snapshot.player_number)
        if snapshot.dice_info is None:
            raise RuntimeError("Main-turn demo state is missing dice information.")
        self._tutor_dev_played = snapshot.played_dev_card
        self._run_main_turn_loop(player, snapshot.dice_info, snapshot.played_dev_card)

    def _finish_demo_from_state(self, definition: DemoStateDefinition) -> None:
        snapshot = self._get_demo_state_snapshot(definition)
        self._restore_demo_state(snapshot)
        original_view = self.view
        self.view = DemoAutoPlayView(self)
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
