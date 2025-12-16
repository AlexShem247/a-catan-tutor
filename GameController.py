from typing import Callable, List, Tuple, Optional

from game.Edge import Edge, EdgeDirection
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex, VertexDirection
from view.display import display_results


class GameController:
    """
    Controls the flow of a Catan game using a pure Game model.
    Handles turns, building actions, and dice rolls via hooks.
    """

    def __init__(
            self,
            game: Game,
            get_settlement_choice: Callable[[Player, "GameController"], Vertex] = None,
            get_road_choice: Callable[[Vertex, "GameController"], Edge] = None,
            get_settlement_choice_ai: Callable[[Player, "GameController"], Vertex] = None,
            get_road_choice_ai: Callable[[Vertex, "GameController"], Edge] = None,
            play_round_hook: Callable[[Player, "GameController"], None] = None,
            play_round_ai_hook: Callable[[Player, "GameController"], None] = None,
            trade_manager_hook: Callable[["GameController", Player, ResourceCount, ResourceCount,
                                          Player], Tuple[bool, Optional[ResourceCount]]] = None,
            trade_manager_ai_hook: Callable[
                [Player, ResourceCount, ResourceCount, int], Tuple[bool, Optional[ResourceCount]]] = None,
            robber_discard_hook: Callable[[Player, "GameController", int, bool], ResourceCount] = None,
            robber_discard_ai_hook: Callable[[Player, "GameController", int, bool], ResourceCount] = ResourceCount,
            place_robber_hook: Callable[[Player, "GameController"], Tuple[HexTile, Optional[Player]]] = None,
            place_robber_ai_hook: Callable[[Player, "GameController"], Tuple[HexTile, Optional[Player]]] = None,
    ):
        self._game = game
        self.round_num = 1

        self.get_settlement_choice = get_settlement_choice
        self.get_road_choice = get_road_choice
        self.play_round_hook = play_round_hook

        self.get_settlement_choice_ai = get_settlement_choice_ai
        self.get_road_choice_ai = get_road_choice_ai
        self.play_round_ai_hook = play_round_ai_hook

        self.trade_manager_hook = trade_manager_hook
        self.trade_manager_ai_hook = trade_manager_ai_hook

        self.robber_discard_hook = robber_discard_hook
        self.robber_discard_ai_hook = robber_discard_ai_hook
        self.place_robber_hook = place_robber_hook
        self.place_robber_ai_hook = place_robber_ai_hook

    def run_initial_placement(self):
        """
        Each player places two settlements and two roads in order:
        forward + reverse order for second placement.
        """
        players_order = self._game.players + list(reversed(self._game.players))
        for player in players_order:
            # Settlement
            if player.is_human and self.get_settlement_choice:
                vertex = self.get_settlement_choice(player, self)
            else:
                vertex = self.get_settlement_choice_ai(player, self)
            self._game.try_build_settlement(player, vertex, use_resources=False, road_restriction=False)

            # Road
            if player.is_human and self.get_road_choice:
                edge = self.get_road_choice(vertex, self)
            else:
                edge = self.get_road_choice_ai(vertex, self)
            self._game.try_build_road(player, edge, use_resources=False)

    def start_game(self):
        """Run initial placement, then loop turns until game over."""
        self.run_initial_placement()
        while not self._game.game_over:
            for player in self._game.players:
                if player.is_human:
                    if self.play_round_hook:
                        self.play_round_hook(player, self)
                else:
                    if self.play_round_ai_hook:
                        self.play_round_ai_hook(player, self)

                if self._game.game_over:
                    break

            self.round_num += 1

        display_results(self._game)

    def trade_with_players(self, selling_player, selling, buying) -> List[Tuple[Player, Optional[ResourceCount]]]:
        """Sees which players are willing to trade"""
        results = []
        for player in self._game.players:
            if player != selling_player:
                if player.is_human:
                    interested, counter = self.trade_manager_hook(self, player, selling, buying, selling_player)
                else:
                    interested, counter = self.trade_manager_ai_hook(player, selling, buying, self.round_num)

                if interested:
                    results.append((player, counter))

        return results

    def get_game_state(self):
        """Returns the internal game state"""
        return self._game

    def roll_dice(self, player: Player) -> Tuple[int, int, int]:
        """Roll two dice and distribute resources to players."""
        d1, d2, total = self._game.roll_dice()
        if total == Game.ROBBER_DICE_NUM:
            # Perform robber actions
            # 1. All players must discard half of their resources
            for p in self._game.players:
                discard_count = p.calculate_discard_count()
                if discard_count > 0:
                    if p.is_human:
                        resources_to_discard = self.robber_discard_hook(p, self, discard_count, False)
                    else:
                        resources_to_discard = self.robber_discard_ai_hook(p, self, discard_count, False)
                    p.remove_resources(resources_to_discard)

            # 2. Player who rolled dice can move robber and collect resources
            if player.is_human:
                tile, steal_from = self.place_robber_hook(player, self)
            else:
                tile, steal_from = self.place_robber_ai_hook(player, self)

            self._game.set_robber(tile)

            if steal_from is not None:
                if steal_from.is_human:
                    resource = self.robber_discard_hook(steal_from, self, 1, True)
                else:
                    resource = self.robber_discard_ai_hook(steal_from, self, 1, True)
                self._game.trade_between_players(player, {}, steal_from, resource)

        return d1, d2, total

    # <editor-fold desc="Controller wrapper methods for model">

    def get_vertex(self, q: int, r: int, corner_index: VertexDirection) -> Optional[Vertex]:
        """Return the Vertex object for hex (q,r) at corner_index 0-5."""
        return self._game.get_vertex(q, r, corner_index)

    def try_build_settlement(
            self,
            player: Player,
            vertex: Vertex,
            build: bool = True,
            use_resources: bool = True,
            road_restriction: bool = True
    ) -> tuple[bool, str]:
        """Attempt to build a settlement with rules enforced."""
        return self._game.try_build_settlement(player, vertex, build, use_resources, road_restriction)

    def get_edge(self, q: int, r: int, edge_index: EdgeDirection) -> Optional[Edge]:
        """Return the Edge object for hex (q,r) at edge_index 0-5."""
        return self._game.get_edge(q, r, edge_index)

    def try_build_road(
            self,
            player: Player,
            edge: Edge,
            on_vertex: Optional[Vertex] = None,
            build: bool = True,
            use_resources: bool = True
    ) -> tuple[bool, str]:
        """Attempt to build a road with rules enforced."""
        return self._game.try_build_road(player, edge, on_vertex, build, use_resources)

    def get_buildable_options(self, player: Player) -> dict:
        """
        Returns dict of possible Buildable actions and valid board locations.
        Empty list if player cannot afford or no legal space.
        """
        return self._game.get_buildable_options(player)

    def try_build_city(
            self,
            player: Player,
            vertex: Vertex,
            build: bool = True,
            use_resources: bool = True
    ) -> tuple[bool, str]:
        """Attempt to upgrade a settlement to a city."""
        return self._game.try_build_city(player, vertex, build, use_resources)

    def try_trade_with_bank(
            self, player: Player, selling: ResourceCount,
            buying: ResourceCount, use_resources: bool = True
    ) -> bool:
        """Attempt a bank trade using correct port discounts (2:1, 3:1, 4:1)."""
        return self._game.try_trade_with_bank(player, selling, buying, use_resources)

    def trade_between_players(self, player: Player, selling: ResourceCount,
                              buying_player: Player, buying: ResourceCount):
        """Execute a trade of resources between two players."""
        return self._game.trade_between_players(player, selling, buying_player, buying)

    def get_available_vertices(self, player: Player, building_type: Buildable, road_restriction: bool = True) -> \
            List[Vertex]:
        """Return a list of vertices where the player can build a settlement or city."""
        return self._game.get_available_vertices(player, building_type, road_restriction)

    def get_buildable_edges_for_vertex(self, vertex: Vertex) -> List[Edge]:
        """Return edges adjacent to a vertex where the player can build a road."""
        return self._game.get_buildable_edges_for_vertex(vertex)

    def get_trade_rate(self, player: Player, resource: Resource) -> int:
        """Return the best trade rate for 'player' when selling 'resource'."""
        return self._game.get_trade_rate(player, resource)

    def get_hex_tile(self, q: int, r: int) -> Optional[HexTile]:
        """Return the HexTile object for hex (q,r)."""
        return self._game.get_hex_tile(q, r)

    def get_players_on_hex(self, hex_tile):
        """Return a list of players who own a settlement or city on the given hex tile."""
        return self._game.get_players_on_hex(hex_tile)

    def get_all_hexes(self) -> List[HexTile]:
        """Return a list of all hex tiles on the board."""
        return self._game.get_all_hexes()

    def get_hex_tiles_with_players(self):
        """Return a list of hex tiles that have at least one player on them."""
        return self._game.get_hex_tiles_with_players()

    def try_buy_development_card(self, player) -> tuple[bool, str]:
        """Attempt to buy a development card for a player."""
        return self._game.try_buy_development_card(player)

    # </editor-fold>
