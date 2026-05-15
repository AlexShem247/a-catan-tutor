from enum import IntEnum, Enum
from typing import List, Optional, TYPE_CHECKING, Tuple, Set

from game.HexTile import HexTile
from game.PlayerAssets import Building
from game.Resources import Resource

if TYPE_CHECKING:
    from game.Player import Player
    from game.Edge import Edge


class VertexDirection(IntEnum):
    TOP = 0
    TOP_RIGHT = 1
    BOTTOM_RIGHT = 2
    BOTTOM = 3
    BOTTOM_LEFT = 4
    TOP_LEFT = 5


class Port(Enum):
    WOOD = 0
    BRICK = 1
    SHEEP = 2
    WHEAT = 3
    ORE = 4
    THREE_TO_ONE = 5

    @classmethod
    def resource_to_port(cls, resource: Resource) -> Optional["Port"]:
        """Convert a resource type into its matching port type."""
        resource_to_port = {
            Resource.WOOD: cls.WOOD,
            Resource.BRICK: cls.BRICK,
            Resource.SHEEP: cls.SHEEP,
            Resource.WHEAT: cls.WHEAT,
            Resource.ORE: cls.ORE,
        }
        return resource_to_port.get(resource)


class Vertex:
    def __init__(self, pos: Tuple[int, int, VertexDirection]):
        self.hexes: List[HexTile] = []
        self.edges: List[Edge] = []
        self.owner: Optional[Player] = None
        self.building: Optional[Building] = None
        self.pos = pos
        self.port: Optional[Port] = None

    def get_pos(self) -> str:
        """Return the board position label for this object."""
        q, r, direction = self.pos
        return f"{q}, {r}, {direction.name.title().replace('_', ' ')}"

    def get_neighbours(self) -> Set["Vertex"]:
        """Return the neighboring vertices connected by edges."""
        neighbor_vertices = set()
        for edge in self.edges:
            # Add the other vertex of the edge
            if edge.vertices[0] != self:
                neighbor_vertices.add(edge.vertices[0])
            if edge.vertices[1] != self:
                neighbor_vertices.add(edge.vertices[1])
        return neighbor_vertices

    def get_edge_between(self, neighbour: "Vertex") -> Optional["Edge"]:
        """Return the edge connecting this vertex to the neighbor."""
        for edge in self.edges:
            if edge.vertices[0] == neighbour or edge.vertices[1] == neighbour:
                return edge
        return None

    def __repr__(self) -> str:
        if not self.owner:
            return f"EMPTY({self.get_pos()})"
        return f"{self.owner.name}-{self.building.name}({self.get_pos()})"
