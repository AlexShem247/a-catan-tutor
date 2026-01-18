from abc import ABC, abstractmethod
from typing import Optional, List, Tuple, Dict

from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from game.Edge import Edge
from game.HexTile import HexTile


class AI(ABC):
    """Abstract interface for pure AI decision-making logic."""

    @abstractmethod
    def choose_build_action(self, ) -> Optional[Buildable]:
        """Choose a desired build action for the AI."""
        pass

    @abstractmethod
    def pick_random_resources(self,
                              resources: ResourceCount,
                              num_resources: int
                              ) -> ResourceCount:
        """Randomly pick num_resources resource units."""
        pass

    @abstractmethod
    def pick_trade_partner(self,
                           resources: ResourceCount,
                           available_players: List[Tuple[Player, Optional[ResourceCount]]],
                           estimated_cost: int
                           ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        """Decide which trade to follow through with."""
        pass

    @abstractmethod
    def decide_trade_strategy(self,
                              player_resources: ResourceCount,
                              cost: ResourceCount,
                              round_num: int,
                              bank_rate: int
                              ) -> Tuple[Optional[Resource], Optional[Resource], int, int]:
        """Decide trade strategy."""
        pass

    @abstractmethod
    def should_trade_with_player(self,
                                 ai_buying_rate: int,
                                 bank_rate: int
                                 ) -> bool:
        """Determine if player trade is preferable to bank trade."""
        pass

    @abstractmethod
    def choose_random_settlement(self,
                                 available_vertices: List[Vertex]
                                 ) -> Optional[Vertex]:
        """Choose a random settlement vertex."""
        pass

    @abstractmethod
    def choose_random_road(self,
                           available_edges: List[Edge]
                           ) -> Optional[Edge]:
        """Choose a random road edge."""
        pass

    @abstractmethod
    def choose_random_build_location(self,
                                     buildable_options: Dict[Buildable, List | bool],
                                     action: Buildable
                                     ) -> Optional[Vertex | Edge | bool]:
        """Choose a random build location."""
        pass

    @abstractmethod
    def can_build_development_card(self,
                                   buildable_options: Dict[Buildable, List | bool]
                                   ) -> bool:
        """Check if development card can be built."""
        pass

    @abstractmethod
    def decide_dev_card_usage(self,
                              playable_cards: List[DevelopmentCardType],
                              used_dev_card: bool
                              ) -> Optional[DevelopmentCardType]:
        """Decide whether to use a development card."""
        pass

    @abstractmethod
    def decide_robber_placement(self,
                                valid_hexes: List[HexTile],
                                current_player: Player,
                                get_players_on_hex_func,
                                has_resources_func
                                ) -> Tuple[HexTile, Optional[Player]]:
        """Decide where to place the robber and who to steal from."""
        pass

    @abstractmethod
    def decide_robber_discard(self,
                              player_resources: ResourceCount,
                              num_resources: int
                              ) -> ResourceCount:
        """Decide which resources to discard."""
        pass

    @abstractmethod
    def decide_year_of_plenty_resources(self,
                                        available_resources: ResourceCount
                                        ) -> ResourceCount:
        """Decide which two resources to take."""
        pass

    @abstractmethod
    def decide_monopoly_resource(self,
                                 available_resources: ResourceCount
                                 ) -> Resource:
        """Decide which resource to monopolise."""
        pass

    @abstractmethod
    def trade_manager_ai_logic(self,
                               player_resources: ResourceCount,
                               selling: ResourceCount,
                               buying: ResourceCount,
                               round_num: int
                               ) -> Tuple[bool, Optional[ResourceCount]]:
        """Decide whether to accept, reject, or counter a trade."""
        pass

    @abstractmethod
    def decide_post_roll_dev_card_usage(self,
                                        playable_cards: List[DevelopmentCardType],
                                        used_dev_card: bool
                                        ) -> Optional[DevelopmentCardType]:
        """Decide whether to use a development card post-roll."""
        pass
