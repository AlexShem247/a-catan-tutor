from dataclasses import dataclass
from enum import Enum, auto
from numbers import Number
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
    RETURN_HOME = auto()


@dataclass
class Action:
    type: ActionType
    payload: Any = None


def actions_equivalent(left: Action | None, right: Action | None) -> bool:
    """Return whether two actions represent the same move."""
    if left is right:
        return True
    if left is None or right is None:
        return False
    return left.type == right.type and _normalise_action_value(left.payload) == _normalise_action_value(right.payload)


def _normalise_action_value(value: Any) -> Any:
    """Normalise payload values so equivalent moves compare equal."""
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            if item is None:
                continue
            if isinstance(item, Number) and item == 0:
                continue
            items.append((_normalise_action_value(key), _normalise_action_value(item)))
        return tuple(sorted(items, key=repr))
    if isinstance(value, (list, tuple)):
        return tuple(_normalise_action_value(item) for item in value)
    pos = getattr(value, "pos", None)
    if pos is not None:
        return ("pos", _normalise_action_value(pos))
    player_number = getattr(value, "player_number", None)
    if player_number is not None:
        return ("player", player_number)
    return value
