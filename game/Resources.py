from enum import Enum
from typing import Literal, Dict, TypeAlias

HexType = Literal["forest", "hills", "pasture", "fields", "mountains", "desert"]


class Resource(Enum):
    WOOD = 0
    BRICK = 1
    SHEEP = 2
    WHEAT = 3
    ORE = 4


ResourceCount: TypeAlias = Dict[Resource, int]

HEX_TO_RESOURCE: Dict[HexType, Resource] = {
    "forest": Resource.WOOD,
    "hills": Resource.BRICK,
    "pasture": Resource.SHEEP,
    "fields": Resource.WHEAT,
    "mountains": Resource.ORE,
}
