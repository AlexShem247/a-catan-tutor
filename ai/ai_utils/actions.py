from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class Phase(Enum):
    PRE_ROLL = auto()
    MAIN = auto()


class ActionType(Enum):
    ROLL = auto()
    BUILD = auto()
    TRADE_WITH_BANK = auto()
    TRADE_WITH_PLAYER = auto()
    BUY_DEV_CARD = auto()
    PLAY_DEV_CARD = auto()
    END_TURN = auto()


@dataclass
class Action:
    type: ActionType
    payload: Any = None
