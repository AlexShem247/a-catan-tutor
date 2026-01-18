from ai.BasicAI import BasicAI
from ai.RandomAI import RandomAI
from game.Game import PlayerConfig
from game.Player import PlayerNumber

STANDARD_SINGLEPLAYER: PlayerConfig = {
    PlayerNumber.P1: None,
    PlayerNumber.P2: RandomAI,
    PlayerNumber.P3: RandomAI,
    PlayerNumber.P4: RandomAI,
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
