from typing import List

from ai.ai_utils.SimPlayerState import SimPlayerState
from ai.ai_utils.actions import ActionType, Action
from config.performance_constants import EPSILON
from game.Game import Game
from game.PlayerAssets import Buildable
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex, Port


def expected_rolls_for_resource(player: SimPlayerState, resource: Resource) -> float:
    """Estimate the expected number of dice rolls to gather one unit of the given resource."""
    fr = player.get_production_rate(resource)

    if fr <= EPSILON:
        return float("inf")  # Cannot produce this resource

    # Expected rolls to get one unit
    return 1 / fr


def calc_step_resources(step: Action) -> ResourceCount:
    """Calculate the resource cost of a single action."""
    total_resources = {res: 0 for res in Resource}
    if step.type == ActionType.BUILD:
        building: Buildable = step.payload[0]
        for res, cost in Game.BUILDING_COST[building].items():
            total_resources[res] = total_resources.get(res, 0) + cost
    elif step.type == ActionType.BUY_DEV_CARD:
        total_resources = Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD]

    return total_resources


def get_bank_trade_ratio(buildings: List[Vertex], resource: Resource) -> int:
    """Determine the best trade ratio for a resource given a player's controlled ports."""

    # Get all ports the player controls (deterministic order)
    controlled_ports = []
    for v in buildings:
        if v.port and v.port not in controlled_ports:
            controlled_ports.append(v.port)

    # Check for specific 2:1 port for this resource
    specific_port = Port.resource_to_port(resource)
    if specific_port in controlled_ports:
        return 2

    # Check for generic 3:1 port
    if Port.THREE_TO_ONE in controlled_ports:
        return 3

    # Default bank rate
    return 4
