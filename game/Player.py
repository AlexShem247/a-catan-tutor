from __future__ import annotations

from enum import Enum
from random import Random
from typing import TYPE_CHECKING

from game.Edge import Edge
from game.PlayerAssets import DevelopmentCard, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Port, Vertex

if TYPE_CHECKING:
    from ai.AI import AI


class PlayerNumber(Enum):
    P1 = 0
    P2 = 1
    P3 = 2
    P4 = 3


class Player:

    def __init__(self, is_human: bool, player_number: PlayerNumber, bank_resources: ResourceCount, rng: Random,
                 name: str | None = None, policy: AI | None = None):
        self.is_human = is_human
        self.name = player_number.name if name is None else name
        self.player_number = player_number
        self.bank_resources = bank_resources
        self.rng = rng
        self.policy = policy

        # Resources (0 for each)
        self.resources: ResourceCount = {resource: 0 for resource in Resource}

        # Assets on the board
        self.settlements: list[Vertex] = []
        self.cities: list[Vertex] = []
        self.roads: list[Edge] = []

        # Game metrics
        self.longest_road_length: int = 0
        self.has_longest_road: bool = False
        self.army_size: int = 0
        self.has_largest_army: bool = False
        self.best_opponents_victory_point: int = 0

        self.development_cards: list[DevelopmentCard] = []

    def calc_victory_points(self) -> tuple[int, int]:
        """Calculate the visible and total victory points for the player."""
        visible_points = 0

        # Buildings
        visible_points += len(self.settlements) * 1  # 1 point per settlement
        visible_points += len(self.cities) * 2  # 2 points per city

        # Special achievements
        if self.has_longest_road:
            visible_points += 2
        if self.has_largest_army:
            visible_points += 2

        # Hidden Victory Point development cards
        hidden_vp_cards = sum(1 for card in self.development_cards
                              if card.card_type == DevelopmentCardType.VICTORY_POINT)

        total_points = visible_points + hidden_vp_cards
        return visible_points, total_points

    def __repr__(self):
        return self.name

    def add_resource(self, resource: Resource, amount: int) -> None:
        """Add resources of the given type to the player."""
        move_amount = min(self.bank_resources[resource], amount)

        self.bank_resources[resource] -= move_amount
        self.resources[resource] += move_amount

    def add_resources(self, resources: ResourceCount) -> None:
        """Add a batch of resources to the player."""
        for resource, amount in resources.items():
            self.add_resource(resource, amount)

    def remove_resource(self, resource: Resource, amount: int) -> None:
        """Remove resources of the given type from the player."""
        move_amount = min(self.resources[resource], amount)

        self.bank_resources[resource] += move_amount
        self.resources[resource] -= move_amount

    def remove_resources(self, resources: ResourceCount) -> None:
        """Remove a batch of resources from the player."""
        for resource, amount in resources.items():
            self.remove_resource(resource, amount)

    def can_afford(self, resources: ResourceCount) -> bool:
        """Check whether the player can afford the given cost."""
        return all(self.resources.get(res, 0) >= amt for res, amt in resources.items())

    def has_resources(self) -> bool:
        """Check whether the player has any resources."""
        return any(amount > 0 for amount in self.resources.values())

    def add_settlement(self, vertex) -> None:
        """Record a new settlement for the player."""
        self.settlements.append(vertex)

    def add_city(self, vertex) -> None:
        """Upgrade one of the player settlements to a city."""
        if vertex in self.settlements:
            self.settlements.remove(vertex)
        self.cities.append(vertex)

    def add_road(self, edge) -> None:
        """Record a new road for the player."""
        self.roads.append(edge)

    def get_ports(self) -> list[Port]:
        """Return the board ports and their attached vertices."""
        return [v.port for v in self.settlements + self.cities if v.port is not None]

    def calculate_discard_count(self) -> int:
        """Calculate how many resources the player must discard."""
        resource_count = sum(self.resources.values())
        if resource_count < 7:
            return 0
        return resource_count // 2

    def random_resource(self) -> ResourceCount:
        """Return a random resource from the player inventory."""
        # Build a flat list where each card appears once per count
        pool = [resource for resource, count in self.resources.items() for _ in range(count)]

        if not pool:
            return {}

        resource_to_give = self.rng.choice(pool)
        return {resource_to_give: 1}
