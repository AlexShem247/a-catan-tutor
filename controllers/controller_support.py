from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

from ai.rule_based_ai.RuleBasedAI import RuleBasedAI
from ai.tutor.evaluator import TutorEvaluator
from ai.tutor.explanations import ActionExplanation
from ai.tutor.feedback import TutorFeedbackExplanation
from ai.tutor.tutor import TutorStage
from game.Edge import Edge
from game.Game import Game, PlayerConfig
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.PlayerAssets import Buildable
from game.Resources import ResourceCount
from game.Vertex import Vertex
from view.View import GameMode, View

START_LAST = False
MAX_AI_ACTION_REQUESTS_PER_TURN = 200
T = TypeVar("T")


class ReturnToStart(Exception):
    pass


class AITurnActionLimitExceeded(Exception):
    def __init__(self, player_name: str, request_count: int, phase):
        self.player_name = player_name
        self.request_count = request_count
        self.phase = phase
        super().__init__(
            f"AI action request limit exceeded for {player_name} after {request_count} requests in {phase.name}."
        )


@dataclass(frozen=True)
class PlayerScoreSnapshot:
    total_vp: int
    visible_vp: int
    settlements: int
    cities: int
    hidden_vp_cards: int
    longest_road_length: int
    army_size: int
    has_longest_road: bool
    has_largest_army: bool


class ControllerSupport:
    _game: Game
    view: View | None
    game_mode: GameMode
    GameMode: type[GameMode]
    game_players: PlayerConfig
    simulation_players: PlayerConfig
    game_seed: Optional[int]
    game_rng: Random
    tutor_ai: RuleBasedAI
    tutor_evaluator: TutorEvaluator
    tutor_feedback_history: List[TutorFeedbackExplanation]
    _tutor_dev_played: bool
    _pending_tutor_robber_choice: Any
    SHOW_AI_BUILT_LOCATIONS: bool

    def _preview_tutor_explanation(self, callback: Callable[[], tuple[Any, ...]]) -> Optional[ActionExplanation]:
        raise NotImplementedError

    def _show_tutor_init(
            self,
            player: Player,
            stage: TutorStage,
            explanation: Optional[ActionExplanation],
    ) -> None:
        raise NotImplementedError

    def _run_tutor_decision(self, callback: Callable[[], T]) -> T:
        raise NotImplementedError

    def _set_tutor_shortcut_handlers(self, recommended_handler: Optional[Callable[[], Any]]) -> None:
        raise NotImplementedError

    def _raise_if_return_home(self, value: object) -> None:
        raise NotImplementedError

    def _raise_if_view_requested_home(self) -> None:
        raise NotImplementedError

    def _should_collect_tutor_feedback(self, player: Player) -> bool:
        raise NotImplementedError

    def _show_tutor_action_feedback(self, player: Player, feedback: Optional[TutorFeedbackExplanation]) -> None:
        raise NotImplementedError

    def _refresh_tutor_turn_explanation(self, player: Player) -> None:
        raise NotImplementedError

    def _get_tutor_recommended_robber_choice(
            self,
            player: Player,
            valid_hexes: list[HexTile],
    ):
        raise NotImplementedError

    def get_road_choice(
            self,
            player: Player,
            settlement: Optional[Vertex] = None,
            selector: Optional[Callable[[list[Edge]], Optional[Edge]]] = None,
    ) -> Edge:
        raise NotImplementedError

    def get_road_choice_ai(self, player: Player, settlement: Optional[Vertex] = None) -> Optional[Edge]:
        raise NotImplementedError

    def get_tutor_recommended_main_action(self, player: Player, played_dev_card: bool):
        raise NotImplementedError

    def _prepare_tutor_main_action_comparison(self, player: Player, action, played_dev_card: bool):
        raise NotImplementedError

    def play_development_card(self, player: Player, card_type) -> str:
        raise NotImplementedError

    def roll_dice(self, player: Player):
        raise NotImplementedError

    def trade_with_players(self, selling_player, selling, buying):
        raise NotImplementedError

    def ai_attempt_build(self, player: Player, action: Buildable, location):
        raise NotImplementedError

    def try_build_road(self, player: Player, location):
        raise NotImplementedError

    def try_build_settlement(self, player: Player, location):
        raise NotImplementedError

    def try_build_city(self, player: Player, location):
        raise NotImplementedError

    def try_trade_with_bank(self, player: Player, selling: ResourceCount, buying: ResourceCount):
        raise NotImplementedError

    def trade_between_players(
            self,
            player: Player,
            selling: ResourceCount,
            buying_player: Player,
            buying: ResourceCount,
    ):
        raise NotImplementedError

    def try_buy_development_card(self, player: Player):
        raise NotImplementedError
