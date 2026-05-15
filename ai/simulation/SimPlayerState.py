from collections import Counter
from functools import lru_cache
from typing import TYPE_CHECKING, Dict, List, Tuple

from game.Board import Board
from game.Edge import Edge
from game.PlayerAssets import DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex

if TYPE_CHECKING:
    from game.Player import Player


@lru_cache(maxsize=128)
def dice_probability_cached(number: int) -> float:
    """Return the probability of rolling the given dice number on two six-sided dice."""
    dice_probs = {
        2: 1 / 36,
        3: 2 / 36,
        4: 3 / 36,
        5: 4 / 36,
        6: 5 / 36,
        8: 5 / 36,
        9: 4 / 36,
        10: 3 / 36,
        11: 2 / 36,
        12: 1 / 36
    }
    return dice_probs.get(number, 0)


def dice_probability(number: int) -> float:
    """Wrapper for cached dice probability."""
    return dice_probability_cached(number)


class SimPlayerState:
    """Lightweight player model for ETW forward simulation with caching."""

    def __init__(self, player: "Player", opponent: bool = False):
        """Create a simulation state from a real Player."""
        self.player_number = player.player_number

        # Resources (copy)
        self.resources: ResourceCount = dict(player.resources)

        # Board assets (copy lists, not objects)
        self.settlements: List[Vertex] = list(player.settlements)
        self.cities: List[Vertex] = list(player.cities)
        self.roads: List[Edge] = list(player.roads)

        # Development cards
        if opponent:
            # We do not know development cards
            self.dev_cards: Counter[DevelopmentCardType] = Counter()
        else:
            self.dev_cards: Counter[DevelopmentCardType] = Counter(c.card_type for c in player.development_cards)

        # Achievements
        self.longest_road_length: int = player.longest_road_length
        self.has_longest_road: bool = player.has_longest_road

        self.army_size: int = player.army_size
        self.has_largest_army: bool = player.has_largest_army
        self.vp_ev_bonus: float = 0.0

        # Caches for performance optimization
        self.etw_cache: Dict[Tuple, float] = {}
        self.etb_cache: Dict[Tuple, float] = {}
        self.candidate_cache: Dict[Tuple, List] = {}
        self._production_cache: Dict[Resource, float] = {}

    def copy(self) -> "SimPlayerState":
        """Return a copy of this simulation state."""
        new = SimPlayerState.__new__(SimPlayerState)
        new.player_number = self.player_number

        new.resources = dict(self.resources)

        new.settlements = list(self.settlements)
        new.cities = list(self.cities)
        new.roads = list(self.roads)

        new.dev_cards = self.dev_cards.copy()

        new.longest_road_length = self.longest_road_length
        new.has_longest_road = self.has_longest_road

        new.army_size = self.army_size
        new.has_largest_army = self.has_largest_army
        new.vp_ev_bonus = self.vp_ev_bonus

        # Create fresh caches for the copy
        new.etw_cache = {}
        new.etb_cache = {}
        new.candidate_cache = {}
        new._production_cache = dict(self._production_cache)

        return new

    def victory_points(self) -> float:
        """Handle victory points."""
        points = 0.0
        points += len(self.settlements)
        points += 2 * len(self.cities)

        if self.has_longest_road:
            points += 2
        if self.has_largest_army:
            points += 2

        points += self.dev_cards.get(DevelopmentCardType.VICTORY_POINT, 0)

        # EV from dev-card purchases
        points += self.vp_ev_bonus

        return points

    def can_afford(self, cost: ResourceCount) -> bool:
        """Check whether the afford."""
        return all(self.resources.get(r, 0) >= c for r, c in cost.items())

    def pay(self, cost: ResourceCount) -> None:
        """Handle pay."""
        for r, c in cost.items():
            self.resources[r] -= c

    def add_resources(self, resources: ResourceCount) -> None:
        """Handle add resources."""
        for r, c in resources.items():
            self.resources[r] = self.resources.get(r, 0) + c

    def remove_resources(self, resources: ResourceCount) -> None:
        """Handle remove resources."""
        for r, c in resources.items():
            self.resources[r] = max(0, self.resources.get(r, 0) - c)

    def build_settlement(self, vertex: Vertex) -> None:
        """Build the settlement."""
        self.settlements.append(vertex)
        # Clear production cache as settlements affect production
        self._production_cache.clear()

    def build_city(self, vertex: Vertex) -> None:
        """Build the city."""
        if vertex in self.settlements:
            self.settlements.remove(vertex)

        self.cities.append(vertex)
        # Clear production cache as cities affect production
        self._production_cache.clear()

    def build_road(self, edge: Edge, opponent_road_length: List[int]) -> None:
        """Build the road."""
        self.roads.append(edge)
        self.longest_road_length = Board.calculate_longest_road_length(self.roads)

        opp_best = max(opponent_road_length, default=0)
        if self.longest_road_length >= 5 and self.longest_road_length > opp_best:
            self.has_longest_road = True

    def add_knight(self, opponent_army_size: List[int]) -> None:
        """Handle add knight."""
        self.army_size += 1
        opp_best = max(opponent_army_size, default=0)
        if self.army_size >= 3 and self.army_size > opp_best:
            self.has_largest_army = True

    def remove_card(self, ctype: DevelopmentCardType) -> None:
        """Handle remove card."""
        self.dev_cards[ctype] = max(0, self.dev_cards[ctype] - 1)

    def get_production_rate(self, resource: Resource) -> float:
        """Return the production rate."""
        if resource not in self._production_cache:
            fr = 0.0
            for v in self.settlements:
                for h in v.hexes:
                    if h.resource == resource:
                        fr += dice_probability(h.production_number)

            for v in self.cities:
                for h in v.hexes:
                    if h.resource == resource:
                        fr += dice_probability(h.production_number) * 2

            self._production_cache[resource] = fr

        return self._production_cache[resource]
