from dataclasses import dataclass, field
from typing import Dict, Optional

from game.Game import Game
from game.Player import PlayerNumber, Player
from game.Vertex import Vertex
from game.Edge import Edge

from ai.ai_utils.SimPlayerState import SimPlayerState


@dataclass
class BoardOverlay:
    """Counterfactual board state storing hypothetical ownership and simulated players."""

    vertex_owner: Dict[Vertex, PlayerNumber] = field(default_factory=dict)
    edge_owner: Dict[Edge, PlayerNumber] = field(default_factory=dict)

    # Simulated players indexed by player_number
    sim_players: Dict[PlayerNumber, SimPlayerState] = field(default_factory=dict)

    def copy(self) -> "BoardOverlay":
        """Return a shallow copy of the overlay with identical counterfactual state."""
        return BoardOverlay(
            vertex_owner=dict(self.vertex_owner),
            edge_owner=dict(self.edge_owner),
            sim_players=dict(self.sim_players),
        )

    def get_sim_player(self, player_number: PlayerNumber) -> SimPlayerState:
        """Return the SimPlayerState for the given player number."""
        return self.sim_players[player_number]

    def set_sim_player(self, sim_player: SimPlayerState) -> None:
        """Register or replace a SimPlayerState in the overlay."""
        self.sim_players[sim_player.player_number] = sim_player

    def get_vertex_owner_num(self, vertex: Vertex) -> Optional[PlayerNumber]:
        """Return the player number owning a vertex in real or simulated state."""
        if vertex.owner is not None:
            return vertex.owner.player_number
        return self.vertex_owner.get(vertex)

    def is_vertex_taken(self, vertex: Vertex) -> bool:
        """Return True if the vertex is occupied in real or simulated state."""
        return self.get_vertex_owner_num(vertex) is not None

    def get_edge_owner_num(self, edge: Edge) -> Optional[PlayerNumber]:
        """Return the player number owning an edge in real or simulated state."""
        if edge.owner is not None:
            return edge.owner.player_number
        return self.edge_owner.get(edge)

    def is_edge_taken(self, edge: Edge) -> bool:
        """Return True if the edge is occupied in real or simulated state."""
        return self.get_edge_owner_num(edge) is not None

    def claim_vertex(self, vertex: Vertex, player_number: PlayerNumber) -> None:
        """Mark a vertex as owned by a player in the simulated state."""
        self.vertex_owner[vertex] = player_number

    def claim_edge(self, edge: Edge, player_number: PlayerNumber) -> None:
        """Mark an edge as owned by a player in the simulated state."""
        self.edge_owner[edge] = player_number


@dataclass(frozen=True)
class SimGame:
    """Read-only game reference paired with a mutable counterfactual board overlay."""

    game: Game
    overlay: BoardOverlay

    @staticmethod
    def from_real_game(
        game: Game,
        hide_opponent_dev_cards: bool = True,
    ) -> "SimGame":
        """Construct a SimGame with fresh SimPlayerStates derived from the real game."""
        overlay = BoardOverlay()

        for player in game.players:
            opponent_flag = hide_opponent_dev_cards
            sim_player = SimPlayerState(player, opponent=opponent_flag)
            overlay.set_sim_player(sim_player)

        return SimGame(game=game, overlay=overlay)

    def copy_with_players(self, sim_players: Dict[PlayerNumber, SimPlayerState]) -> "SimGame":
        """Return a new SimGame sharing board state but using supplied SimPlayerStates."""
        new_overlay = self.overlay.copy()
        new_overlay.sim_players = dict(sim_players)
        return SimGame(game=self.game, overlay=new_overlay)


def make_sim_game_for_player(game: Game, player: Player) -> SimGame:
    """Create a SimGame and ensure `player` is a full-information SimPlayerState in the overlay."""
    sim_game = SimGame.from_real_game(game, hide_opponent_dev_cards=True)

    sim_us = SimPlayerState(player, opponent=False)
    overlay2 = sim_game.overlay.copy()
    overlay2.set_sim_player(sim_us)

    return SimGame(game=sim_game.game, overlay=overlay2)
