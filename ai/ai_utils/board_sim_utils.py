from typing import List, Set, Dict, Optional

from ai.ai_utils.SimPlayerState import SimPlayerState, dice_probability
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.Resources import Resource
from game.Vertex import Vertex


def get_reachable_vertices(start_vertex: Vertex, player: Player, available_vertices: List[Vertex]) -> Set[Vertex]:
    """Return all vertices reachable by the player from start_vertex along their roads."""
    visited: Set[Vertex] = set()
    stack: List[Vertex] = [start_vertex]

    while stack:
        v = stack.pop()
        if v in visited:
            continue
        visited.add(v)

        # Check neighbouring vertices connected by player's roads
        for edge in v.edges:
            if edge.owner == player:
                neighbour = edge.get_other_vertex(v)
                # Must be empty and obey distance rule
                if neighbour not in visited and neighbour in available_vertices:
                    stack.append(neighbour)

    return visited


def legal_settlement_vertex(player: SimPlayerState, vertex: Vertex) -> bool:
    """Check if a settlement can legally be placed on the given vertex."""
    if vertex in (player.settlements + player.cities) or vertex.owner is not None:
        # Vertex already built on
        return False

    # Check 2-distance rule: no neighbor of this vertex has a building
    for edge in vertex.edges:
        neighbour = edge.get_other_vertex(vertex)
        if neighbour in [player.settlements + player.cities] or neighbour.owner is not None:
            # Neighbour owned
            return False

    return True


def find_edge_toward_vertex(from_vertex: Vertex, target_vertex: Vertex, available_edges: List[Edge]) -> Optional[Edge]:
    """Find the available edge that moves closer from from_vertex to target_vertex."""
    best_edge = None
    best_distance = float("inf")

    for edge in available_edges:
        if from_vertex not in edge.vertices:
            continue

        other_vertex = edge.get_other_vertex(from_vertex)

        # Estimate distance from this vertex to target
        distance = estimate_distance(other_vertex, target_vertex)

        if distance < best_distance:
            best_distance = distance
            best_edge = edge

    return best_edge


def estimate_distance(v1: Vertex, v2: Vertex) -> int:
    """Estimate the distance in vertices between two vertices (1, 2, or 3)."""
    if v1 == v2:
        return 0

    # Check direct connection
    for edge in v1.edges:
        if edge.get_other_vertex(v1) == v2:
            return 1

    # Check if they share a neighbor (distance = 2)
    v1_neighbors = {edge.get_other_vertex(v1) for edge in v1.edges}
    v2_neighbors = {edge.get_other_vertex(v2) for edge in v2.edges}

    if v1_neighbors & v2_neighbors:
        return 2

    return 3  # Further away


def moves_toward_vertex(from_vertex: Vertex, target_vertex: Vertex) -> bool:
    """Return True if moving from from_vertex brings us closer to target_vertex."""
    return estimate_distance(from_vertex, target_vertex) <= 2


def find_gap_connection(player: Player, available_edges: List[Edge]) -> Optional[Edge]:
    """Find an edge that connects disconnected roads or links a settlement to a road network."""

    # Get all vertices connected by our roads
    road_vertices = set()
    for road in player.roads:
        road_vertices.update(road.vertices)

    # Check each available edge
    for edge in available_edges:
        v1, v2 = edge.vertices

        # Check if this connects a settlement/city to road network
        for structure in player.settlements + player.cities:
            if (structure == v1 and v2 not in road_vertices) or \
                    (structure == v2 and v1 not in road_vertices):
                return edge

        # Check if this connects two disconnected road segments
        v1_has_road = v1 in road_vertices
        v2_has_road = v2 in road_vertices

        if v1_has_road != v2_has_road:  # One has road, one doesn't
            return edge

    return None


def find_edge_toward_vertex_from_any(player: Player, target_vertex: Vertex,
                                     available_edges: List[Edge]) -> Optional[Edge]:
    """Find an edge extending from any player structure toward the target vertex."""

    # Get all our structures (settlements, cities, road endpoints)
    our_structures = list(player.settlements + player.cities)
    for road in player.roads:
        our_structures.extend(road.vertices)

    # Find edge that gets us closest to target from any structure
    best_edge = None
    best_distance = float("inf")

    for edge in available_edges:
        v1, v2 = edge.vertices

        # Check if edge connects to one of our structures
        if v1 in our_structures or v2 in our_structures:
            # Get the vertex that's NOT our structure (the new extension)
            new_vertex = v2 if v1 in our_structures else v1

            # Estimate distance from new vertex to target
            distance = estimate_distance(new_vertex, target_vertex)

            if distance < best_distance:
                best_distance = distance
                best_edge = edge

    return best_edge


def score_hex_for_opponent(opponent: Player, game: Game, hex_tile: HexTile, importance: Dict[Resource, float]) \
        -> float:
    """Compute the strategic value of a hex tile for an opponent based on resource and production."""

    resource = hex_tile.resource

    # Resource not needed
    if resource not in importance:
        return 0.0

    imp = importance[resource]

    # Expected production
    production = (
            dice_probability(hex_tile.production_number)
            * game.count_player_buildings(opponent, hex_tile)
    )

    return imp * production


def get_legal_settlement_vertices(game: Game) -> List[Vertex]:
    """Get all vertices where settlement could be legally placed."""
    legal_vertices = []

    for vertex in game.get_all_vertices():
        # Skip if already occupied
        if vertex.owner is not None:
            continue

        # Check distance rule
        valid = True
        for edge in vertex.edges:
            neighbor = edge.get_other_vertex(vertex)
            if neighbor.owner is not None:
                valid = False
                break

        if valid:
            legal_vertices.append(vertex)

    return legal_vertices


def get_opponents(player: SimPlayerState, game: Game) -> List[SimPlayerState]:
    """Return a list of opponent player states for the given player."""
    return [SimPlayerState(p, opponent=True) for p in game.players if p.player_number != player.player_number]
