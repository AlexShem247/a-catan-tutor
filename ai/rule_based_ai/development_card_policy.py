
from ai.actions import Action, ActionType, Phase
from ai.RandomAI import RandomAI
from ai.simulation.board_sim_utils import get_opponents
from ai.simulation.SimGame import make_sim_game_for_player
from ai.tutor.explanations import (ActionExplanation, AssumptionCode, CandidateExplanation, ExplanationTemplate, Reason,
                                   ReasonLabel, ReasonType)
from ai.tutor.move_quality import monopoly_move_quality, strategic_turn_move_quality, year_of_plenty_move_quality
from ai.utils.action_utils import play_development_card_action
from ai.utils.resource_utils import calc_step_resources
from game.Game import Game
from game.Player import Player, PlayerNumber
from game.PlayerAssets import DevelopmentCardType
from game.Resources import Resource, ResourceCount


class DevelopmentCardPolicy:

    def __init__(self, rng, random_ai: RandomAI, etw_estimator, decision_config, use_strategic_move, planner_kwargs,
                 etw_kwargs):
        self.rng = rng
        self.random_ai = random_ai
        self.etw_estimator = etw_estimator
        self.decision_config = decision_config
        self._use_strategic_move = use_strategic_move
        self._planner_kwargs = planner_kwargs
        self._etw_kwargs = etw_kwargs

    def select_year_of_plenty_resources(self, player: Player, game: Game) -> ResourceCount:
        """Select resources for the Year of Plenty card."""
        resources, _ = self.select_year_of_plenty_resources_with_explanation(player, game)
        return resources

    def select_year_of_plenty_resources_with_explanation(
            self, player: Player, game: Game) -> tuple[ResourceCount, ActionExplanation | None]:
        """Select the year of plenty resources with explanation."""
        if not self._use_strategic_move():
            selected = self.random_ai.select_year_of_plenty_resources(player, game)
            return selected, self.explain_year_of_plenty_choice(player, game, selected)

        sim_game = make_sim_game_for_player(game, player)
        best_plan_explanation = self.etw_estimator.calculate_best_game_action_with_explanation(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=False,
            **self._planner_kwargs(),
        )
        primary_action, target_action, target_shortfalls, already_had_next_step = self._year_of_plenty_plan_target(
            player, best_plan_explanation)

        shortfall_priority: list[Resource] = []
        for resource in Resource:
            shortfall_priority.extend([resource] * target_shortfalls[resource])

        if not shortfall_priority and target_action is not None:
            target_cost = calc_step_resources(target_action)
            for resource in Resource:
                shortfall_priority.extend([resource] * target_cost.get(resource, 0))

        if not shortfall_priority:
            shortfall_priority = self._flexible_year_of_plenty_priority(player)

        picked = shortfall_priority[:2]
        selected: ResourceCount = {resource: 0 for resource in Resource}
        for resource in picked:
            selected[resource] += 1

        clearly_supports_follow_up = (target_action is not None and 0 < sum(selected.values()) == sum(
            min(selected[resource], target_shortfalls[resource]) for resource in Resource))
        explanation = self._build_year_of_plenty_explanation(
            selected,
            primary_action,
            target_action if clearly_supports_follow_up or already_had_next_step else None,
            clearly_supports_follow_up,
            already_had_next_step,
            best_plan_explanation,
        )
        return selected, explanation

    def explain_year_of_plenty_choice(self, player: Player, game: Game, selected: ResourceCount) -> ActionExplanation:
        """Handle explain year of plenty choice."""
        normalized_selected = {resource: int(selected.get(resource, 0)) for resource in Resource}
        sim_game = make_sim_game_for_player(game, player)
        best_plan_explanation = self.etw_estimator.calculate_best_game_action_with_explanation(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=False,
            **self._planner_kwargs(),
        )
        primary_action, target_action, target_shortfalls, already_had_next_step = self._year_of_plenty_plan_target(
            player, best_plan_explanation)
        clearly_supports_follow_up = (target_action is not None and 0 < sum(normalized_selected.values()) == sum(
            min(normalized_selected[resource], target_shortfalls[resource]) for resource in Resource))
        return self._build_year_of_plenty_explanation(
            normalized_selected,
            primary_action,
            target_action if clearly_supports_follow_up or already_had_next_step else None,
            clearly_supports_follow_up,
            already_had_next_step,
            best_plan_explanation,
        )

    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        """Select the resource type for the Monopoly card."""
        resource, _ = self.select_monopoly_resource_with_explanation(player, game)
        return resource

    def select_monopoly_resource_with_explanation(self, player: Player,
                                                  game: Game) -> tuple[Resource, ActionExplanation | None]:
        """Select the monopoly resource with explanation."""
        if not self._use_strategic_move():
            chosen = self.random_ai.select_monopoly_resource(player, game)
            return chosen, self.explain_monopoly_choice(player, game, chosen)

        if not self.decision_config.use_opponent_interference:
            best_self_action = self.etw_estimator.calculate_best_game_action(
                sim_game=make_sim_game_for_player(game, player),
                player_number=player.player_number,
                dev_played=False,
                ignore_affordability=True,
                **self._planner_kwargs(ignore_opponents=True),
            )
            required = calc_step_resources(best_self_action)
            candidates = [resource for resource, amount in required.items() if amount > 0]
            chosen = self.rng.choice(candidates) if candidates else self.rng.choice(list(Resource))
            explanation = self._build_monopoly_resource_explanation(chosen, 0, float(required.get(chosen, 0)), 0.0)
            return chosen, explanation

        need_counts: dict[Resource, int] = {resource: 0 for resource in Resource}
        held_counts: dict[Resource, int] = {resource: 0 for resource in Resource}
        leader_counts: dict[Resource, int] = {resource: 0 for resource in Resource}
        leader_vp = max(
            (opponent.calc_victory_points()[0] for opponent in game.players if opponent != player),
            default=0,
        )

        for opponent in game.players:
            if opponent == player:
                continue
            sim_game_opp = make_sim_game_for_player(game, opponent)
            best_action = self.etw_estimator.calculate_best_game_action(
                sim_game=sim_game_opp,
                player_number=opponent.player_number,
                dev_played=False,
                ignore_affordability=True,
                **self._planner_kwargs(ignore_opponents=True),
            )
            required = calc_step_resources(best_action)
            for resource, amount in required.items():
                if amount > 0:
                    need_counts[resource] += 1
            for resource, amount in opponent.resources.items():
                held_counts[resource] += amount
                if opponent.calc_victory_points()[0] == leader_vp:
                    leader_counts[resource] += amount

        max_count = max(need_counts.values())
        candidates = [resource for resource, count in need_counts.items() if count == max_count]
        chosen = self.rng.choice(candidates)
        best_self_action = self.etw_estimator.calculate_best_game_action(
            sim_game=make_sim_game_for_player(game, player),
            player_number=player.player_number,
            dev_played=False,
            ignore_affordability=True,
            **self._planner_kwargs(ignore_opponents=True),
        )
        self_gain_efficiency = float(calc_step_resources(best_self_action).get(chosen, 0))
        leader_share = leader_counts[chosen] / max(held_counts[chosen], 1) if held_counts[chosen] > 0 else 0.0
        explanation = self._build_monopoly_resource_explanation(
            chosen,
            held_counts[chosen],
            self_gain_efficiency,
            leader_share,
        )
        return chosen, explanation

    def explain_monopoly_choice(self, player: Player, game: Game, chosen: Resource) -> ActionExplanation:
        """Handle explain monopoly choice."""
        held_counts: dict[Resource, int] = {resource: 0 for resource in Resource}
        leader_counts: dict[Resource, int] = {resource: 0 for resource in Resource}
        leader_vp = max(
            (opponent.calc_victory_points()[0] for opponent in game.players if opponent != player),
            default=0,
        )
        for opponent in game.players:
            if opponent == player:
                continue
            for resource, amount in opponent.resources.items():
                held_counts[resource] += amount
                if opponent.calc_victory_points()[0] == leader_vp:
                    leader_counts[resource] += amount
        best_self_action = self.etw_estimator.calculate_best_game_action(
            sim_game=make_sim_game_for_player(game, player),
            player_number=player.player_number,
            dev_played=False,
            ignore_affordability=True,
            **self._planner_kwargs(ignore_opponents=True),
        )
        self_gain_efficiency = float(calc_step_resources(best_self_action).get(chosen, 0))
        leader_share = leader_counts[chosen] / max(held_counts[chosen], 1) if held_counts[chosen] > 0 else 0.0
        return self._build_monopoly_resource_explanation(
            chosen,
            held_counts[chosen],
            self_gain_efficiency,
            leader_share,
        )

    def select_pre_roll_action_with_explanation(self, player: Player, game: Game,
                                                dev_played: bool) -> tuple[Action, ActionExplanation] | None:
        """Select the pre roll action with explanation."""
        if dev_played or not self.decision_config.use_development_cards:
            return None

        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        dev_candidates = play_development_card_action(sim_us, sim_game)
        if not dev_candidates:
            return None

        etw_before = self.etw_estimator.estimated_time_to_win(sim_us.copy(), sim_game, dev_played, **self._etw_kwargs())
        opponents_etw_before: dict[PlayerNumber, float] = {}
        if self.decision_config.use_opponent_interference:
            opponents_etw_before = {
                opp.player_number: self.etw_estimator.estimated_time_to_win(opp.copy(), sim_game, False,
                                                                            **self._etw_kwargs())
                for opp in get_opponents(sim_game, player.player_number)
            }

        explained_candidates = self.etw_estimator.evaluate_candidates_with_explanations(
            sim_us,
            sim_game,
            dev_played,
            dev_candidates,
            etw_before,
            opponents_etw_before,
            include_player_trades=self.decision_config.use_player_trading,
            allow_development_cards=self.decision_config.use_development_cards,
            use_planning=self.decision_config.use_etw_planning,
            use_time_discount=self.decision_config.use_time_discount,
        )
        if not explained_candidates:
            return None

        best_candidate = explained_candidates[0]
        if best_candidate.utility_total <= 0.0:
            return None

        explanation = ActionExplanation(
            chosen_action=best_candidate.action,
            chosen_candidate=best_candidate,
            alternatives=explained_candidates[1:4],
            move_quality=strategic_turn_move_quality(
                best_candidate,
                explained_candidates[1].utility_total if len(explained_candidates) > 1 else None,
                explained_candidates[-1].utility_total if explained_candidates else None,
            ),
            assumptions=[AssumptionCode.PRE_ROLL_DEV_ONLY],
            metadata={"phase": Phase.PRE_ROLL.name.lower()},
        )
        return best_candidate.action, explanation

    def explain_pre_roll_dev_choice(self, player: Player, game: Game,
                                    card_type: DevelopmentCardType) -> ActionExplanation:
        """Handle explain pre roll dev choice."""
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        dev_candidates = play_development_card_action(sim_us, sim_game)
        etw_before = self.etw_estimator.estimated_time_to_win(sim_us.copy(), sim_game, False, **self._etw_kwargs())
        opponents_etw_before: dict[PlayerNumber, float] = {}
        if self.decision_config.use_opponent_interference:
            opponents_etw_before = {
                opp.player_number: self.etw_estimator.estimated_time_to_win(opp.copy(), sim_game, False,
                                                                            **self._etw_kwargs())
                for opp in get_opponents(sim_game, player.player_number)
            }
        explained_candidates = self.etw_estimator.evaluate_candidates_with_explanations(
            sim_us,
            sim_game,
            False,
            dev_candidates,
            etw_before,
            opponents_etw_before,
            include_player_trades=self.decision_config.use_player_trading,
            allow_development_cards=self.decision_config.use_development_cards,
            use_planning=self.decision_config.use_etw_planning,
            use_time_discount=self.decision_config.use_time_discount,
        )
        chosen_candidate = next(
            (candidate for candidate in explained_candidates
             if candidate.action.type == ActionType.PLAY_DEV_CARD and candidate.action.payload == card_type), None)
        if chosen_candidate is None:
            chosen_candidate = CandidateExplanation(
                action=Action(ActionType.PLAY_DEV_CARD, card_type),
                full_plan=[Action(ActionType.PLAY_DEV_CARD, card_type)],
                reasons_for=[],
            )
        alternatives = [candidate for candidate in explained_candidates if candidate is not chosen_candidate][:3]
        return ActionExplanation(
            chosen_action=chosen_candidate.action,
            chosen_candidate=chosen_candidate,
            alternatives=alternatives,
            move_quality=strategic_turn_move_quality(
                chosen_candidate,
                alternatives[0].utility_total if alternatives else None,
                explained_candidates[-1].utility_total if explained_candidates else None,
            ),
            assumptions=[AssumptionCode.PRE_ROLL_DEV_ONLY],
            metadata={"phase": Phase.PRE_ROLL.name.lower()},
        )

    def _build_year_of_plenty_explanation(self, selected: ResourceCount, primary_action: Action | None,
                                          target_action: Action | None, clearly_supports_follow_up: bool,
                                          already_had_next_step: bool,
                                          best_plan_explanation: ActionExplanation) -> ActionExplanation:
        """Build the year of plenty explanation."""
        reasons_for: list[Reason] = []
        if clearly_supports_follow_up and target_action is not None:
            reasons_for.append(
                Reason(
                    ReasonType.QUICK_TO_EXECUTE,
                    ReasonLabel.YOP_FILLS_SHORTFALL,
                    float(sum(selected.values())),
                ))
            reasons_for.append(
                Reason(
                    ReasonType.HEURISTIC_CHOICE,
                    ReasonLabel.YOP_SUPPORTS_FOLLOW_UP,
                    1.0,
                    {
                        "primary_action": primary_action,
                        "follow_up_action": target_action,
                        "already_had_next_step": already_had_next_step,
                    },
                ))
        elif target_action is not None:
            reasons_for.append(
                Reason(
                    ReasonType.HEURISTIC_CHOICE,
                    ReasonLabel.YOP_SUPPORTS_FOLLOW_UP,
                    1.0,
                    {
                        "primary_action": primary_action,
                        "follow_up_action": target_action,
                        "already_had_next_step": already_had_next_step,
                    },
                ))
        else:
            reasons_for.append(Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.YOP_FLEXIBLE_PICK, 1.0))

        action = Action(ActionType.PLAY_DEV_CARD, DevelopmentCardType.YEAR_OF_PLENTY)
        candidate = CandidateExplanation(
            action=action,
            full_plan=[action],
            reasons_for=reasons_for,
            metadata={
                "template": ExplanationTemplate.YEAR_OF_PLENTY_RESOURCES,
                "selected_resources": selected,
                "primary_action": primary_action,
                "follow_up_action": target_action,
                "supports_follow_up": clearly_supports_follow_up,
                "already_had_next_step": already_had_next_step,
            },
        )
        return ActionExplanation(
            chosen_action=action,
            chosen_candidate=candidate,
            move_quality=year_of_plenty_move_quality(
                etw_gain=max(0.0, best_plan_explanation.chosen_candidate.etw_delta),
                utility_gain=max(0.0, best_plan_explanation.chosen_candidate.utility_total),
                enables_immediate_build=clearly_supports_follow_up,
            ),
            metadata={"template": ExplanationTemplate.YEAR_OF_PLENTY_RESOURCES},
        )

    @staticmethod
    def _build_monopoly_resource_explanation(selected_resource: Resource, total_resource_count: int,
                                             self_gain_efficiency: float, leader_share: float) -> ActionExplanation:
        """Build the monopoly resource explanation."""
        reasons_for: list[Reason] = []
        if total_resource_count > 0:
            reasons_for.append(
                Reason(
                    ReasonType.SLOWS_LEADING_OPPONENT,
                    ReasonLabel.MONOPOLY_HIGHEST_DEMAND,
                    float(total_resource_count),
                ))
        else:
            reasons_for.append(Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.MONOPOLY_FLEXIBLE_PICK, 1.0))

        action = Action(ActionType.PLAY_DEV_CARD, DevelopmentCardType.MONOPOLY)
        candidate = CandidateExplanation(
            action=action,
            full_plan=[action],
            reasons_for=reasons_for,
            metadata={
                "template": ExplanationTemplate.MONOPOLY_RESOURCE,
                "selected_resource": selected_resource,
                "selected_resources": {
                    selected_resource: 1
                },
            },
        )
        return ActionExplanation(
            chosen_action=action,
            chosen_candidate=candidate,
            move_quality=monopoly_move_quality(total_resource_count, self_gain_efficiency, leader_share),
            metadata={"template": ExplanationTemplate.MONOPOLY_RESOURCE},
        )

    @staticmethod
    def _year_of_plenty_plan_target(
            player: Player,
            explanation: ActionExplanation) -> tuple[Action | None, Action | None, ResourceCount, bool]:
        """Handle year of plenty plan target."""
        if explanation.chosen_action.type == ActionType.END_TURN and explanation.chosen_candidate.next_plan:
            plan = explanation.chosen_candidate.next_plan
        elif explanation.chosen_candidate.full_plan:
            plan = explanation.chosen_candidate.full_plan
        else:
            plan = [explanation.chosen_action]

        simulated_resources = player.resources.copy()
        primary_action: Action | None = None
        already_had_next_step = False

        for action in plan:
            cost = calc_step_resources(action)
            if not any(cost.values()):
                continue

            if primary_action is None:
                primary_action = action

            shortfalls = {
                resource: max(0,
                              cost.get(resource, 0) - simulated_resources[resource])
                for resource in Resource
            }
            if sum(shortfalls.values()) > 0:
                return primary_action, action, shortfalls, already_had_next_step

            already_had_next_step = True
            for resource, amount in cost.items():
                simulated_resources[resource] -= amount

        if primary_action is not None:
            return primary_action, primary_action, {resource: 0 for resource in Resource}, already_had_next_step
        return None, None, {resource: 0 for resource in Resource}, False

    @staticmethod
    def _flexible_year_of_plenty_priority(player: Player) -> list[Resource]:
        """Handle flexible year of plenty priority."""
        sorted_resources = sorted(Resource, key=lambda resource: (player.resources[resource], resource.value))
        if len(sorted_resources) >= 2:
            return sorted_resources[:2]
        return sorted_resources
