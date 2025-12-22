from enum import Enum
from typing import Literal, Dict, TypeAlias


class HexType(Enum):
    FOREST = 0
    HILLS = 1
    PASTURE = 2
    FIELDS = 3
    MOUNTAINS = 4
    DESERT = 5


class Resource(Enum):
    WOOD = 0
    BRICK = 1
    SHEEP = 2
    WHEAT = 3
    ORE = 4


ResourceCount: TypeAlias = Dict[Resource, int]

HEX_TO_RESOURCE: Dict[HexType, Resource] = {
    HexType.FOREST: Resource.WOOD,
    HexType.HILLS: Resource.BRICK,
    HexType.PASTURE: Resource.SHEEP,
    HexType.FIELDS: Resource.WHEAT,
    HexType.MOUNTAINS: Resource.ORE,
}
