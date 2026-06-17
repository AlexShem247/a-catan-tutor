from abc import ABC
from random import Random
from typing import Any, Callable, Optional, TypeVar

from ai.actions import Action, Phase
from ai.rule_based_ai.RuleBasedAI import RuleBasedAI
from ai.tutor.explanations import ActionExplanation
from ai.tutor.feedback import TutorFeedbackExplanation
from ai.tutor.tutor import TutorStage
from controllers.controller_support import ControllerSupport
from game.HexTile import HexTile
from game.Player import Player

T = TypeVar("T")


class TutorController(ControllerSupport, ABC):

    def _new_tutor_rng(self) -> Random:
        """Create a new tutor RNG instance."""
        seed_getter = getattr(self, "_get_active_game_seed", None)
        if callable(seed_getter):
            seed = seed_getter()
            if seed is None or isinstance(seed, (int, float, str, bytes, bytearray)):
                return Random(seed)
        return Random(self.game_seed)

    def _new_tutor_ai(self) -> RuleBasedAI:
        """Create a new tutor AI instance."""
        tutor_rng = self._new_tutor_rng()
        human_player_numbers = [
            player_number for player_number, policy_cls in self.game_players.items() if policy_cls is None
        ]
        for player_number in human_player_numbers:
            policy_factory = self.simulation_players.get(player_number)
            if policy_factory is None:
                continue
            tutor_policy = policy_factory(tutor_rng)
            if isinstance(tutor_policy, RuleBasedAI):
                return tutor_policy
        return RuleBasedAI(tutor_rng)

    def _sync_tutor_ai_rng_to_game_state(self) -> None:
        """Sync tutor AI randomness from the game state."""
        self.tutor_ai.rng.setstate(self.game_rng.getstate())

    def _commit_tutor_ai_rng_to_game_state(self) -> None:
        """Commit tutor AI randomness back to the game state."""
        self.game_rng.setstate(self.tutor_ai.rng.getstate())

    def _run_tutor_decision(self, callback: Callable[[], T]) -> T:
        """Run a decision while keeping tutor state in sync."""
        self._sync_tutor_ai_rng_to_game_state()
        result = callback()
        self._commit_tutor_ai_rng_to_game_state()
        return result

    def _run_tutor_preview(self, callback: Callable[[], T]) -> T:
        """Run a tutor preview without mutating the live game state."""
        snapshot = self.tutor_ai.snapshot_state()
        try:
            self._sync_tutor_ai_rng_to_game_state()
            return callback()
        finally:
            self.tutor_ai.restore_state(snapshot)

    def _show_tutor_init(
        self,
        player: Player,
        stage: TutorStage,
        explanation: Optional[ActionExplanation],
    ) -> None:
        """Show the tutor introduction for the current decision stage."""
        if (self.game_mode in {self.GameMode.TUTOR, self.GameMode.GUIDED} and player.is_human and explanation is
                not None):
            self.view.display_tutor_init(player, stage, explanation)

    def _should_collect_tutor_feedback(self, player: Player) -> bool:
        """Check whether tutor feedback should be collected."""
        return player.is_human and self.game_mode in {self.GameMode.PLAY, self.GameMode.TUTOR, self.GameMode.GUIDED}

    def _should_show_tutor_feedback(self, player: Player) -> bool:
        """Check whether tutor feedback should be shown."""
        return (self.view is not None and player.is_human
                and self.game_mode in {self.GameMode.TUTOR, self.GameMode.GUIDED})

    def get_tutor_turn_explanation(
        self,
        player: Player,
        played_dev_card: Optional[bool] = None,
    ) -> Optional[ActionExplanation]:
        """Return the tutor explanation for the current turn."""
        if self.game_mode not in {self.GameMode.TUTOR, self.GameMode.GUIDED} or not player.is_human:
            return None
        if played_dev_card is None:
            played_dev_card = self._tutor_dev_played
        _, explanation = self._run_tutor_preview(lambda: self.tutor_ai.next_action_with_explanation(
            player,
            self._game,
            phase=Phase.MAIN,
            dev_played=played_dev_card,
        ))
        return explanation

    def _preview_tutor_explanation(
        self,
        callback: Callable[[], tuple[Any, ...]],
    ) -> Optional[ActionExplanation]:
        """Preview the tutor explanation for a pending decision."""
        preview_result = self._run_tutor_preview(callback)
        if not isinstance(preview_result, tuple) or len(preview_result) < 2:
            return None
        explanation = preview_result[-1]
        return explanation if isinstance(explanation, ActionExplanation) else None

    def _refresh_tutor_turn_explanation(self, player: Player) -> None:
        """Refresh the cached tutor turn explanation."""
        if (self.game_mode not in {self.GameMode.TUTOR, self.GameMode.GUIDED} or not player.is_human or self.view
                is None):
            return
        explanation = self.get_tutor_turn_explanation(player)
        if explanation is not None:
            self.view.display_tutor_init(player, TutorStage.TURN_ACTION, explanation)

    def get_tutor_recommended_main_action(self, player: Player, played_dev_card: bool) -> Action:
        """Return the tutor-recommended main action."""
        action, _ = self._run_tutor_decision(lambda: self.tutor_ai.next_action_with_explanation(
            player,
            self._game,
            phase=Phase.MAIN,
            dev_played=played_dev_card,
        ))
        return action

    def _set_tutor_shortcut_handlers(
        self,
        recommended_handler: Optional[Callable[[], Any]],
    ) -> None:
        """Set the tutor shortcut handlers for the current decision."""
        if self.view is None:
            return
        if self.game_mode in {self.GameMode.PLAY, self.GameMode.TUTOR, self.GameMode.GUIDED}:
            self.view.set_debug_tutor_shortcut_handler(recommended_handler)
        else:
            self.view.set_debug_tutor_shortcut_handler(None)

    def _prepare_tutor_main_action_comparison(self, player: Player, action: Action,
                                              played_dev_card: bool) -> Optional[TutorFeedbackExplanation]:
        """Prepare tutor comparison data for a main action."""
        if not self._should_collect_tutor_feedback(player):
            return None
        return self._run_tutor_preview(lambda: self.tutor_evaluator.evaluate_main_turn_action(
            player,
            self._game,
            Phase.MAIN,
            played_dev_card,
            action,
            title="Main Turn",
        ))

    def _show_tutor_action_feedback(self, player: Player, feedback: Optional[TutorFeedbackExplanation]) -> None:
        """Show tutor feedback for the completed player action."""
        if feedback is None or not self._should_collect_tutor_feedback(player):
            return
        self.tutor_feedback_history.append(feedback)
        if self._should_show_tutor_feedback(player):
            result = self.view.display_tutor_action_feedback(feedback)
            self._raise_if_return_home(result)
            next_demo_handler = getattr(self, "_raise_if_next_demo_state", None)
            if callable(next_demo_handler):
                next_demo_handler(result)

    def _get_tutor_recommended_robber_choice(
        self,
        player: Player,
        valid_hexes: list[HexTile],
    ):
        """Return the tutor-recommended robber choice."""
        cached_choice = self._pending_tutor_robber_choice
        if cached_choice is not None and cached_choice[0] in valid_hexes:
            return cached_choice
        choice = self._run_tutor_decision(lambda: self.tutor_ai.select_robber_target(player, self._game, valid_hexes))
        self._pending_tutor_robber_choice = choice
        return choice
