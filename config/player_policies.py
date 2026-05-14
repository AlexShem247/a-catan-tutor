from dataclasses import dataclass, field
from typing import Any, Optional

from ai.BasicAI import BasicAI
from ai.RandomAI import RandomAI
from ai.rule_based_ai.RuleBasedAI import RuleBasedAI, RuleBasedAIDecisionConfig
from config.StrategyWeights import EVO_STRATEGY_WEIGHTS, ORIGINAL_STRATEGY_WEIGHTS, StrategyWeights
from game.Game import PlayerConfig
from game.Player import PlayerNumber


@dataclass(frozen=True)
class PolicyFactory:
    ai_cls: type
    name: Optional[str] = None
    kwargs: dict[str, Any] = field(default_factory=dict)

    def __call__(self, rng):
        policy = self.ai_cls(rng, **self.kwargs)
        if self.name is not None:
            policy.policy_name = self.name
        return policy


def make_rule_based_policy(
        name: str,
        weights: StrategyWeights,
        decision_config: Optional[RuleBasedAIDecisionConfig] = None) -> PolicyFactory:
    return PolicyFactory(
        ai_cls=RuleBasedAI,
        name=name,
        kwargs={
            "strategy_weights": weights,
            "decision_config": decision_config,
            "use_difficulty_randomness": True,
        },
    )


RULE_BASED_AI_EVO = make_rule_based_policy("RuleBasedAI Evo", EVO_STRATEGY_WEIGHTS)
RULE_BASED_AI_ORIGINAL = make_rule_based_policy("RuleBasedAI Original", ORIGINAL_STRATEGY_WEIGHTS)

STANDARD_SINGLEPLAYER: PlayerConfig = {
    PlayerNumber.P1: None,
    PlayerNumber.P2: RULE_BASED_AI_ORIGINAL,
    PlayerNumber.P3: RULE_BASED_AI_ORIGINAL,
    PlayerNumber.P4: RULE_BASED_AI_ORIGINAL,
}

EVO_VS_RULE_BASED: PlayerConfig = {
    PlayerNumber.P1: RULE_BASED_AI_EVO,
    PlayerNumber.P2: RULE_BASED_AI_ORIGINAL,
    PlayerNumber.P3: RULE_BASED_AI_ORIGINAL,
    PlayerNumber.P4: RULE_BASED_AI_ORIGINAL,
}

RULE_BASED_VS_RANDOM: PlayerConfig = {
    PlayerNumber.P1: RULE_BASED_AI_EVO,
    PlayerNumber.P2: RandomAI,
    PlayerNumber.P3: RandomAI,
    PlayerNumber.P4: RandomAI,
}

RULE_BASED_VS_BASIC: PlayerConfig = {
    PlayerNumber.P1: RULE_BASED_AI_EVO,
    PlayerNumber.P2: BasicAI,
    PlayerNumber.P3: BasicAI,
    PlayerNumber.P4: BasicAI,
}

BASIC_VS_RANDOM: PlayerConfig = {
    PlayerNumber.P1: BasicAI,
    PlayerNumber.P2: RandomAI,
    PlayerNumber.P3: RandomAI,
    PlayerNumber.P4: RandomAI,
}

ALL_RANDOM: PlayerConfig = {
    PlayerNumber.P1: RandomAI,
    PlayerNumber.P2: RandomAI,
    PlayerNumber.P3: RandomAI,
    PlayerNumber.P4: RandomAI,
}

POLICY_EVALUATION_EXPERIMENT: PlayerConfig = {
    PlayerNumber.P1: RULE_BASED_AI_EVO,
    PlayerNumber.P2: RULE_BASED_AI_ORIGINAL,
    PlayerNumber.P3: RULE_BASED_AI_ORIGINAL,
    PlayerNumber.P4: RULE_BASED_AI_ORIGINAL,
}
