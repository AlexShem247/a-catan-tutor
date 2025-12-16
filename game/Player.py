from enum import Enum
from typing import List, Optional, Tuple

from game.Edge import Edge
from game.PlayerAssets import DevelopmentCard, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex, Port


class PlayerNumber(Enum):
    P1 = 0
    P2 = 1
    P3 = 2
    P4 = 3


class Player:
    def __init__(self, is_human: bool, playerNumber: PlayerNumber, bank_resources: ResourceCount,
                 name: Optional[str] = None):
        self.is_human = is_human
        self.name = playerNumber.name if name is None else name
        self.playerNumber = playerNumber
        self.bank_resources = bank_resources

        # Resources (0 for each)
        self.resources: ResourceCount = {
            resource: 0 for resource in Resource
        }

        # Assets on the board
        self.settlements: List[Vertex] = []
        self.cities: List[Vertex] = []
        self.roads: List[Edge] = []

        # Game metrics
        self.longest_road_length: int = 0
        self.has_longest_road: bool = False
        self.army_size: int = 0
        self.has_largest_army: bool = False
        self.best_opponents_victory_point: int = 0

        self.development_cards: List[DevelopmentCard] = []

    def calc_victory_points(self) -> Tuple[int, int]:
        """Return (visible_points, total_points), with hidden Victory Point cards included in total."""
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
        hidden_vp_cards = sum(
            1 for card in self.development_cards
            if card.card_type == DevelopmentCardType.VICTORY_POINT
        )

        total_points = visible_points + hidden_vp_cards
        return visible_points, total_points

    def __repr__(self):
        return self.name

    def add_resource(self, resource: Resource, amount: int) -> None:
        """Add a given amount of a resource to the player."""
        move_amount = min(self.bank_resources[resource], amount)

        self.bank_resources[resource] -= move_amount
        self.resources[resource] += move_amount

    def add_resources(self, resources: ResourceCount) -> None:
        """Adds multiple resources."""
        for resource, amount in resources.items():
            self.add_resource(resource, amount)

    def remove_resource(self, resource: Resource, amount: int) -> None:
        """Removes a given amount of a resource."""
        move_amount = min(self.resources[resource], amount)

        self.bank_resources[resource] += move_amount
        self.resources[resource] -= move_amount

    def remove_resources(self, resources: ResourceCount) -> None:
        """Removes multiple resources."""
        for resource, amount in resources.items():
            self.remove_resource(resource, amount)

    def add_settlement(self, vertex) -> None:
        """Add a settlement at the given vertex."""
        self.settlements.append(vertex)

    def add_city(self, vertex) -> None:
        """Upgrade a settlement to a city at the given vertex."""
        if vertex in self.settlements:
            self.settlements.remove(vertex)
        self.cities.append(vertex)

    def add_road(self, edge) -> None:
        """Add a road along the given edge."""
        self.roads.append(edge)

    def get_ports(self) -> List[Port]:
        """Returns the list of ports owned by the player"""
        return [v.port for v in self.settlements + self.cities if v.port is not None]

    def calculate_discard_count(self) -> int:
        """Return the number of resource cards to discard when a robber is thrown"""
        resource_count = sum(self.resources.values())
        if resource_count < 7:
            return 0
        return resource_count // 2
