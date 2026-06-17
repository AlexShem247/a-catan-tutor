from dataclasses import dataclass
from functools import wraps
from random import Random
from typing import Any

from ai.actions import Action, ActionType, Phase
from ai.AI import AI
from ai.RandomAI import RandomAI
from ai.rule_based_ai.development_card_policy import DevelopmentCardPolicy
from ai.rule_based_ai.discard_policy import DiscardPolicy
from ai.rule_based_ai.opening_policy import OpeningPolicy
from ai.rule_based_ai.robber_policy import RobberPolicy
from ai.rule_based_ai.trade_policy import TradePolicy
from ai.simulation.EtwEstimator import EtwEstimator, EtwTradeStateSnapshot
from ai.simulation.SimGame import make_sim_game_for_player
from ai.tutor.explanations import ActionExplanation, CandidateExplanation, Reason, ReasonLabel, ReasonType
from config.settings import AI_DIFFICULTY_STRATEGIC_MOVE_PROBABILITIES, load_effective_settings
from config.StrategyWeights import StrategyWeights
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex


def use_strategy_weights(method):

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.strategy_weights.applied():
            return method(self, *args, **kwargs)

    return wrapper


@dataclass(frozen=True)
class RuleBasedAIDecisionConfig:
    use_etw_planning: bool = True
    use_opponent_interference: bool = True
    use_time_discount: bool = True
    use_player_trading: bool = True
    use_development_cards: bool = True

    @classmethod
    def full_system(cls) -> "RuleBasedAIDecisionConfig":
        """Handle full system."""
        return cls()

    @classmethod
    def no_etw_planning(cls) -> "RuleBasedAIDecisionConfig":
        """Handle no etw planning."""
        return cls(use_etw_planning=False)

    @classmethod
    def single_step_etw_rollout(cls) -> "RuleBasedAIDecisionConfig":
        """Handle single step etw rollout."""
        return cls(use_etw_planning=False)

    @classmethod
    def no_opponent_interference(cls) -> "RuleBasedAIDecisionConfig":
        """Handle no opponent interference."""
        return cls(use_opponent_interference=False)

    @classmethod
    def no_time_discount(cls) -> "RuleBasedAIDecisionConfig":
        """Handle no time discount."""
        return cls(use_time_discount=False)

    @classmethod
    def no_player_trading(cls) -> "RuleBasedAIDecisionConfig":
        """Handle no player trading."""
        return cls(use_player_trading=False)

    @classmethod
    def no_development_cards(cls) -> "RuleBasedAIDecisionConfig":
        """Handle no development cards."""
        return cls(use_development_cards=False)


@dataclass(frozen=True)
class RuleBasedAIStateSnapshot:
    rng_state: Any
    trade_state: EtwTradeStateSnapshot


class RuleBasedAI(AI):

    def __init__(self, rng: Random, strategy_weights: StrategyWeights | None = None,
                 decision_config: RuleBasedAIDecisionConfig | None = None, use_difficulty_randomness: bool = False):
        super().__init__(rng)
        self.strategy_weights = strategy_weights or StrategyWeights()
        self.decision_config = decision_config or RuleBasedAIDecisionConfig()
        self.use_difficulty_randomness = use_difficulty_randomness
        self.etw_estimator = EtwEstimator()
        self.random_ai = RandomAI(rng)
        self.opening_policy = OpeningPolicy(
            rng=self.rng,
            random_ai=self.random_ai,
            decision_config=self.decision_config,
            use_strategic_move=self._use_strategic_move,
        )
        self.trade_policy = TradePolicy(
            random_ai=self.random_ai,
            etw_estimator=self.etw_estimator,
            decision_config=self.decision_config,
            use_strategic_move=self._use_strategic_move,
            planner_kwargs=self._planner_kwargs,
            etw_kwargs=self._etw_kwargs,
            trade_risk_kwargs=self._trade_risk_kwargs,
        )
        self.robber_policy = RobberPolicy(
            rng=self.rng,
            random_ai=self.random_ai,
            etw_estimator=self.etw_estimator,
            decision_config=self.decision_config,
            use_strategic_move=self._use_strategic_move,
            planner_kwargs=self._planner_kwargs,
        )
        self.discard_policy = DiscardPolicy(
            random_ai=self.random_ai,
            etw_estimator=self.etw_estimator,
            use_strategic_move=self._use_strategic_move,
            planner_kwargs=self._planner_kwargs,
        )
        self.dev_card_policy = DevelopmentCardPolicy(
            rng=self.rng,
            random_ai=self.random_ai,
            etw_estimator=self.etw_estimator,
            decision_config=self.decision_config,
            use_strategic_move=self._use_strategic_move,
            planner_kwargs=self._planner_kwargs,
            etw_kwargs=self._etw_kwargs,
        )

    def new_turn(self):
        """Reset per-turn AI state."""
        self.etw_estimator.new_turn()

    def snapshot_state(self) -> RuleBasedAIStateSnapshot:
        """Capture the current AI state snapshot."""
        return RuleBasedAIStateSnapshot(
            rng_state=self.rng.getstate(),
            trade_state=self.etw_estimator.snapshot_trade_state(),
        )

    def restore_state(self, snapshot: RuleBasedAIStateSnapshot) -> None:
        """Restore the AI state from a snapshot."""
        self.rng.setstate(snapshot.rng_state)
        self.etw_estimator.restore_trade_state(snapshot.trade_state)

    def _use_strategic_move(self) -> bool:
        """Handle use strategic move."""
        if not self.use_difficulty_randomness:
            return True
        settings = load_effective_settings()
        difficulty = str(settings.get("ai_difficulty", "medium")).lower()
        strategic_move_probability = AI_DIFFICULTY_STRATEGIC_MOVE_PROBABILITIES.get(
            difficulty,
            AI_DIFFICULTY_STRATEGIC_MOVE_PROBABILITIES["medium"],
        )
        return self.rng.random() < strategic_move_probability

    def _build_random_action_explanation(self, action: Action, phase: Phase) -> ActionExplanation:
        """Build the random action explanation."""
        candidate = CandidateExplanation(
            action=action,
            full_plan=[action],
            reasons_for=[Reason(
                ReasonType.HEURISTIC_CHOICE,
                ReasonLabel.QUICK_GENERIC,
                0.0,
            )],
            metadata={
                "phase": phase.name.lower(),
                "selection_mode": "random"
            },
        )
        return ActionExplanation(
            chosen_action=action,
            chosen_candidate=candidate,
            alternatives=[],
            move_quality=0.0,
            assumptions=[],
            metadata={
                "phase": phase.name.lower(),
                "selection_mode": "random"
            },
        )

    def _planner_kwargs(self, ignore_opponents: bool = False) -> dict[str, object]:
        """Handle planner kwargs."""
        return {
            "include_player_trades": self.decision_config.use_player_trading,
            "ignore_opponents": ignore_opponents or not self.decision_config.use_opponent_interference,
            "use_time_discount": self.decision_config.use_time_discount,
            "allow_development_cards": self.decision_config.use_development_cards,
            "use_planning": self.decision_config.use_etw_planning,
        }

    def _etw_kwargs(self, include_player_trades: bool = True) -> dict[str, object]:
        """Handle etw kwargs."""
        return {
            "include_player_trades": include_player_trades,
            "allow_development_cards": self.decision_config.use_development_cards,
            "use_planning": self.decision_config.use_etw_planning,
        }

    def _trade_risk_kwargs(self) -> dict[str, float]:
        """Handle trade risk kwargs."""
        if self.decision_config.use_opponent_interference:
            return {}
        return {
            "lambda_leader": float("inf"),
            "lambda_base": float("inf"),
            "leader_penalty": 0.0,
        }

    @use_strategy_weights
    def select_initial_settlement_location(self, player: Player, game: Game,
                                           available_vertices: list[Vertex]) -> Vertex | None:
        """Select the initial settlement location."""
        return self.opening_policy.select_initial_settlement_location(player, game, available_vertices)

    @use_strategy_weights
    def select_initial_road_location(self, player: Player, game: Game, available_edges: list[Edge]) -> Edge | None:
        """Select the initial road location."""
        return self.opening_policy.select_initial_road_location(player, game, available_edges)

    @use_strategy_weights
    def select_initial_settlement_location_with_explanation(
            self, player: Player, game: Game,
            available_vertices: list[Vertex]) -> tuple[Vertex | None, ActionExplanation | None]:
        """Select the initial settlement location with explanation."""
        return self.opening_policy.select_initial_settlement_location_with_explanation(player, game, available_vertices)

    @use_strategy_weights
    def explain_initial_settlement_choice(self, player: Player, game: Game, available_vertices: list[Vertex],
                                          chosen_vertex: Vertex) -> ActionExplanation:
        """Handle explain initial settlement choice."""
        return self.opening_policy.explain_initial_settlement_choice(player, game, available_vertices, chosen_vertex)

    @use_strategy_weights
    def score_initial_settlement_choice(self, player: Player, game: Game, available_vertices: list[Vertex],
                                        chosen_vertex: Vertex) -> float:
        """Score the initial settlement choice."""
        return self.opening_policy.score_initial_settlement_choice(player, game, available_vertices, chosen_vertex)

    @use_strategy_weights
    def select_initial_road_location_with_explanation(
            self, player: Player, game: Game,
            available_edges: list[Edge]) -> tuple[Edge | None, ActionExplanation | None]:
        """Select the initial road location with explanation."""
        return self.opening_policy.select_initial_road_location_with_explanation(player, game, available_edges)

    @use_strategy_weights
    def explain_initial_road_choice(self, player: Player, game: Game, available_edges: list[Edge],
                                    chosen_edge: Edge) -> ActionExplanation:
        """Handle explain initial road choice."""
        return self.opening_policy.explain_initial_road_choice(player, game, available_edges, chosen_edge)

    @use_strategy_weights
    def score_initial_road_choice(self, player: Player, game: Game, available_edges: list[Edge],
                                  chosen_edge: Edge) -> float:
        """Score the initial road choice."""
        return self.opening_policy.score_initial_road_choice(player, game, available_edges, chosen_edge)

    @staticmethod
    def vertex_utility(vertex: Vertex, player: Player, game: Game, available_vertices: list[Vertex],
                       first_settlement: bool = True, use_opponent_interference: bool = True) -> float:
        """Handle vertex utility."""
        return OpeningPolicy.vertex_utility(vertex, player, game, available_vertices, first_settlement,
                                            use_opponent_interference)

    @use_strategy_weights
    def choose_trade_partner(
        self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount,
        available_players: list[tuple[Player, ResourceCount | None]]
    ) -> tuple[Player, ResourceCount | None] | None:
        """Choose the preferred trade partner from the available offers."""
        return self.trade_policy.choose_trade_partner(player, game, selling, buying, available_players)

    @use_strategy_weights
    def choose_trade_partner_with_explanation(
        self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount,
        available_players: list[tuple[Player, ResourceCount | None]]
    ) -> tuple[tuple[Player, ResourceCount | None] | None, ActionExplanation | None]:
        """Choose the trade partner with explanation."""
        return self.trade_policy.choose_trade_partner_with_explanation(player, game, selling, buying, available_players)

    @use_strategy_weights
    def explain_trade_partner_choice(self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount,
                                     available_players: list[tuple[Player, ResourceCount | None]],
                                     chosen_player: Player, counter: ResourceCount | None) -> ActionExplanation:
        """Handle explain trade partner choice."""
        return self.trade_policy.explain_trade_partner_choice(player, game, selling, buying, available_players,
                                                              chosen_player, counter)

    @use_strategy_weights
    def select_robber_target(self, player: Player, game: Game,
                             valid_hexes: list[HexTile]) -> tuple[HexTile, Player | None]:
        """Select the robber target hex and victim."""
        return self.robber_policy.select_robber_target(player, game, valid_hexes)

    @use_strategy_weights
    def select_robber_target_with_explanation(
            self, player: Player, game: Game,
            valid_hexes: list[HexTile]) -> tuple[HexTile, Player | None, ActionExplanation | None]:
        """Select the robber target with explanation."""
        return self.robber_policy.select_robber_target_with_explanation(player, game, valid_hexes)

    @use_strategy_weights
    def explain_robber_choice(self, player: Player, game: Game, _valid_hexes: list[HexTile], chosen_hex: HexTile,
                              chosen_player: Player | None) -> ActionExplanation:
        """Handle explain robber choice."""
        return self.robber_policy.explain_robber_choice(player, game, _valid_hexes, chosen_hex, chosen_player)

    @use_strategy_weights
    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        """Select which resources to discard."""
        return self.discard_policy.select_discard_resources(player, game, num_resources)

    @use_strategy_weights
    def select_discard_resources_with_explanation(
            self, player: Player, game: Game, num_resources: int) -> tuple[ResourceCount, ActionExplanation | None]:
        """Select the discard resources with explanation."""
        return self.discard_policy.select_discard_resources_with_explanation(player, game, num_resources)

    @use_strategy_weights
    def explain_discard_choice(self, player: Player, game: Game, discard: ResourceCount) -> ActionExplanation:
        """Handle explain discard choice."""
        return self.discard_policy.explain_discard_choice(player, game, discard)

    @use_strategy_weights
    def select_year_of_plenty_resources(self, player: Player, game: Game) -> ResourceCount:
        """Select resources for the Year of Plenty card."""
        return self.dev_card_policy.select_year_of_plenty_resources(player, game)

    @use_strategy_weights
    def select_year_of_plenty_resources_with_explanation(
            self, player: Player, game: Game) -> tuple[ResourceCount, ActionExplanation | None]:
        """Select the year of plenty resources with explanation."""
        return self.dev_card_policy.select_year_of_plenty_resources_with_explanation(player, game)

    @use_strategy_weights
    def explain_year_of_plenty_choice(self, player: Player, game: Game, selected: ResourceCount) -> ActionExplanation:
        """Handle explain year of plenty choice."""
        return self.dev_card_policy.explain_year_of_plenty_choice(player, game, selected)

    @use_strategy_weights
    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        """Select the resource type for the Monopoly card."""
        return self.dev_card_policy.select_monopoly_resource(player, game)

    @use_strategy_weights
    def select_monopoly_resource_with_explanation(self, player: Player,
                                                  game: Game) -> tuple[Resource, ActionExplanation | None]:
        """Select the monopoly resource with explanation."""
        return self.dev_card_policy.select_monopoly_resource_with_explanation(player, game)

    @use_strategy_weights
    def explain_monopoly_choice(self, player: Player, game: Game, chosen: Resource) -> ActionExplanation:
        """Handle explain monopoly choice."""
        return self.dev_card_policy.explain_monopoly_choice(player, game, chosen)

    @use_strategy_weights
    def respond_to_trade(self, player: Player, game: Game, opponent: Player, selling: ResourceCount,
                         buying: ResourceCount) -> tuple[bool, ResourceCount | None]:
        """Handle respond to trade."""
        return self.trade_policy.respond_to_trade(player, game, opponent, selling, buying)

    @use_strategy_weights
    def respond_to_trade_with_explanation(
            self, player: Player, game: Game, opponent: Player, selling: ResourceCount,
            buying: ResourceCount) -> tuple[bool, ResourceCount | None, ActionExplanation | None]:
        """Handle respond to trade with explanation."""
        return self.trade_policy.respond_to_trade_with_explanation(player, game, opponent, selling, buying)

    @use_strategy_weights
    def explain_trade_response_choice(self, player: Player, game: Game, opponent: Player, selling: ResourceCount,
                                      buying: ResourceCount, accepted: bool,
                                      counter: ResourceCount | None) -> ActionExplanation:
        """Handle explain trade response choice."""
        return self.trade_policy.explain_trade_response_choice(player, game, opponent, selling, buying, accepted,
                                                               counter)

    @use_strategy_weights
    def road_building_placement(self, player: Player, game: Game, available_edges: list[Edge]) -> Edge | None:
        """Handle road building placement."""
        return self.opening_policy.road_building_placement(player, game, available_edges)

    @use_strategy_weights
    def next_action_with_explanation(self, player: Player, game: Game, phase: Phase,
                                     dev_played: bool) -> tuple[Action, ActionExplanation]:
        """Return the next action together with its explanation."""
        if not self._use_strategic_move():
            action = self.random_ai.next_action(player, game, phase, dev_played)
            return action, self._build_random_action_explanation(action, phase)

        if phase == Phase.PRE_ROLL:
            dev_action = self.dev_card_policy.select_pre_roll_action_with_explanation(player, game, dev_played)
            if dev_action is not None:
                return dev_action

            roll_action = Action(ActionType.ROLL)
            explanation = ActionExplanation(
                chosen_action=roll_action, chosen_candidate=CandidateExplanation(
                    action=roll_action, full_plan=[roll_action], reasons_for=[
                        Reason(type=ReasonType.HEURISTIC_CHOICE, label=ReasonLabel.PRE_ROLL_NO_DEV_PLAY, value=0.0)
                    ]), alternatives=[], move_quality=0.0, assumptions=[], metadata={"phase": "pre_roll"})
            return roll_action, explanation

        sim_game = make_sim_game_for_player(game, player)

        explanation = self.etw_estimator.calculate_best_game_action_with_explanation(
            sim_game=sim_game, player_number=player.player_number, dev_played=dev_played, **self._planner_kwargs())

        best_action = explanation.chosen_action

        if best_action.type == ActionType.TRADE_WITH_PLAYER:
            self.etw_estimator.record_trade_proposal(player.resources)
        else:
            self.etw_estimator.clear_trade_proposal()

        return best_action, explanation

    @use_strategy_weights
    def explain_pre_roll_dev_choice(self, player: Player, game: Game,
                                    card_type: DevelopmentCardType) -> ActionExplanation:
        """Handle explain pre roll dev choice."""
        return self.dev_card_policy.explain_pre_roll_dev_choice(player, game, card_type)

    @use_strategy_weights
    def explain_action(self, player: Player, game: Game, phase: Phase, dev_played: bool,
                       action: Action) -> ActionExplanation:
        """Handle explain action."""
        if phase == Phase.PRE_ROLL:
            candidate = CandidateExplanation(
                action=action,
                full_plan=[action],
                reasons_for=[],
            )
            return ActionExplanation(
                chosen_action=action,
                chosen_candidate=candidate,
                alternatives=[],
                move_quality=0.0,
                metadata={"phase": "pre_roll"},
            )

        sim_game = make_sim_game_for_player(game, player)
        return self.etw_estimator.explain_action(
            sim_game=sim_game,
            player_number=player.player_number,
            dev_played=dev_played,
            action=action,
            **self._planner_kwargs(),
        )

    @use_strategy_weights
    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        """Return the next action for the current game phase."""
        action, _ = self.next_action_with_explanation(player, game, phase, dev_played)
        return action
