from typing import List, Optional, Tuple

from ai.actions import Action, ActionType
from ai.simulation.board_sim_utils import get_opponents
from ai.simulation.etw_evaluation import sim_game_with_replaced_player
from ai.simulation.SimGame import SimGame
from ai.simulation.SimPlayerState import SimPlayerState
from ai.tutor.explanations import CandidateExplanation, Reason, ReasonLabel, ReasonType
from ai.utils.action_utils import get_bank_trade_for_action
from ai.utils.resource_utils import calc_step_resources
from ai.utils.trade_utils import propose_trade


class EtwSelection:

    def __init__(self, timing, evaluator, last_trade_rejected, estimator):
        self.timing = timing
        self.evaluator = evaluator
        self.last_trade_rejected = last_trade_rejected
        self.estimator = estimator

    def choose_max_utility_action(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        utilities: List[Tuple[Action, float]],
        ignore_affordability: bool = False,
        include_player_trades: bool = True,
    ) -> Action:
        """Choose the max utility action."""
        best_action: Optional[Action] = None
        best_utility = float("-inf")

        for action, utility in utilities:
            cost = calc_step_resources(action)
            if player.can_afford(cost) or ignore_affordability:
                if utility > best_utility:
                    best_utility = utility
                    best_action = action
                continue

            bank_trade_action = get_bank_trade_for_action(player, cost)
            if bank_trade_action and utility > best_utility:
                best_utility = utility
                best_action = bank_trade_action

            if include_player_trades and not self.last_trade_rejected(player):
                player_deficit, player_excesses = self.timing.calculate_deficits_and_excesses(player.resources, cost)
                missing = next((resource for resource, amount in player_deficit.items() if amount > 0), None)
                if missing is not None:
                    sim_game_for_trade = sim_game_with_replaced_player(sim_game, player)
                    opponents = get_opponents(sim_game_for_trade, player.player_number)
                    trade_action = propose_trade(player, sim_game_for_trade, missing, player_excesses, opponents,
                                                 self.estimator)
                    if trade_action and utility > best_utility:
                        best_utility = utility
                        best_action = trade_action

        return best_action if best_action is not None else Action(ActionType.END_TURN)

    def choose_max_utility_action_with_candidate(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        candidates: List[CandidateExplanation],
        ignore_affordability: bool = False,
        include_player_trades: bool = True,
        use_time_discount: bool = True,
    ) -> Tuple[Action, CandidateExplanation]:
        """Choose the max utility action with candidate."""
        best_action: Optional[Action] = None
        best_candidate: Optional[CandidateExplanation] = None
        best_utility = float("-inf")

        for candidate_explanation in candidates:
            action = candidate_explanation.action
            utility = candidate_explanation.utility_total
            cost = calc_step_resources(action)
            if player.can_afford(cost) or ignore_affordability:
                if utility > best_utility:
                    best_utility = utility
                    best_action = action
                    best_candidate = candidate_explanation
                continue

            bank_trade_action = get_bank_trade_for_action(player, cost)
            if bank_trade_action and utility > best_utility:
                best_utility = utility
                best_action = bank_trade_action
                best_candidate = CandidateExplanation(
                    action=bank_trade_action,
                    full_plan=[bank_trade_action] + candidate_explanation.full_plan,
                    next_plan=list(candidate_explanation.next_plan),
                    waiting_resources=dict(candidate_explanation.waiting_resources),
                    etb=candidate_explanation.etb,
                    etw_before=candidate_explanation.etw_before,
                    etw_after=candidate_explanation.etw_after,
                    etw_delta=candidate_explanation.etw_delta,
                    utility_total=candidate_explanation.utility_total,
                    utility_self=candidate_explanation.utility_self,
                    utility_opponent=candidate_explanation.utility_opponent,
                    utility_special=candidate_explanation.utility_special,
                    utility_attention=candidate_explanation.utility_attention,
                    expected_vp_gain=candidate_explanation.expected_vp_gain,
                    reasons_for=[
                        Reason(
                            ReasonType.REQUIRES_TRADE,
                            ReasonLabel.REQUIRES_TRADE,
                            max(1.0, candidate_explanation.utility_total),
                        )
                    ] + list(candidate_explanation.reasons_for),
                    reasons_against=list(candidate_explanation.reasons_against),
                    metadata={
                        **candidate_explanation.metadata,
                        "trade_inserted": True,
                        "enabled_action": candidate_explanation.action,
                    },
                )

            if include_player_trades and not self.last_trade_rejected(player):
                player_deficit, player_excesses = self.timing.calculate_deficits_and_excesses(player.resources, cost)
                missing = next((resource for resource, amount in player_deficit.items() if amount > 0), None)
                if missing is not None:
                    sim_game_for_trade = sim_game_with_replaced_player(sim_game, player)
                    opponents = get_opponents(sim_game_for_trade, player.player_number)
                    trade_action = propose_trade(player, sim_game_for_trade, missing, player_excesses, opponents,
                                                 self.estimator)
                    if trade_action and utility > best_utility:
                        best_utility = utility
                        best_action = trade_action
                        best_candidate = CandidateExplanation(
                            action=trade_action,
                            full_plan=[trade_action] + candidate_explanation.full_plan,
                            next_plan=list(candidate_explanation.next_plan),
                            waiting_resources=dict(candidate_explanation.waiting_resources),
                            etb=candidate_explanation.etb,
                            etw_before=candidate_explanation.etw_before,
                            etw_after=candidate_explanation.etw_after,
                            etw_delta=candidate_explanation.etw_delta,
                            utility_total=candidate_explanation.utility_total,
                            utility_self=candidate_explanation.utility_self,
                            utility_opponent=candidate_explanation.utility_opponent,
                            utility_special=candidate_explanation.utility_special,
                            utility_attention=candidate_explanation.utility_attention,
                            expected_vp_gain=candidate_explanation.expected_vp_gain,
                            reasons_for=[
                                Reason(
                                    ReasonType.REQUIRES_TRADE,
                                    ReasonLabel.REQUIRES_TRADE,
                                    max(1.0, candidate_explanation.utility_total),
                                )
                            ] + list(candidate_explanation.reasons_for),
                            reasons_against=list(candidate_explanation.reasons_against),
                            metadata={
                                **candidate_explanation.metadata,
                                "trade_inserted": True,
                                "enabled_action": candidate_explanation.action,
                            },
                        )

        if best_action is not None and best_candidate is not None:
            return best_action, best_candidate

        fallback = self.evaluator.build_end_turn_candidate(
            player,
            sim_game,
            max((candidate_item.etw_before for candidate_item in candidates), default=0.0),
            max(candidates, key=lambda candidate_item: candidate_item.utility_total, default=None),
            use_time_discount=use_time_discount,
        )
        return fallback.action, fallback
