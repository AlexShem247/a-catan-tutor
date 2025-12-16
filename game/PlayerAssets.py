import random
from dataclasses import dataclass
from enum import Enum, auto


class Buildable(Enum):
    ROAD = ("road", 15)
    SETTLEMENT = ("settlement", 5)
    CITY = ("city", 4)
    DEVELOPMENT_CARD = ("development card", 25)

    def __init__(self, label: str, max_on_board: int):
        self.label = label
        self.max_on_board = max_on_board


class Building(Enum):
    SETTLEMENT = Buildable.SETTLEMENT
    CITY = Buildable.CITY

    def get_resource_yield(self) -> int:
        """Return how many resources this building produces per turn."""
        if self == Building.CITY:
            return 2

        return 1


class DevelopmentCardType(Enum):
    KNIGHT = auto()
    ROAD_BUILDING = auto()
    YEAR_OF_PLENTY = auto()
    MONOPOLY = auto()
    VICTORY_POINT = auto()


@dataclass
class DevelopmentCard:
    card_type: DevelopmentCardType
    playable: bool = False  # False if bought this turn


class DevelopmentDeck:
    def __init__(self):
        self._deck: list[DevelopmentCard] = []
        # self._add_cards(DevelopmentCardType.KNIGHT, 14)
        # self._add_cards(DevelopmentCardType.ROAD_BUILDING, 2)
        # self._add_cards(DevelopmentCardType.YEAR_OF_PLENTY, 2)
        # self._add_cards(DevelopmentCardType.MONOPOLY, 2)
        self._add_cards(DevelopmentCardType.VICTORY_POINT, 5)
        random.shuffle(self._deck)

    def _add_cards(self, card_type: DevelopmentCardType, count: int):
        for _ in range(count):
            self._deck.append(DevelopmentCard(card_type))

    def empty(self) -> bool:
        """Checks to see if deck is empty"""
        return len(self._deck) == 0

    def draw(self) -> DevelopmentCard:
        """Draws a card assuming deck is not empty"""
        if self.empty():
            raise RuntimeError("Development deck is empty")
        return self._deck.pop()
