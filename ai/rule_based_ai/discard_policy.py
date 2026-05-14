from typing import Dict, List, Optional, Tuple

from ai.RandomAI import RandomAI
from ai.actions import Action, ActionType
from ai.simulation.SimGame import make_sim_game_for_player
from ai.tutor.explanations import (
    ActionExplanation,
    CandidateExplanation,
    ExplanationTemplate,
    Reason,
    ReasonLabel,
    ReasonType,
)
from ai.tutor.move_quality import discard_move_quality
from ai.utils.resource_utils import calc_step_resources
from game.Game import Game
from game.Player import Player
from game.PlayerAssets import Buildable
from game.Resources import Resource, ResourceCount


class DiscardPolicy:
    def __init__(self, random_ai: RandomAI, etw_estimator, use_strategic_move, planner_kwargs):
        self.random_ai = random_ai
        self.etw_estimator = etw_estimator
        self._use_strategic_move = use_strategic_move
        self._planner_kwargs = planner_kwargs

    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        discard, _ = self.select_discard_resources_with_explanation(player, game, num_resources)
        return discard

    def select_discard_resources_with_explanation(
            self, player: Player, game: Game, num_resources: int) -> Tuple[ResourceCount, Optional[ActionExplanation]]:
        if not self._use_strategic_move():
            discard = self.random_ai.select_discard_resources(player, game, num_resources)
            return discard, self.explain_discard_choice(player, game, discard)

        current_resources, needed, best_plan_explanation = self._discard_context(player, game)
        best_discard: Optional[ResourceCount] = None
        best_explanation: Optional[ActionExplanation] = None
        best_quality = float("-inf")

        for discard in self._legal_discard_candidates(current_resources, num_resources):
            explanation = self._evaluate_discard_choice(
                discard, current_resources, needed, best_plan_explanation)
            if explanation.move_quality > best_quality:
                best_quality = explanation.move_quality
                best_discard = discard
                best_explanation = explanation

        if best_discard is None:
            best_discard = {resource: 0 for resource in Resource}
            best_explanation = self._evaluate_discard_choice(
                best_discard, current_resources, needed, best_plan_explanation)
        return best_discard, best_explanation

    def explain_discard_choice(
            self, player: Player, game: Game, discard: ResourceCount) -> ActionExplanation:
        current_resources, needed, best_plan_explanation = self._discard_context(player, game)
        normalized_discard = {resource: int(discard.get(resource, 0)) for resource in Resource}
        return self._evaluate_discard_choice(
            normalized_discard, current_resources, needed, best_plan_explanation)

    def _discard_context(
            self, player: Player, game: Game) -> Tuple[ResourceCount, ResourceCount, ActionExplanation]:
        current_resources = {resource: int(player.resources.get(resource, 0)) for resource in Resource}
        sim_game = make_sim_game_for_player(game, player)
        best_plan_explanation = self.etw_estimator.calculate_best_game_action_with_explanation(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=False,
            **self._planner_kwargs(),
        )
        needed = {
            resource: int(calc_step_resources(best_plan_explanation.chosen_action).get(resource, 0))
            for resource in Resource
        }
        return current_resources, needed, best_plan_explanation

    def _evaluate_discard_choice(
            self, discard: ResourceCount, current_resources: ResourceCount, needed: ResourceCount,
            best_plan_explanation: ActionExplanation) -> ActionExplanation:
        return self._build_discard_explanation(discard, current_resources, needed, best_plan_explanation)

    @staticmethod
    def _legal_discard_candidates(
            current_resources: ResourceCount, num_resources: int) -> List[ResourceCount]:
        resources = list(Resource)
        candidates: List[ResourceCount] = []

        def build_candidate(index: int, remaining: int, partial: ResourceCount) -> None:
            if index == len(resources):
                if remaining == 0:
                    candidates.append(partial.copy())
                return

            resource = resources[index]
            max_take = min(remaining, int(current_resources.get(resource, 0)))
            for amount in range(max_take + 1):
                partial[resource] = amount
                build_candidate(index + 1, remaining - amount, partial)

        build_candidate(0, num_resources, {resource: 0 for resource in resources})
        return candidates

    def _build_discard_explanation(
            self, discard: ResourceCount, current_resources: ResourceCount, needed: ResourceCount,
            best_plan_explanation: ActionExplanation) -> ActionExplanation:
        protected_resources = sum(min(needed.get(resource, 0), amount) for resource, amount in discard.items())
        surplus_discarded = sum(discard.values()) - protected_resources
        plan_metadata = self._discard_plan_metadata(best_plan_explanation)
        reasons_for = [
            Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.DISCARD_PROTECTS_PLAN, float(sum(needed.values()))),
            Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.DISCARD_USES_SURPLUS, float(max(0, surplus_discarded))),
        ]
        action = Action(ActionType.END_TURN, discard)
        candidate = CandidateExplanation(
            action=action,
            full_plan=[action],
            reasons_for=reasons_for,
            metadata={
                "template": ExplanationTemplate.DISCARD_RESOURCES,
                "discard_resources": discard,
                **plan_metadata,
            },
        )
        return ActionExplanation(
            chosen_action=action,
            chosen_candidate=candidate,
            move_quality=discard_move_quality(discard, current_resources, needed),
            metadata={"template": ExplanationTemplate.DISCARD_RESOURCES},
        )

    @staticmethod
    def _discard_plan_metadata(explanation: ActionExplanation) -> Dict[str, object]:
        action = explanation.chosen_action
        protected_action = DiscardPolicy._protected_follow_up_action_from_explanation(explanation)
        metadata: Dict[str, object] = {"protected_action": protected_action}

        trade_action = None
        if action.type in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER):
            trade_action = action
        elif action.type == ActionType.END_TURN and explanation.chosen_candidate.next_plan:
            first_next = explanation.chosen_candidate.next_plan[0]
            if first_next.type in (ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER):
                trade_action = first_next

        if trade_action is not None:
            payload = trade_action.payload
            if isinstance(payload, tuple) and len(payload) == 2:
                _, buying = payload
                target_resources = [resource for resource, amount in buying.items() if amount > 0]
                if target_resources:
                    metadata["trade_target_resources"] = target_resources

                follow_up_action = protected_action if protected_action != trade_action else (
                    DiscardPolicy._trade_follow_up_action_for_resources(target_resources)
                )
                if follow_up_action is not None:
                    metadata["trade_follow_up_action"] = follow_up_action

        return metadata

    @staticmethod
    def _protected_follow_up_action_from_explanation(explanation: ActionExplanation) -> Action:
        action = explanation.chosen_action
        if action.type == ActionType.END_TURN and explanation.chosen_candidate.next_plan:
            return explanation.chosen_candidate.next_plan[-1]
        if explanation.chosen_candidate.full_plan and explanation.chosen_candidate.full_plan[-1] != action:
            return explanation.chosen_candidate.full_plan[-1]
        return action

    @staticmethod
    def _trade_follow_up_action_for_resources(resources: List[Resource]) -> Optional[Action]:
        resource_set = set(resources)
        if Resource.ORE in resource_set and Resource.WHEAT in resource_set:
            return Action(ActionType.BUILD, (Buildable.CITY, None))
        if Resource.WOOD in resource_set and Resource.BRICK in resource_set and Resource.SHEEP in resource_set:
            return Action(ActionType.BUILD, (Buildable.SETTLEMENT, None))
        if Resource.ORE in resource_set and Resource.SHEEP in resource_set and Resource.WHEAT in resource_set:
            return Action(ActionType.BUY_DEV_CARD)
        if Resource.WOOD in resource_set and Resource.BRICK in resource_set:
            return Action(ActionType.BUILD, (Buildable.ROAD, None))
        return None

    @staticmethod
    def action_summary_text(action: Action) -> str:
        if action.type == ActionType.BUILD and isinstance(action.payload, tuple) and len(action.payload) >= 1:
            buildable = action.payload[0]
            if hasattr(buildable, "name"):
                return f"build a {buildable.name.lower()}"
        if action.type == ActionType.BUY_DEV_CARD:
            return "buy a development card"
        if action.type == ActionType.TRADE_WITH_BANK:
            return "make a bank trade"
        if action.type == ActionType.TRADE_WITH_PLAYER:
            return "make a player trade"
        if action.type == ActionType.PLAY_DEV_CARD:
            return "play a development card"
        return "take the next planned action"
