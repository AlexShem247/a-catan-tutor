from dataclasses import dataclass
from typing import Dict, Optional

from ai.actions import Action, ActionType
from ai.simulation.SimGame import SimGame
from ai.simulation.etw_candidates import EtwCandidateGenerator
from ai.simulation.etw_evaluation import EtwEvaluation
from ai.simulation.etw_selection import EtwSelection
from ai.simulation.etw_timing import EtwTiming
from ai.tutor.explanations import ActionExplanation, AssumptionCode, CandidateExplanation
from ai.tutor.move_quality import strategic_turn_move_quality
from config.StrategyWeights import StrategyWeights
from game.Player import PlayerNumber
from game.Resources import ResourceCount
from ai.simulation.board_sim_utils import get_opponents


@dataclass(frozen=True)
class EtwTradeStateSnapshot:
    last_trade_resources: Optional[ResourceCount]
    last_trade_proposed: bool


class EtwEstimator:
    def __init__(self):
        self._eval_stats = {"cache_hits": 0, "cache_misses": 0, "evaluations": 0}
        self._last_trade_resources: Optional[ResourceCount] = None
        self._last_trade_proposed: bool = False
        self.timing = EtwTiming()
        self.candidates = EtwCandidateGenerator(self.timing, self)
        self.evaluator = EtwEvaluation(self.timing, self.candidates, self._eval_stats)
        self.evaluator.estimator = self
        self.selector = EtwSelection(self.timing, self.evaluator, self.last_trade_rejected, self)

    def new_turn(self):
        """Reset per-turn AI state."""
        self._last_trade_proposed = False
        self._last_trade_resources = None

    def snapshot_trade_state(self) -> EtwTradeStateSnapshot:
        """Capture the trade state."""
        last_trade_resources = self._last_trade_resources
        return EtwTradeStateSnapshot(
            last_trade_resources=None if last_trade_resources is None else last_trade_resources.copy(),
            last_trade_proposed=self._last_trade_proposed,
        )

    def restore_trade_state(self, snapshot: EtwTradeStateSnapshot) -> None:
        """Restore the trade state."""
        self._last_trade_proposed = snapshot.last_trade_proposed
        self._last_trade_resources = (
            None if snapshot.last_trade_resources is None else snapshot.last_trade_resources.copy()
        )

    def record_trade_proposal(self, resources: ResourceCount) -> None:
        """Record the trade proposal."""
        self._last_trade_proposed = True
        self._last_trade_resources = resources.copy()

    def clear_trade_proposal(self) -> None:
        """Handle clear trade proposal."""
        self._last_trade_proposed = False
        self._last_trade_resources = None

    def estimated_time_to_build(
        self,
        player,
        sim_game: SimGame,
        target_resources: ResourceCount,
        include_player_trades: bool = True,
    ) -> float:
        """Handle estimated time to build."""
        return self.timing.estimated_time_to_build(
            player,
            sim_game,
            target_resources,
            include_player_trades=include_player_trades,
        )

    def estimated_time_to_win(
        self,
        player,
        sim_game: SimGame,
        dev_played: bool,
        include_player_trades: bool = True,
        max_depth_override: Optional[int] = None,
        allow_development_cards: bool = True,
        use_planning: bool = True,
    ) -> float:
        """Handle estimated time to win."""
        return self.evaluator.estimated_time_to_win(
            player,
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            max_depth_override=max_depth_override,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )

    def calc_etb_actions(self, player, sim_game: SimGame, total_actions):
        """Handle calc etb actions."""
        return self.timing.calc_etb_actions(player, sim_game, total_actions)

    def _simulate_step(self, sim_game: SimGame, player, step: Action):
        """Simulate the step."""
        self.evaluator.simulate_step(sim_game, player, step)

    def _build_end_turn_candidate(
        self,
        player,
        sim_game: SimGame,
        etw_before: float,
        deferred_candidate: Optional[CandidateExplanation] = None,
        include_player_trades: bool = True,
        allow_development_cards: bool = True,
        use_planning: bool = True,
        use_time_discount: bool = True,
    ) -> CandidateExplanation:
        """Build the end turn candidate."""
        return self.evaluator.build_end_turn_candidate(
            player,
            sim_game,
            etw_before,
            deferred_candidate,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
            use_time_discount=use_time_discount,
        )

    def evaluate_candidates_with_explanations(
        self,
        player,
        sim_game: SimGame,
        dev_played: bool,
        candidates,
        etw_before: float,
        opponents_etw_before: Dict[PlayerNumber, float],
        include_player_trades: bool = True,
        allow_development_cards: bool = True,
        use_planning: bool = True,
        use_time_discount: bool = True,
    ):
        """Evaluate the candidates with explanations."""
        return self.evaluator.evaluate_candidates_with_explanations(
            player,
            sim_game,
            dev_played,
            candidates,
            etw_before,
            opponents_etw_before,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
            use_time_discount=use_time_discount,
        )

    def last_trade_rejected(self, player) -> bool:
        """Handle last trade rejected."""
        if not self._last_trade_proposed or self._last_trade_resources is None:
            return False
        return self._last_trade_resources == player.resources

    def calculate_best_game_action(
        self,
        sim_game: SimGame,
        player_number: PlayerNumber,
        dev_played: bool,
        ignore_affordability: bool = False,
        ignore_opponents: bool = False,
        include_player_trades: bool = True,
        use_time_discount: bool = True,
        allow_development_cards: bool = True,
        use_planning: bool = True,
    ) -> Action:
        """Handle calculate best game action."""
        sim_player = sim_game.overlay.get_sim_player(player_number)
        etw_before = self.estimated_time_to_win(
            sim_player.copy(),
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )

        opponents_etw_before: Dict[PlayerNumber, float] = {}
        if not ignore_opponents:
            for opponent in get_opponents(sim_game, player_number):
                opponents_etw_before[opponent.player_number] = self.estimated_time_to_win(
                    opponent.copy(),
                    sim_game,
                    False,
                    include_player_trades=include_player_trades,
                    allow_development_cards=allow_development_cards,
                    use_planning=use_planning,
                )

        candidates = self.candidates.get_candidate_actions(
            sim_player,
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )
        if not candidates:
            return Action(ActionType.END_TURN)

        utilities = self.evaluator.evaluate_utilities(
            sim_player,
            sim_game,
            dev_played,
            candidates,
            etw_before,
            opponents_etw_before,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
            use_time_discount=use_time_discount,
        )
        if not utilities:
            return Action(ActionType.END_TURN)

        best_build = max(
            (utility for utility in utilities if utility[0].type != ActionType.BUY_DEV_CARD),
            default=None,
            key=lambda item: item[1],
        )
        best_dev = max(
            (utility for utility in utilities if utility[0].type == ActionType.BUY_DEV_CARD),
            default=None,
            key=lambda item: item[1],
        )
        if allow_development_cards and (not ignore_affordability) and best_build is not None and best_dev is not None:
            if best_dev[1] >= best_build[1] * (1.0 - StrategyWeights.DEV_CLOSE_THRESHOLD):
                utilities = [best_dev]

        return self.selector.choose_max_utility_action(
            sim_player,
            sim_game,
            utilities,
            ignore_affordability=ignore_affordability,
            include_player_trades=include_player_trades,
        )

    def explain_action(
        self,
        sim_game: SimGame,
        player_number: PlayerNumber,
        dev_played: bool,
        action: Action,
        ignore_opponents: bool = False,
        include_player_trades: bool = True,
        use_time_discount: bool = True,
        allow_development_cards: bool = True,
        use_planning: bool = True,
    ) -> ActionExplanation:
        """Handle explain action."""
        sim_player = sim_game.overlay.get_sim_player(player_number)
        etw_before = self.estimated_time_to_win(
            sim_player.copy(),
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )

        opponents_etw_before: Dict[PlayerNumber, float] = {}
        if not ignore_opponents:
            for opponent in get_opponents(sim_game, player_number):
                opponents_etw_before[opponent.player_number] = self.estimated_time_to_win(
                    opponent.copy(),
                    sim_game,
                    False,
                    include_player_trades=include_player_trades,
                    allow_development_cards=allow_development_cards,
                    use_planning=use_planning,
                )

        candidates = self.candidates.get_candidate_actions(
            sim_player,
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )
        explained_candidates = self.evaluator.evaluate_candidates_with_explanations(
            sim_player,
            sim_game,
            dev_played,
            candidates,
            etw_before,
            opponents_etw_before,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
            use_time_discount=use_time_discount,
        ) if candidates else []

        chosen_candidate = next((candidate for candidate in explained_candidates if candidate.action == action), None)
        if chosen_candidate is None:
            chosen_candidate = self.evaluator.evaluate_action_plan(
                sim_player,
                sim_game,
                dev_played,
                [action],
                self.candidates.estimate_single_action_etb(
                    sim_player,
                    sim_game,
                    action,
                    include_player_trades=include_player_trades,
                ),
                0.0,
                etw_before,
                opponents_etw_before,
                include_player_trades=include_player_trades,
                allow_development_cards=allow_development_cards,
                use_planning=use_planning,
                use_time_discount=use_time_discount,
            )

        if chosen_candidate is None:
            chosen_candidate = CandidateExplanation(
                action=action,
                full_plan=[action],
                etw_before=etw_before,
                etw_after=etw_before,
                etw_delta=0.0,
                utility_total=0.0,
                reasons_for=[],
            )

        alternatives = [
            candidate for candidate in explained_candidates
            if candidate.action != chosen_candidate.action
        ][:3]
        worst_utility = (
            explained_candidates[-1].utility_total
            if explained_candidates
            else chosen_candidate.utility_total
        )
        return ActionExplanation(
            chosen_action=chosen_candidate.action,
            chosen_candidate=chosen_candidate,
            alternatives=alternatives,
            move_quality=strategic_turn_move_quality(
                chosen_candidate,
                alternatives[0].utility_total if alternatives else None,
                worst_utility,
            ),
            assumptions=[AssumptionCode.EXPECTED_PRODUCTION, AssumptionCode.LEGALITY_AND_AFFORDABILITY],
            metadata={"player_number": player_number, "etw_before": etw_before},
        )

    def calculate_best_game_action_with_explanation(
        self,
        sim_game: SimGame,
        player_number: PlayerNumber,
        dev_played: bool,
        ignore_affordability: bool = False,
        ignore_opponents: bool = False,
        include_player_trades: bool = True,
        use_time_discount: bool = True,
        allow_development_cards: bool = True,
        use_planning: bool = True,
    ) -> ActionExplanation:
        """Handle calculate best game action with explanation."""
        sim_player = sim_game.overlay.get_sim_player(player_number)
        etw_before = self.estimated_time_to_win(
            sim_player.copy(),
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )

        opponents_etw_before: Dict[PlayerNumber, float] = {}
        if not ignore_opponents:
            for opponent in get_opponents(sim_game, player_number):
                opponents_etw_before[opponent.player_number] = self.estimated_time_to_win(
                    opponent.copy(),
                    sim_game,
                    False,
                    include_player_trades=include_player_trades,
                    allow_development_cards=allow_development_cards,
                    use_planning=use_planning,
                )

        candidates = self.candidates.get_candidate_actions(
            sim_player,
            sim_game,
            dev_played,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
        )
        if not candidates:
            chosen = CandidateExplanation(
                action=Action(ActionType.END_TURN),
                full_plan=[Action(ActionType.END_TURN)],
                next_plan=[],
                waiting_resources={},
                etw_before=etw_before,
                etw_after=etw_before,
                etw_delta=0.0,
                utility_total=0.0,
                reasons_for=[],
            )
            return ActionExplanation(
                chosen_action=chosen.action,
                chosen_candidate=chosen,
                alternatives=[],
                move_quality=strategic_turn_move_quality(chosen),
                assumptions=[AssumptionCode.NO_CANDIDATE_ACTION],
            )

        explained_candidates = self.evaluator.evaluate_candidates_with_explanations(
            sim_player,
            sim_game,
            dev_played,
            candidates,
            etw_before,
            opponents_etw_before,
            include_player_trades=include_player_trades,
            allow_development_cards=allow_development_cards,
            use_planning=use_planning,
            use_time_discount=use_time_discount,
        )
        if not explained_candidates:
            next_plan, waiting_resources = self.evaluator.future_plan_fields(sim_player, candidates[0][0])
            chosen = CandidateExplanation(
                action=Action(ActionType.END_TURN),
                full_plan=[Action(ActionType.END_TURN)],
                next_plan=next_plan,
                waiting_resources=waiting_resources,
                etw_before=etw_before,
                etw_after=etw_before,
                etw_delta=0.0,
                utility_total=0.0,
                reasons_for=[],
            )
            return ActionExplanation(
                chosen_action=chosen.action,
                chosen_candidate=chosen,
                alternatives=[],
                move_quality=strategic_turn_move_quality(chosen),
                assumptions=[AssumptionCode.FILTERED_CANDIDATES],
            )

        chosen_action, chosen_candidate = self.selector.choose_max_utility_action_with_candidate(
            sim_player,
            sim_game,
            explained_candidates,
            ignore_affordability=ignore_affordability,
            include_player_trades=include_player_trades,
            use_time_discount=use_time_discount,
        )
        alternatives = [
            candidate for candidate in explained_candidates
            if candidate.full_plan != chosen_candidate.full_plan
        ][:3]
        return ActionExplanation(
            chosen_action=chosen_action,
            chosen_candidate=chosen_candidate,
            alternatives=alternatives,
            move_quality=strategic_turn_move_quality(
                chosen_candidate,
                alternatives[0].utility_total if alternatives else None,
                explained_candidates[-1].utility_total if explained_candidates else None,
            ),
            assumptions=[AssumptionCode.EXPECTED_PRODUCTION, AssumptionCode.LEGALITY_AND_AFFORDABILITY],
            metadata={"player_number": player_number, "etw_before": etw_before},
        )
