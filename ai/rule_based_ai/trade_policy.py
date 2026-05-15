from typing import List, Optional, Tuple

from ai.RandomAI import RandomAI
from ai.actions import Action, ActionType
from ai.simulation.SimGame import make_sim_game_for_player
from ai.simulation.SimPlayerState import SimPlayerState
from ai.simulation.board_sim_utils import get_opponents
from ai.tutor.explanations import (
    ActionExplanation,
    CandidateExplanation,
    ExplanationTemplate,
    Reason,
    ReasonLabel,
    ReasonType,
)
from ai.tutor.move_quality import strategic_turn_move_quality, trade_partner_move_quality
from ai.utils.trade_utils import respond_to_trade_batna, select_best_trade_partner
from config.StrategyWeights import StrategyWeights
from game.Game import Game
from game.Player import Player
from game.Resources import ResourceCount


class TradePolicy:
    def __init__(
            self,
            random_ai: RandomAI,
            etw_estimator,
            decision_config,
            use_strategic_move,
            planner_kwargs,
            etw_kwargs,
            trade_risk_kwargs):
        self.random_ai = random_ai
        self.etw_estimator = etw_estimator
        self.decision_config = decision_config
        self._use_strategic_move = use_strategic_move
        self._planner_kwargs = planner_kwargs
        self._etw_kwargs = etw_kwargs
        self._trade_risk_kwargs = trade_risk_kwargs

    def choose_trade_partner(
            self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount,
            available_players: List[Tuple[Player, Optional[ResourceCount]]]) -> Optional[
            Tuple[Player, Optional[ResourceCount]]]:
        """Choose the preferred trade partner from the available offers."""
        selection, _ = self.choose_trade_partner_with_explanation(player, game, selling, buying, available_players)
        return selection

    def choose_trade_partner_with_explanation(
            self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount,
            available_players: List[Tuple[Player, Optional[ResourceCount]]]) -> Tuple[
            Optional[Tuple[Player, Optional[ResourceCount]]], Optional[ActionExplanation]]:
        """Choose the trade partner with explanation."""
        if not self.decision_config.use_player_trading:
            return None, None
        if not self._use_strategic_move():
            selection = self.random_ai.choose_trade_partner(player, game, selling, buying, available_players)
            if selection is None:
                return None, None
            chosen_player, counter = selection
            explanation = self.explain_trade_partner_choice(
                player, game, selling, buying, available_players, chosen_player, counter)
            return selection, explanation

        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        available_sim_players = [(SimPlayerState(p, opponent=True), offer) for (p, offer) in available_players]
        selection = select_best_trade_partner(
            player_sim=sim_us,
            sim_game=sim_game,
            etw_estimator=self.etw_estimator,
            selling_orig=selling,
            buying=buying,
            available_players=available_sim_players,
            **self._trade_risk_kwargs(),
        )
        if selection is None:
            return None, None

        chosen_sim_player, counter = selection
        chosen_player = next(p for p in game.players if p.player_number == chosen_sim_player.player_number)
        explanation = self._build_trade_partner_explanation(
            player, sim_us, sim_game, selling, buying, available_players, chosen_player, counter)
        return (chosen_player, counter), explanation

    def explain_trade_partner_choice(
            self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount,
            available_players: List[Tuple[Player, Optional[ResourceCount]]], chosen_player: Player,
            counter: Optional[ResourceCount]) -> ActionExplanation:
        """Handle explain trade partner choice."""
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        return self._build_trade_partner_explanation(
            player, sim_us, sim_game, selling, buying, available_players, chosen_player, counter)

    def respond_to_trade(
            self, player: Player, game: Game, opponent: Player, selling: ResourceCount,
            buying: ResourceCount) -> Tuple[bool, Optional[ResourceCount]]:
        """Handle respond to trade."""
        accepted, counter, _ = self.respond_to_trade_with_explanation(player, game, opponent, selling, buying)
        return accepted, counter

    def respond_to_trade_with_explanation(
            self, player: Player, game: Game, opponent: Player, selling: ResourceCount,
            buying: ResourceCount) -> Tuple[bool, Optional[ResourceCount], Optional[ActionExplanation]]:
        """Handle respond to trade with explanation."""
        if not self.decision_config.use_player_trading:
            return False, None, None
        if not self._use_strategic_move():
            accepted, counter = self.random_ai.respond_to_trade(player, game, opponent, selling, buying)
            explanation = self.explain_trade_response_choice(
                player, game, opponent, selling, buying, accepted, counter)
            return accepted, counter, explanation

        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        opponent_sim = SimPlayerState(opponent, opponent=True)
        opponents = get_opponents(sim_game, player.player_number)
        accepted, counter = respond_to_trade_batna(
            player_sim=sim_us,
            opponent_sim=opponent_sim,
            sim_game=sim_game,
            etw_estimator=self.etw_estimator,
            selling_to_us=selling,
            buying_from_us=buying,
            opponents=opponents,
            **{
                key: value
                for key, value in self._trade_risk_kwargs().items()
                if key != "leader_penalty"
            },
        )
        explanation = self._build_trade_response_explanation(
            player, opponent, sim_us, opponent_sim, sim_game, selling, buying, opponents, accepted, counter)
        return accepted, counter, explanation

    def explain_trade_response_choice(
            self, player: Player, game: Game, opponent: Player, selling: ResourceCount,
            buying: ResourceCount, accepted: bool, counter: Optional[ResourceCount]) -> ActionExplanation:
        """Handle explain trade response choice."""
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        opponent_sim = SimPlayerState(opponent, opponent=True)
        opponents = get_opponents(sim_game, player.player_number)
        return self._build_trade_response_explanation(
            player, opponent, sim_us, opponent_sim, sim_game, selling, buying, opponents, accepted, counter)

    def _build_trade_partner_explanation(
            self, player: Player, sim_us: SimPlayerState, sim_game, selling: ResourceCount, buying: ResourceCount,
            available_players: List[Tuple[Player, Optional[ResourceCount]]], chosen_player: Player,
            counter: Optional[ResourceCount]) -> ActionExplanation:
        """Build the trade partner explanation."""
        batna_etw = self.etw_estimator.estimated_time_to_win(
            sim_us, sim_game, False, **self._etw_kwargs(include_player_trades=False))
        candidate_explanations: List[CandidateExplanation] = []
        all_sims = [sim_us] + [SimPlayerState(opp, opponent=True) for opp, _ in available_players]
        etw_by_player = {
            sim_player: self.etw_estimator.estimated_time_to_win(
                sim_player.copy(), sim_game, False, **self._etw_kwargs(include_player_trades=False))
            for sim_player in all_sims
        }
        leading_sim = min(etw_by_player, key=etw_by_player.get)

        for opponent, offered_counter in available_players:
            opp_sim = SimPlayerState(opponent, opponent=True)
            payment = offered_counter if offered_counter is not None else selling
            if any(sim_us.resources.get(resource, 0) < amount for resource, amount in payment.items()):
                continue

            sim_after = sim_us.copy()
            sim_after.remove_resources(payment)
            sim_after.add_resources(buying)
            sim_game_after = make_sim_game_for_player(sim_game.game, player)
            sim_game_after.overlay.set_sim_player(sim_after)
            etw_after = self.etw_estimator.estimated_time_to_win(
                sim_after, sim_game_after, False, **self._etw_kwargs(include_player_trades=False))
            delta_ai = batna_etw - etw_after
            if delta_ai <= 0:
                continue

            delta_opp = 0.0
            if self.decision_config.use_opponent_interference:
                etw_opp_before = self.etw_estimator.estimated_time_to_win(
                    opp_sim, sim_game, False, **self._etw_kwargs(include_player_trades=False))
                sim_opp_after = opp_sim.copy()
                sim_opp_after.add_resources(payment)
                sim_opp_after.remove_resources(buying)
                sim_game_opp_after = make_sim_game_for_player(sim_game.game, player)
                sim_game_opp_after.overlay.set_sim_player(sim_opp_after)
                etw_opp_after = self.etw_estimator.estimated_time_to_win(
                    sim_opp_after, sim_game_opp_after, False, **self._etw_kwargs(include_player_trades=False))
                delta_opp = max(0.0, etw_opp_before - etw_opp_after)

            is_leader = opp_sim == leading_sim
            vp_gap = opp_sim.victory_points() - sim_us.victory_points()
            is_close = vp_gap >= -StrategyWeights.CLOSE_OPPONENT_VP_GAP
            lambda_risk = StrategyWeights.LAMBDA_RISK_LEADER if is_leader else StrategyWeights.LAMBDA_RISK_BASE
            if (
                self.decision_config.use_opponent_interference
                and (is_close or is_leader)
                and delta_opp >= lambda_risk * delta_ai
            ):
                continue

            reasons_for = [Reason(ReasonType.FASTEST_PROGRESS, ReasonLabel.TRADE_PARTNER_BEST_ETW, delta_ai)]
            if offered_counter is not None:
                saved_resources = max(0.0, float(sum(selling.values()) - sum(payment.values())))
                reasons_for.append(Reason(
                    ReasonType.HEURISTIC_CHOICE,
                    ReasonLabel.TRADE_PARTNER_COUNTER_VALUE,
                    saved_resources,
                ))
            if self.decision_config.use_opponent_interference and (is_close or is_leader):
                safety_margin = max(0.0, lambda_risk * delta_ai - delta_opp)
                reasons_for.append(Reason(
                    ReasonType.HEURISTIC_CHOICE,
                    ReasonLabel.TRADE_PARTNER_SAFE_OPPONENT,
                    safety_margin,
                ))

            action = Action(ActionType.TRADE_WITH_PLAYER, (payment, buying))
            candidate_explanations.append(CandidateExplanation(
                action=action,
                full_plan=[action],
                etw_before=batna_etw,
                etw_after=etw_after,
                etw_delta=delta_ai,
                utility_total=batna_etw - etw_after - (
                    StrategyWeights.TRADE_LEADER_PENALTY
                    if self.decision_config.use_opponent_interference and is_leader else 0.0
                ),
                reasons_for=reasons_for,
                metadata={
                    "template": ExplanationTemplate.TRADE_PARTNER,
                    "partner_name": opponent.name,
                    "partner_player_number": opponent.player_number,
                    "payment": payment,
                    "buying": buying,
                    "self_gain": delta_ai,
                    "opponent_gain": delta_opp,
                    "partner_is_leader": is_leader,
                },
            ))

        candidate_explanations.sort(key=lambda candidate: candidate.utility_total, reverse=True)
        chosen_candidate = next((
            candidate for candidate in candidate_explanations
            if candidate.metadata.get("partner_player_number") == chosen_player.player_number
            and candidate.metadata.get("payment") == (counter if counter is not None else selling)
        ), None)
        if chosen_candidate is None:
            action = Action(ActionType.TRADE_WITH_PLAYER, ((counter if counter is not None else selling), buying))
            chosen_candidate = CandidateExplanation(
                action=action,
                full_plan=[action],
                reasons_for=[Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.TRADE_PARTNER_BEST_ETW, 0.0)],
                metadata={
                    "template": ExplanationTemplate.TRADE_PARTNER,
                    "partner_name": chosen_player.name,
                    "partner_player_number": chosen_player.player_number,
                    "payment": counter if counter is not None else selling,
                    "buying": buying,
                },
            )
            candidate_explanations.insert(0, chosen_candidate)
        alternatives = [candidate for candidate in candidate_explanations if candidate is not chosen_candidate][:3]
        return ActionExplanation(
            chosen_action=chosen_candidate.action,
            chosen_candidate=chosen_candidate,
            alternatives=alternatives,
            move_quality=trade_partner_move_quality(
                self_gain=float(chosen_candidate.metadata.get("self_gain", 0.0)),
                opponent_gain=float(chosen_candidate.metadata.get("opponent_gain", 0.0)),
                partner_is_leader=bool(chosen_candidate.metadata.get("partner_is_leader", False)),
            ),
            metadata={"template": ExplanationTemplate.TRADE_PARTNER},
        )

    def _build_trade_response_explanation(
            self, player: Player, opponent: Player, sim_us: SimPlayerState, opponent_sim: SimPlayerState, sim_game,
            selling_to_us: ResourceCount, buying_from_us: ResourceCount, opponents: List[SimPlayerState],
            accepted: bool, counter: Optional[ResourceCount]) -> ActionExplanation:
        """Build the trade response explanation."""
        etw_before = self.etw_estimator.estimated_time_to_win(
            sim_us, sim_game, False, **self._etw_kwargs(include_player_trades=False))

        offered_after = sim_us.copy()
        offered_after.add_resources(selling_to_us)
        offered_after.remove_resources(buying_from_us)
        offered_game = make_sim_game_for_player(sim_game.game, player)
        offered_game.overlay.set_sim_player(offered_after)
        etw_after_offer = self.etw_estimator.estimated_time_to_win(
            offered_after, offered_game, False, **self._etw_kwargs(include_player_trades=False))
        delta_offer = etw_before - etw_after_offer

        all_players = [sim_us, *opponents]
        etw_by_player = {
            sim_player: self.etw_estimator.estimated_time_to_win(
                sim_player.copy(), sim_game, False, **self._etw_kwargs(include_player_trades=False))
            for sim_player in all_players
        }
        leading = min(etw_by_player, key=etw_by_player.get)
        is_leader = opponent_sim == leading
        vp_gap = opponent_sim.victory_points() - sim_us.victory_points()
        is_close = vp_gap >= -StrategyWeights.CLOSE_OPPONENT_VP_GAP
        lambda_risk = StrategyWeights.LAMBDA_RISK_LEADER if is_leader else StrategyWeights.LAMBDA_RISK_BASE

        delta_opp_offer = 0.0
        if self.decision_config.use_opponent_interference:
            opp_before = self.etw_estimator.estimated_time_to_win(
                opponent_sim, sim_game, False, **self._etw_kwargs(include_player_trades=False))
            opp_after_offer = opponent_sim.copy()
            opp_after_offer.remove_resources(selling_to_us)
            opp_after_offer.add_resources(buying_from_us)
            opp_game = make_sim_game_for_player(sim_game.game, player)
            opp_game.overlay.set_sim_player(opp_after_offer)
            opp_after = self.etw_estimator.estimated_time_to_win(
                opp_after_offer, opp_game, False, **self._etw_kwargs(include_player_trades=False))
            delta_opp_offer = max(0.0, opp_before - opp_after)

        decision = "reject"
        payment = buying_from_us
        reasons_for: List[Reason] = []
        chosen_action = Action(ActionType.TRADE_WITH_PLAYER, (payment, selling_to_us))
        etw_after = etw_after_offer
        etw_delta = delta_offer

        if accepted and counter is None:
            decision = "accept"
            reasons_for.append(Reason(
                ReasonType.FASTEST_PROGRESS,
                ReasonLabel.TRADE_RESPONSE_ACCEPT_VALUE,
                delta_offer,
            ))
            if self.decision_config.use_opponent_interference and (is_close or is_leader):
                reasons_for.append(Reason(
                    ReasonType.HEURISTIC_CHOICE,
                    ReasonLabel.TRADE_PARTNER_SAFE_OPPONENT,
                    max(0.0, lambda_risk * delta_offer - delta_opp_offer),
                ))
        elif accepted and counter is not None:
            decision = "counter"
            chosen_action = Action(ActionType.TRADE_WITH_PLAYER, (counter, selling_to_us))
            counter_after = sim_us.copy()
            counter_after.add_resources(selling_to_us)
            counter_after.remove_resources(counter)
            counter_game = make_sim_game_for_player(sim_game.game, player)
            counter_game.overlay.set_sim_player(counter_after)
            etw_after = self.etw_estimator.estimated_time_to_win(
                counter_after, counter_game, False, **self._etw_kwargs(include_player_trades=False))
            etw_delta = etw_before - etw_after
            reasons_for.append(Reason(
                ReasonType.FASTEST_PROGRESS,
                ReasonLabel.TRADE_RESPONSE_COUNTER_VALUE,
                etw_delta,
            ))
        else:
            if delta_offer <= 0:
                reasons_for.append(Reason(
                    ReasonType.HEURISTIC_CHOICE,
                    ReasonLabel.TRADE_RESPONSE_REJECT_NO_GAIN,
                    abs(delta_offer),
                ))
            else:
                reasons_for.append(Reason(
                    ReasonType.HEURISTIC_CHOICE,
                    ReasonLabel.TRADE_RESPONSE_REJECT_RISK,
                    delta_opp_offer,
                ))

        candidate = CandidateExplanation(
            action=chosen_action,
            full_plan=[chosen_action],
            etw_before=etw_before,
            etw_after=etw_after,
            etw_delta=etw_delta,
            utility_total=max(0.0, etw_delta),
            reasons_for=reasons_for,
            metadata={
                "template": ExplanationTemplate.TRADE_RESPONSE,
                "decision": decision,
                "opponent_name": opponent.name,
                "turn_player_number": opponent.player_number,
                "selling_to_us": selling_to_us,
                "payment": buying_from_us,
                "counter_payment": counter,
            },
        )
        return ActionExplanation(
            chosen_action=chosen_action,
            chosen_candidate=candidate,
            move_quality=strategic_turn_move_quality(candidate),
            metadata={
                "template": ExplanationTemplate.TRADE_RESPONSE,
                "turn_player_number": opponent.player_number,
            },
        )
