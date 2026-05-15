from __future__ import annotations

from abc import ABC, abstractmethod
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
            f"AI action request limit exceeded for {player_name} after {request_count} requests in {phase.name}.")


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


class ControllerSupport(ABC):
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

    @abstractmethod
    def _preview_tutor_explanation(self, callback: Callable[[], tuple[Any, ...]]) -> Optional[ActionExplanation]:
        """Preview the tutor explanation for a pending decision."""
        ...

    @abstractmethod
    def _show_tutor_init(
        self,
        player: Player,
        stage: TutorStage,
        explanation: Optional[ActionExplanation],
    ) -> None:
        """Show the tutor introduction for the current decision stage."""
        ...

    @abstractmethod
    def _run_tutor_decision(self, callback: Callable[[], T]) -> T:
        """Run a decision while keeping tutor state in sync."""
        ...

    @abstractmethod
    def _set_tutor_shortcut_handlers(self, recommended_handler: Optional[Callable[[], Any]]) -> None:
        """Set the tutor shortcut handlers for the current decision."""
        ...

    @abstractmethod
    def _raise_if_return_home(self, value: object) -> None:
        """Raise when a return-home action is received."""
        ...

    @abstractmethod
    def _raise_if_view_requested_home(self) -> None:
        """Raise when the view has requested a return home."""
        ...

    @abstractmethod
    def _should_collect_tutor_feedback(self, player: Player) -> bool:
        """Check whether tutor feedback should be collected."""
        ...

    @abstractmethod
    def _show_tutor_action_feedback(self, player: Player, feedback: Optional[TutorFeedbackExplanation]) -> None:
        """Show tutor feedback for the completed player action."""
        ...

    @abstractmethod
    def _refresh_tutor_turn_explanation(self, player: Player) -> None:
        """Refresh the cached tutor turn explanation."""
        ...

    @abstractmethod
    def _get_tutor_recommended_robber_choice(
        self,
        player: Player,
        valid_hexes: list[HexTile],
    ):
        """Return the tutor-recommended robber choice."""
        ...

    @abstractmethod
    def get_road_choice(
        self,
        player: Player,
        settlement: Optional[Vertex] = None,
        selector: Optional[Callable[[list[Edge]], Optional[Edge]]] = None,
    ) -> Edge:
        """Return the selected road choice for the current flow."""
        ...

    @abstractmethod
    def get_road_choice_ai(self, player: Player, settlement: Optional[Vertex] = None) -> Optional[Edge]:
        """Return the AI-selected road choice."""
        ...

    @abstractmethod
    def get_tutor_recommended_main_action(self, player: Player, played_dev_card: bool):
        """Return the tutor-recommended main action."""
        ...

    @abstractmethod
    def _prepare_tutor_main_action_comparison(self, player: Player, action, played_dev_card: bool):
        """Prepare tutor comparison data for a main action."""
        ...

    @abstractmethod
    def play_development_card(self, player: Player, card_type) -> str:
        """Play the selected development card action."""
        ...

    @abstractmethod
    def roll_dice(self, player: Player):
        """Roll the dice and handle any resulting events."""
        ...

    @abstractmethod
    def trade_with_players(self, selling_player, selling, buying):
        """Run the player-to-player trade flow."""
        ...

    @abstractmethod
    def ai_attempt_build(self, player: Player, action: Buildable, location):
        """Try to execute the requested AI build action."""
        ...

    @abstractmethod
    def try_build_road(self, player: Player, location):
        """Try to build a road through the controller workflow."""
        ...

    @abstractmethod
    def try_build_settlement(self, player: Player, location):
        """Try to build a settlement through the controller workflow."""
        ...

    @abstractmethod
    def try_build_city(self, player: Player, location):
        """Try to build a city through the controller workflow."""
        ...

    @abstractmethod
    def try_trade_with_bank(self, player: Player, selling: ResourceCount, buying: ResourceCount):
        """Try to perform a bank trade through the controller workflow."""
        ...

    @abstractmethod
    def trade_between_players(
        self,
        player: Player,
        selling: ResourceCount,
        buying_player: Player,
        buying: ResourceCount,
    ):
        """Run the trade flow between two players."""
        ...

    @abstractmethod
    def try_buy_development_card(self, player: Player):
        """Try to buy a development card through the controller workflow."""
        ...
