from typing import Tuple, Optional, List

from ai.AI import AI
from ai.actions import Phase, Action
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex


class RuleBasedAI(AI):
    def choose_trade_partner(self, player: Player, game: "Game",
                             available_players: List[Tuple[Player, Optional[ResourceCount]]]) \
            -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        pass

    def select_settlement_location(self, player: Player, game: "Game", available_vertices: List[Vertex]) \
            -> Optional[Vertex]:
        pass

    def select_road_location(self, player: Player, game: "Game", available_edges: List[Edge]) -> Optional[Edge]:
        pass

    def select_robber_target(self, player: Player, game: "Game", valid_hexes: List[HexTile], get_players_on_hex_func,
                             has_resources_func) -> Tuple[HexTile, Optional[Player]]:
        pass

    def select_discard_resources(self, player: Player, game: "Game", num_resources: int) -> ResourceCount:
        pass

    def select_year_of_plenty_resources(self, player: Player, game: "Game") -> ResourceCount:
        pass

    def select_monopoly_resource(self, player: Player, game: "Game") -> Resource:
        pass

    def respond_to_trade(self, player: Player, game: "Game", selling: ResourceCount, buying: ResourceCount) \
            -> Tuple[bool, Optional[ResourceCount]]:
        pass

    def next_action(self, player: Player, game: "Game", phase: Phase, dev_played: bool) -> Action:
        pass
