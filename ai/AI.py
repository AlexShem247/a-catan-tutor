from abc import ABC, abstractmethod
from random import Random
from typing import Optional, List, Tuple, TYPE_CHECKING

from ai.ai_utils.actions import Action, Phase
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
        """Initialise the AI"""
        self.rng = rng

    @abstractmethod
    def choose_trade_partner(self, player: Player, game: "Game", selling: ResourceCount, buying: ResourceCount,
                             available_players: List[Tuple[Player, Optional[ResourceCount]]],
                             ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        """Pick a player to trade with and optionally propose a counteroffer."""
        pass

    @abstractmethod
    def select_initial_settlement_location(self, player: Player, game: "Game", available_vertices: List[Vertex]) \
            -> Optional[Vertex]:
        """Select the vertex where a settlement should be built."""
        pass

    @abstractmethod
    def select_initial_road_location(self, player: Player, game: "Game", available_edges: List[Edge]) -> Optional[Edge]:
        """Select the edge where a road should be built."""
        pass

    @abstractmethod
    def select_robber_target(self,
                             player: Player,
                             game: "Game",
                             valid_hexes: List[HexTile],
                             ) -> Tuple[HexTile, Optional[Player]]:
        """Select which hex to place the robber on and optionally which player to steal from."""
        pass

    @abstractmethod
    def select_discard_resources(self, player: Player, game: "Game", num_resources: int) -> ResourceCount:
        """Choose which resources to discard when forced by the robber."""
        pass

    @abstractmethod
    def select_year_of_plenty_resources(self, player: Player, game: "Game") -> ResourceCount:
        """Choose two resources to gain from a Year of Plenty card."""
        pass

    @abstractmethod
    def select_monopoly_resource(self, player: Player, game: "Game") -> Resource:
        """Choose a resource type to monopolise when playing a Monopoly card."""
        pass

    @abstractmethod
    def respond_to_trade(self, player: Player, game: "Game", opponent: Player, selling: ResourceCount,
                         buying: ResourceCount) -> Tuple[bool, Optional[ResourceCount]]:
        """Evaluate a trade offer and decide to accept, reject, or propose a counteroffer."""
        pass

    @abstractmethod
    def next_action(self, player: Player, game: "Game", phase: Phase, dev_played: bool) -> Action:
        """
        Decide the next atomic action to execute this turn.

        Returns:
            Action: the chosen action to execute
            Action(ActionType.END_TURN): no further actions this turn
        """
        pass

    @abstractmethod
    def new_turn(self):
        """Method called at the beginning of every round"""
        pass
