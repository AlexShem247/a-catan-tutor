from ai.BasicAI import BasicAI
from ai.RandomAI import RandomAI
from ai.RuleBasedAI import RuleBasedAI
from game.Game import PlayerConfig
from game.Player import PlayerNumber

STANDARD_SINGLEPLAYER: PlayerConfig = {
    PlayerNumber.P1: None,
    PlayerNumber.P2: RuleBasedAI,
    PlayerNumber.P3: RandomAI,
    PlayerNumber.P4: RandomAI,
}

RULE_BASED_VS_RANDOM: PlayerConfig = {
    PlayerNumber.P1: RuleBasedAI,
    PlayerNumber.P2: RandomAI,
    PlayerNumber.P3: RandomAI,
    PlayerNumber.P4: RandomAI,
}

RULE_BASED_VS_BASIC: PlayerConfig = {
    PlayerNumber.P1: RuleBasedAI,
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
