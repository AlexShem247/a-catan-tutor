from abc import ABC, abstractmethod
from random import Random
from typing import TYPE_CHECKING

from ai.actions import Action, Phase
from game.Edge import Edge
from game.HexTile import HexTile
from game.Player import Player
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex

if TYPE_CHECKING:
    from game.Game import Game


class AI(ABC):
    """Abstract interface for AI decision-making logic in the game."""

    def __init__(self, rng: Random):
        self.rng = rng
        self.policy_name = type(self).__name__

    @abstractmethod
    def choose_trade_partner(
        self,
        player: Player,
        game: "Game",
        selling: ResourceCount,
        buying: ResourceCount,
        available_players: list[tuple[Player, ResourceCount | None]],
    ) -> tuple[Player, ResourceCount | None] | None:
        """Choose the trade partner and offer to pursue."""
        ...

    @abstractmethod
    def select_initial_settlement_location(self, player: Player, game: "Game", available_vertices: list[Vertex]) \
            -> Vertex | None:
        """Select the opening settlement location."""
        ...

    @abstractmethod
    def select_initial_road_location(self, player: Player, game: "Game", available_edges: list[Edge]) -> Edge | None:
        """Select the opening road location."""
        ...

    @abstractmethod
    def select_robber_target(
        self,
        player: Player,
        game: "Game",
        valid_hexes: list[HexTile],
    ) -> tuple[HexTile, Player | None]:
        """Select the robber placement and steal target."""
        ...

    @abstractmethod
    def select_discard_resources(self, player: Player, game: "Game", num_resources: int) -> ResourceCount:
        """Select the resources to discard."""
        ...

    @abstractmethod
    def select_year_of_plenty_resources(self, player: Player, game: "Game") -> ResourceCount:
        """Select the resources to take from Year of Plenty."""
        ...

    @abstractmethod
    def select_monopoly_resource(self, player: Player, game: "Game") -> Resource:
        """Select the resource to claim with Monopoly."""
        ...

    @abstractmethod
    def respond_to_trade(self, player: Player, game: "Game", opponent: Player, selling: ResourceCount,
                         buying: ResourceCount) -> tuple[bool, ResourceCount | None]:
        """Decide how to respond to a trade offer."""
        ...

    @abstractmethod
    def next_action(self, player: Player, game: "Game", phase: Phase, dev_played: bool) -> Action:
        """Choose the next action for the current turn state."""
        ...

    @abstractmethod
    def new_turn(self):
        """Reset turn-specific state for a new turn."""
        ...
