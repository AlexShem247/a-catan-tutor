from dataclasses import dataclass
from enum import Enum, auto
from random import Random


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
        """Return how many resources this building yields."""
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

    INITIAL_COUNTS = {
        DevelopmentCardType.KNIGHT: 14,
        DevelopmentCardType.ROAD_BUILDING: 2,
        DevelopmentCardType.YEAR_OF_PLENTY: 2,
        DevelopmentCardType.MONOPOLY: 2,
        DevelopmentCardType.VICTORY_POINT: 5,
    }

    def __init__(self, rng: Random):
        self.rng = rng
        self._deck: list[DevelopmentCard] = []
        self._played = {ctype: 0 for ctype in self.INITIAL_COUNTS}

        for card_type, count in self.INITIAL_COUNTS.items():
            self._add_cards(card_type, count)

        self.rng.shuffle(self._deck)

    def _add_cards(self, card_type: DevelopmentCardType, count: int):
        """Add development cards of the given type to the deck."""
        for _ in range(count):
            self._deck.append(DevelopmentCard(card_type))

    def empty(self) -> bool:
        """Check whether the development deck is empty."""
        return len(self._deck) == 0

    def draw(self) -> DevelopmentCard:
        """Draw the top development card from the deck."""
        if self.empty():
            raise RuntimeError("Development deck is empty")

        return self._deck.pop()

    def size(self) -> int:
        """Return the number of cards remaining in the deck."""
        return len(self._deck)

    def cards(self) -> list[DevelopmentCard]:
        """Return a copy of the current development deck cards."""
        return list(self._deck)

    def played_counts(self) -> dict[DevelopmentCardType, int]:
        """Return how many development cards of each type were played."""
        return dict(self._played)

    def set_cards(self, cards: list[DevelopmentCard]) -> None:
        """Replace the current development deck cards."""
        self._deck = list(cards)

    def play(self, ctype: DevelopmentCardType):
        """Record that a development card of the given type was played."""
        if ctype == DevelopmentCardType.VICTORY_POINT:
            # VP is never played
            return

        self._played[ctype] += 1

    def get_probability(self, ctype: DevelopmentCardType,
                        private_cards: dict[DevelopmentCardType, int] | None = None) -> float:
        """Return the probability of drawing a card of the given type."""

        # Unknown = initial - publicly played
        unknown = max(0, self.INITIAL_COUNTS[ctype] - self._played[ctype])

        # Subtract any private cards of this type
        if private_cards is not None:
            unknown -= private_cards.get(ctype, 0)
            unknown = max(0, unknown)

        # Total unknown across all types
        total_unknown = sum(max(0, self.INITIAL_COUNTS[t] - self._played[t]) for t in DevelopmentCardType)

        if private_cards is not None:
            total_unknown -= sum(private_cards.values())
            total_unknown = max(0, total_unknown)

        if total_unknown == 0:
            return 0.0

        return unknown / total_unknown
