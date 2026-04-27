from typing import List, Set, Dict, Optional

from ai.simulation.SimPlayerState import SimPlayerState, dice_probability
from ai.simulation.SimGame import SimGame
from game.Edge import Edge
from game.HexTile import HexTile
from game.Player import PlayerNumber
from game.Resources import Resource
from game.Vertex import Vertex


def get_reachable_vertices(start_vertex: Vertex, player_number: PlayerNumber, sim_game: SimGame,
                           available_vertices: List[Vertex]) -> Set[Vertex]:
    """Return all vertices reachable from start_vertex along roads owned by player_number."""
    visited: Set[Vertex] = set()
    stack: List[Vertex] = [start_vertex]
    ov = sim_game.overlay

    while stack:
        v = stack.pop()
        if v in visited:
            continue
        visited.add(v)

        for edge in v.edges:
            if ov.get_edge_owner_num(edge) != player_number:
                continue

            neighbour = edge.get_other_vertex(v)
            if neighbour not in visited and neighbour in available_vertices:
                stack.append(neighbour)

    return visited


def legal_settlement_vertex(player: SimPlayerState, vertex: Vertex, sim_game: SimGame) -> bool:
    """Return True if a settlement could be placed on vertex under overlay-aware rules."""
    ov = sim_game.overlay

    if ov.is_vertex_taken(vertex) or vertex in (player.settlements + player.cities):
        return False

    for edge in vertex.edges:
        neighbour = edge.get_other_vertex(vertex)
        if ov.is_vertex_taken(neighbour) or neighbour in (player.settlements + player.cities):
            return False

    return True


def find_edge_toward_vertex(from_vertex: Vertex, target_vertex: Vertex, available_edges: List[Edge]) -> Optional[Edge]:
    """Return the available edge adjacent to from_vertex that minimises estimated distance to target_vertex."""
    best_edge = None
    best_distance = float("inf")

    for edge in available_edges:
        if from_vertex not in edge.vertices:
            continue

        other_vertex = edge.get_other_vertex(from_vertex)
        distance = estimate_distance(other_vertex, target_vertex)

        if distance < best_distance:
            best_distance = distance
            best_edge = edge

    return best_edge


def estimate_distance(v1: Vertex, v2: Vertex) -> int:
    """Return a small discrete estimate of vertex-graph distance (0, 1, 2, or 3)."""
    if v1 == v2:
        return 0

    for edge in v1.edges:
        if edge.get_other_vertex(v1) == v2:
            return 1

    v1_neighbors = {edge.get_other_vertex(v1) for edge in v1.edges}
    v2_neighbors = {edge.get_other_vertex(v2) for edge in v2.edges}

    if v1_neighbors & v2_neighbors:
        return 2

    return 3


def moves_toward_vertex(from_vertex: Vertex, target_vertex: Vertex) -> bool:
    """Return True if from_vertex is estimated within distance 2 of target_vertex."""
    return estimate_distance(from_vertex, target_vertex) <= 2


def find_gap_connection(player_number: PlayerNumber, sim_game: SimGame, available_edges: List[Edge]) -> Optional[Edge]:
    """Return an edge that connects a structure to the road network or joins disconnected road segments."""
    ov = sim_game.overlay
    sp = ov.get_sim_player(player_number)

    road_vertices: Set[Vertex] = set()
    for road in sp.roads:
        road_vertices.update(road.vertices)

    structures = list(sp.settlements + sp.cities)

    for edge in available_edges:
        v1, v2 = edge.vertices

        for structure in structures:
            if (structure == v1 and v2 not in road_vertices) or (structure == v2 and v1 not in road_vertices):
                return edge

        v1_has_road = v1 in road_vertices
        v2_has_road = v2 in road_vertices
        if v1_has_road != v2_has_road:
            return edge

    return None


def find_edge_toward_vertex_from_any(player_number: PlayerNumber, sim_game: SimGame, target_vertex: Vertex,
                                     available_edges: List[Edge]) -> Optional[Edge]:
    """Return the edge extending from any player structure/endpoint that minimises estimated distance to target."""
    ov = sim_game.overlay
    sp = ov.get_sim_player(player_number)

    our_structures: List[Vertex] = list(sp.settlements + sp.cities)
    for road in sp.roads:
        our_structures.extend(road.vertices)

    best_edge = None
    best_distance = float("inf")

    for edge in available_edges:
        v1, v2 = edge.vertices
        if v1 in our_structures or v2 in our_structures:
            new_vertex = v2 if v1 in our_structures else v1
            distance = estimate_distance(new_vertex, target_vertex)
            if distance < best_distance:
                best_distance = distance
                best_edge = edge

    return best_edge


def score_hex_for_opponent(opponent_number: PlayerNumber, sim_game: SimGame, hex_tile: HexTile,
                           importance: Dict[Resource, float]) -> float:
    """Return a heuristic score of blocking hex_tile for opponent_number given resource importance weights."""
    resource = hex_tile.resource
    if resource not in importance:
        return 0.0

    imp = importance[resource]

    production = (
        dice_probability(hex_tile.production_number)
        * sim_game.game.count_player_buildings(
            next(p for p in sim_game.game.players if p.player_number == opponent_number),
            hex_tile
        )
    )

    return imp * production


def get_legal_settlement_vertices(sim_game: SimGame) -> List[Vertex]:
    """Return vertices that satisfy the distance rule under overlay-aware occupancy."""
    ov = sim_game.overlay
    legal_vertices: List[Vertex] = []

    for vertex in sim_game.game.get_all_vertices():
        if ov.is_vertex_taken(vertex):
            continue

        valid = True
        for edge in vertex.edges:
            neighbor = edge.get_other_vertex(vertex)
            if ov.is_vertex_taken(neighbor):
                valid = False
                break

        if valid:
            legal_vertices.append(vertex)

    return legal_vertices


def get_opponents(sim_game: SimGame, player_number) -> List[SimPlayerState]:
    """Return opponent SimPlayerStates from the overlay."""
    return [
        sp for num, sp in sim_game.overlay.sim_players.items()
        if num != player_number
    ]
