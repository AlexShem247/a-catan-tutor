from enum import Enum
from typing import Dict, List, Optional

from game.Edge import Edge
from game.Resources import Resource
from game.Vertex import Vertex


class PlayerNumber(Enum):
    P1 = 0
    P2 = 1
    P3 = 2
    P4 = 3


class Player:
    def __init__(self, playerNumber: PlayerNumber, name: Optional[str] = None):
        self.name = playerNumber.name if name is None else name
        self.playerNumber = playerNumber

        # Resources (0 for each)
        self.resources: Dict[Resource, int] = {
            resource: 0 for resource in Resource
        }

        # Assets on the board
        self.settlements: List[Vertex] = []
        self.cities: List[Vertex] = []
        self.roads: List[Edge] = []

        # Game metrics
        self.victory_points: int = 0
        self.longest_road_length: int = 0
        self.has_longest_road: bool = False

    def __repr__(self):
        return self.name

    def add_resource(self, resource: Resource, amount: int) -> None:
        """Add a given amount of a resource to the player."""
        self.resources[resource] += amount

    def remove_resource(self, resource: Resource, amount: int) -> None:
        """Removes a given amount of a resource."""
        self.resources[resource] = max(0, self.resources[resource] - amount)

    def add_settlement(self, vertex) -> None:
        """Add a settlement at the given vertex."""
        self.settlements.append(vertex)

    def add_city(self, vertex) -> None:
        """Upgrade a settlement to a city at the given vertex."""
        self.settlements.remove(vertex)
        self.cities.append(vertex)

    def add_road(self, edge) -> None:
        """Add a road along the given edge."""
        self.roads.append(edge)


