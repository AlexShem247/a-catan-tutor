from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, cast

from ai.actions import ActionType, Phase
from ai.tutor.tutor import TutorStage
from config.demo_states import DemoStateDefinition
from controllers.controller_support import PlayerScoreSnapshot
from game.Edge import Edge
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.Resources import ResourceCount
from game.Vertex import Vertex
from view.HeadlessView import HeadlessView
from view.View import GameMode


@dataclass
class DemoStateSnapshot:
    definition: DemoStateDefinition
    decision_kind: str
    game_state: object
    game_rng_state: tuple[Any, ...]
    victory_point_history: list[tuple[int, dict[PlayerNumber, int]]]
    endgame_review_history: list[tuple[int, dict[PlayerNumber, PlayerScoreSnapshot]]]
    player_number: PlayerNumber
    dice_info: tuple[int, int, int] | None = None
    played_dev_card: bool = False


class _DemoStateCaptured(Exception):
    def __init__(self, snapshot: DemoStateSnapshot):
        self.snapshot = snapshot
        super().__init__(f"Captured demo state for move {snapshot.definition.moveNumber}.")


class _DemoStateSequenceCapturedAll(Exception):
    pass


def create_demo_state_collector_controller(base_cls: type[Any]) -> type[Any]:
    class _DemoStateCollectorController(base_cls):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.current_human_player: Player | None = None
            self.current_dice_info: tuple[int, int, int] | None = None

        def make_round_move(self, player: Player):
            self.current_human_player = player
            try:
                # noinspection PyUnresolvedReferences
                return super().make_round_move(player)
            finally:
                self.current_human_player = None
                self.current_dice_info = None

        def roll_dice(self, player: Player):
            # noinspection PyUnresolvedReferences
            result = super().roll_dice(player)
            self.current_dice_info = cast(tuple[int, int, int], result[:3])
            return result

        def _record_current_dice_info(self, dice_info: tuple[int, int, int]) -> None:
            """Record dice info as soon as it is available during capture."""
            self.current_dice_info = dice_info

    return _DemoStateCollectorController


class DemoStateCollectorView(HeadlessView):
    def __init__(self, controller: Any, definition: DemoStateDefinition):
        self.controller = controller
        self.definition = definition
        self._decision_index = 0
        self._debug_tutor_shortcut_handler: Callable[[], Any] | None = None
        self._latest_stage: TutorStage | None = None
        self._latest_player: Player | None = None

    def display_start_screen(self) -> GameMode:
        return GameMode.TUTOR

    def set_debug_tutor_shortcut_handler(self, handler):
        self._debug_tutor_shortcut_handler = handler

    def display_tutor_init(self, player: Player, stage: TutorStage, explanation) -> None:
        self._latest_stage = stage
        self._latest_player = player

    def display_board_turn(self, player: Player, dice_info: tuple[int, int, int], played_dev_card: bool = False):
        self._increment_or_capture(
            decision_kind="MAIN_TURN",
            player=player,
            dice_info=dice_info,
            played_dev_card=played_dev_card,
        )
        return self.controller.get_tutor_recommended_main_action(player, played_dev_card)

    def pre_roll(self, player: Player):
        self._increment_or_capture("PRE_ROLL", player)
        recommended_action = self.controller.run_tutor_decision(
            lambda: self.controller.tutor_ai.next_action(player, self.controller.get_game_state(), Phase.PRE_ROLL,
                                                         False))
        if recommended_action.type == ActionType.PLAY_DEV_CARD:
            return recommended_action.payload
        return False

    def draw_selectable_vertices(self, vertices: list[Vertex], disable_interactivity: bool = False) -> Vertex:
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

    def draw_selectable_edges(self, edges: list[Edge], disable_interactivity: bool = False) -> Edge:
        if disable_interactivity:
            return edges[0]
        self._increment_or_capture(
            "INITIAL_ROAD" if self._latest_stage == TutorStage.INITIAL_ROAD else "EDGE",
            self._latest_player or self.controller.current_human_player,
        )
        choice = self._call_debug_handler(edges[0])
        self._latest_stage = None
        self._latest_player = None
        return choice

    def draw_selectable_tiles(self, tiles: list[HexTile]) -> HexTile:
        self._increment_or_capture("ROBBER_PLACEMENT", self._latest_player or self.controller.current_human_player)
        self._latest_stage = None
        self._latest_player = None
        return self._call_debug_handler(tiles[0])

    def show_resource_chooser(self, player: Player, num_resources: int, title: str,
                              resource_caps: ResourceCount | None = None) -> ResourceCount:
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
        willing_players: list[tuple[Player, ResourceCount | None]],
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
        player: Player | None,
        dice_info: tuple[int, int, int] | None = None,
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
        player: Player | None,
        dice_info: tuple[int, int, int] | None,
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
        snapshot_dice_info = dice_info if dice_info is not None else self.controller.current_dice_info
        return DemoStateSnapshot(
            definition=definition,
            decision_kind=decision_kind,
            game_state=deepcopy(self.controller.get_game_state()),
            game_rng_state=self.controller.game_rng.getstate(),
            victory_point_history=deepcopy(self.controller.get_victory_point_history()),
            endgame_review_history=deepcopy(self.controller.get_endgame_review_history()),
            player_number=player.player_number,
            dice_info=snapshot_dice_info,
            played_dev_card=played_dev_card,
        )


class DemoStateSequenceCollectorView(DemoStateCollectorView):
    def __init__(
        self,
        controller: Any,
        definitions: list[DemoStateDefinition],
        snapshot_callback: Callable[[DemoStateSnapshot], None],
    ):
        super().__init__(controller, definitions[0])
        self.definitions = definitions
        self.snapshot_callback = snapshot_callback
        self._target_index = 0

    def _increment_or_capture(
        self,
        decision_kind: str,
        player: Player | None,
        dice_info: tuple[int, int, int] | None = None,
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


class DemoAutoPlayView(HeadlessView):
    def __init__(self, controller: Any):
        self.controller = controller
        self._latest_stage: TutorStage | None = None
        self._latest_player: Player | None = None
        self._latest_robber_hex: HexTile | None = None

    def display_tutor_init(self, player: Player, stage: TutorStage, explanation) -> None:
        self._latest_stage = stage
        self._latest_player = player

    def display_board_turn(self, player: Player, dice_info: tuple[int, int, int], played_dev_card: bool = False):
        return self.controller.get_tutor_recommended_main_action(player, played_dev_card)

    def pre_roll(self, player: Player):
        recommended_action = self.controller.run_tutor_decision(
            lambda: self.controller.tutor_ai.next_action(player, self.controller.get_game_state(), Phase.PRE_ROLL,
                                                         False))
        if recommended_action.type == ActionType.PLAY_DEV_CARD:
            return recommended_action.payload
        return False

    def draw_selectable_vertices(self, vertices: list[Vertex], disable_interactivity: bool = False) -> Vertex:
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

    def draw_selectable_edges(self, edges: list[Edge], disable_interactivity: bool = False) -> Edge | object:
        if disable_interactivity:
            return edges[0]
        player = self._latest_player
        if player is not None:
            if self._latest_stage == TutorStage.ROAD_BUILDING:
                return self.controller.run_tutor_decision(
                    lambda: self.controller.tutor_ai.road_building_placement(
                        player, self.controller.get_game_state(), edges))
            if self._latest_stage == TutorStage.INITIAL_ROAD:
                return self.controller.run_tutor_decision(
                    lambda: self.controller.tutor_ai.select_initial_road_location(
                        player, self.controller.get_game_state(), edges))
        return edges[0]

    def draw_selectable_tiles(self, tiles: list[HexTile]) -> HexTile:
        player = self._latest_player
        if player is not None:
            chosen_hex, _ = self.controller.get_tutor_recommended_robber_choice(player, tiles)
            self._latest_robber_hex = chosen_hex
            return chosen_hex
        return tiles[0]

    def show_resource_chooser(self, player: Player, num_resources: int, title: str,
                              resource_caps: ResourceCount | None = None) -> object | dict[object, int]:
        if self._latest_stage == TutorStage.DISCARD_RESOURCES:
            return self.controller.run_tutor_decision(
                lambda: self.controller.tutor_ai.select_discard_resources(
                    player, self.controller.get_game_state(), num_resources))
        if self._latest_stage == TutorStage.YEAR_OF_PLENTY:
            return self.controller.run_tutor_decision(
                lambda: self.controller.tutor_ai.select_year_of_plenty_resources(
                    player, self.controller.get_game_state()))
        if self._latest_stage == TutorStage.MONOPOLY:
            resource = self.controller.run_tutor_decision(
                lambda: self.controller.tutor_ai.select_monopoly_resource(player, self.controller.get_game_state()))
            return {resource: 1}
        return {}

    def display_trade_manager(self, player: Player, selling: ResourceCount, buying: ResourceCount,
                              selling_player: Player):
        return self.controller.run_tutor_decision(
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
        willing_players: list[tuple[Player, ResourceCount | None]],
    ):
        affordable_offers = [
            (candidate_player, counter)
            for candidate_player, counter in willing_players
            if counter is None or player.can_afford(counter)
        ]
        if not affordable_offers:
            return None
        return self.controller.run_tutor_decision(
            lambda: self.controller.tutor_ai.choose_trade_partner(
                player,
                self.controller.get_game_state(),
                selling,
                buying,
                affordable_offers,
            ))
