from collections import Counter
from typing import List, TYPE_CHECKING

from game.Edge import Edge
from game.PlayerAssets import DevelopmentCardType
from game.Resources import ResourceCount
from game.Vertex import Vertex

if TYPE_CHECKING:
    from game.Player import Player


class SimPlayerState:
    """Lightweight player model for ETW forward simulation."""

    def __init__(self, player: "Player"):
        """Create a simulation state from a real Player."""

        # Resources (copy)
        self.resources: ResourceCount = dict(player.resources)

        # Board assets (copy lists, not objects)
        self.settlements: List[Vertex] = list(player.settlements)
        self.cities: List[Vertex] = list(player.cities)
        self.roads: List[Edge] = list(player.roads)

        # Development cards
        self.dev_cards: Counter[DevelopmentCardType] = Counter(
            c.card_type for c in player.development_cards
        )

        # Achievements
        self.longest_road_length: int = player.longest_road_length
        self.has_longest_road: bool = player.has_longest_road

        self.army_size: int = player.army_size
        self.has_largest_army: bool = player.has_largest_army

    def copy(self) -> "SimPlayerState":
        """Create a fast deep copy of this simulation state."""

        new = SimPlayerState.__new__(SimPlayerState)

        new.resources = dict(self.resources)

        new.settlements = list(self.settlements)
        new.cities = list(self.cities)
        new.roads = list(self.roads)

        new.dev_cards = self.dev_cards.copy()

        new.longest_road_length = self.longest_road_length
        new.has_longest_road = self.has_longest_road

        new.army_size = self.army_size
        new.has_largest_army = self.has_largest_army

        return new

    def victory_points(self) -> int:
        """Return total victory points (including hidden VP cards)."""

        points = 0

        # Buildings
        points += len(self.settlements)
        points += 2 * len(self.cities)

        # Achievements
        if self.has_longest_road:
            points += 2

        if self.has_largest_army:
            points += 2

        # Hidden VP cards
        points += self.dev_cards.get(DevelopmentCardType.VICTORY_POINT, 0)

        return points

    def can_afford(self, cost: ResourceCount) -> bool:
        """Return True if the player can afford the given cost."""
        return all(self.resources.get(r, 0) >= c for r, c in cost.items())

    def pay(self, cost: ResourceCount) -> None:
        """Remove resources (no bank interaction)."""
        for r, c in cost.items():
            self.resources[r] -= c

    def add_resources(self, resources: ResourceCount) -> None:
        """Add resources (used for expected income)."""
        for r, c in resources.items():
            self.resources[r] += c

    def build_settlement(self, vertex: Vertex) -> None:
        """Add a settlement (no legality checking)."""
        self.settlements.append(vertex)

    def build_city(self, vertex: Vertex) -> None:
        """Upgrade settlement to city."""
        if vertex in self.settlements:
            self.settlements.remove(vertex)

        self.cities.append(vertex)

    def build_road(self, edge: Edge) -> None:
        """Add a road."""
        self.roads.append(edge)

    def add_knight(self) -> None:
        """Simulate playing a knight."""
        self.dev_cards[DevelopmentCardType.KNIGHT] += 1
        self.army_size += 1
        if self.army_size >= 3:
            self.has_largest_army = True

    def add_vp_card(self) -> None:
        """Simulate gaining a VP development card."""
        self.dev_cards[DevelopmentCardType.VICTORY_POINT] += 1
