from abc import ABC, abstractmethod
from typing import Optional, List, Tuple, Dict

from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from game.Edge import Edge
from game.HexTile import HexTile


class AI(ABC):
    """Abstract interface for AI decision-making logic in the game."""

    @abstractmethod
    def select_build_action(self, player: Player) -> Optional[Buildable]:
        """Choose the next building or development action to attempt."""
        pass

    @abstractmethod
    def choose_resources(self, player: Player, num_resources: int) -> ResourceCount:
        """Select a set of resources to gain or give."""
        pass

    @abstractmethod
    def choose_trade_partner(self,
                             player: Player,
                             available_players: List[Tuple[Player, Optional[ResourceCount]]],
                             estimated_cost: int
                             ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        """Pick a player to trade with and optionally propose a counteroffer."""
        pass

    @abstractmethod
    def determine_trade(self,
                        player: Player,
                        cost: ResourceCount,
                        round_num: int,
                        bank_rate: int
                        ) -> Tuple[Optional[Resource], Optional[Resource], int, int]:
        """Plan a trade strategy: what to buy, what to sell, and at which rates."""
        pass

    @abstractmethod
    def is_player_trade_better(self, player: Player, ai_buying_rate: int, bank_rate: int) -> bool:
        """Evaluate if trading with another player is preferable to using the bank."""
        pass

    @abstractmethod
    def select_settlement_location(self, player: Player, available_vertices: List[Vertex]) -> Optional[Vertex]:
        """Select the vertex where a settlement should be built."""
        pass

    @abstractmethod
    def select_road_location(self, player: Player, available_edges: List[Edge]) -> Optional[Edge]:
        """Select the edge where a road should be built."""
        pass

    @abstractmethod
    def select_build_location(self,
                              player: Player,
                              buildable_options: Dict[Buildable, List | bool],
                              action: Buildable
                              ) -> Optional[Vertex | Edge | bool]:
        """Select the specific location to execute a chosen build action."""
        pass

    @abstractmethod
    def decide_dev_card_usage(self, player: Player) -> Optional[DevelopmentCardType]:
        """Choose which development card, if any, to play."""
        pass

    @abstractmethod
    def select_robber_target(self,
                             player: Player,
                             valid_hexes: List[HexTile],
                             get_players_on_hex_func,
                             has_resources_func
                             ) -> Tuple[HexTile, Optional[Player]]:
        """Select which hex to place the robber on and optionally which player to steal from."""
        pass

    @abstractmethod
    def select_discard_resources(self, player: Player, num_resources: int) -> ResourceCount:
        """Choose which resources to discard when forced by the robber."""
        pass

    @abstractmethod
    def select_year_of_plenty_resources(self, player: Player) -> ResourceCount:
        """Choose two resources to gain from a Year of Plenty card."""
        pass

    @abstractmethod
    def select_monopoly_resource(self, player: Player) -> Resource:
        """Choose a resource type to monopolise when playing a Monopoly card."""
        pass

    @abstractmethod
    def respond_to_trade(self,
                         player: Player,
                         selling: ResourceCount,
                         buying: ResourceCount,
                         round_num: int
                         ) -> Tuple[bool, Optional[ResourceCount]]:
        """Evaluate a trade offer and decide to accept, reject, or propose a counteroffer."""
        pass
