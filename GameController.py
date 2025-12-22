from typing import Callable, List, Tuple, Optional, TYPE_CHECKING

from drawing.constants import AI_DECISION_ANIMATION_DELAY, AI_DECISION_ANIMATION_DELAY_SIMULATION_MODE
from game.Edge import Edge, EdgeDirection
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex, VertexDirection, Port

if TYPE_CHECKING:
    from drawing.View import View


class GameController:
    """
    Controls the flow of a Catan game using a pure Game model.
    Handles turns, building actions, and dice rolls via hooks.
    """
    _game: Game
    round_num: int

    def __init__(
            self,
            get_game_type: Callable[["View"], bool] = None,
            get_settlement_choice: Callable[[Player, "GameController", "View"], Vertex] = None,
            get_road_choice: Callable[[Player, "GameController", "View", Optional[Vertex]], Edge] = None,
            get_settlement_choice_ai: Callable[[Player, "GameController", "View"], Vertex] = None,
            get_road_choice_ai: Callable[[Player, "GameController", "View", Optional[Vertex]], Edge] = None,
            play_round_hook: Callable[[Player, "GameController", "View"], None] = None,
            play_round_ai_hook: Callable[[Player, "GameController", "View"], None] = None,
            trade_manager_hook: Callable[["GameController", Player, "View", ResourceCount, ResourceCount,
                                          Player], Tuple[bool, Optional[ResourceCount]]] = None,
            trade_manager_ai_hook: Callable[
                [Player, ResourceCount, ResourceCount, int], Tuple[bool, Optional[ResourceCount]]] = None,
            robber_discard_hook: Callable[[Player, "GameController", "View", int, bool], ResourceCount] = None,
            robber_discard_ai_hook: Callable[[Player, "GameController", "View",
                                              int, bool], ResourceCount] = ResourceCount,
            place_robber_hook: Callable[[Player, "GameController", "View"], Tuple[HexTile, Optional[Player]]] = None,
            place_robber_ai_hook: Callable[[Player, "GameController", "View"], Tuple[HexTile, Optional[Player]]] = None,

            year_of_plenty_selection: Callable[["GameController", "View"], ResourceCount] = None,
            year_of_plenty_selection_ai: Callable[["GameController"], ResourceCount] = None,
            monopoly_selection: Callable[["GameController", "View"], Resource] = None,
            monopoly_selection_ai: Callable[["GameController"], Resource] = None,
    ):
        self.get_game_type = get_game_type

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

        self.year_of_plenty_selection = year_of_plenty_selection
        self.year_of_plenty_selection_ai = year_of_plenty_selection_ai

        self.monopoly_selection = monopoly_selection
        self.monopoly_selection_ai = monopoly_selection_ai
        self.view: View | None = None

        self.reset_game(True)

    def reset_game(self, human_player_one: bool):
        """Reset the game to a fresh state and reset round counter."""
        self._game = Game(human_player_one=human_player_one)
        self.round_num = 1
        if self.view is not None:
            self.view.ai_decision_animation_delay = (AI_DECISION_ANIMATION_DELAY if human_player_one
                                                     else AI_DECISION_ANIMATION_DELAY_SIMULATION_MODE)

    def start_game(self):
        """Run initial placement, then loop turns until game over."""
        human_player_one: bool = self.get_game_type(self.view)
        self.reset_game(human_player_one)

        self.run_initial_placement()
        while not self._game.game_over:
            for player in self._game.players:
                if player.is_human:
                    self.play_round_hook(player, self, self.view)
                else:
                    self.play_round_ai_hook(player, self, self.view)

                # Set development cards to playable
                for card in player.development_cards:
                    card.playable = card.card_type != DevelopmentCardType.VICTORY_POINT  # You cannot play VP cards

                if self._game.game_over:
                    break

            self.round_num += 1

        self.view.display_results()

    def run_initial_placement(self):
        """
        Each player places two settlements and two roads in order:
        forward + reverse order for second placement.
        """
        players_order = [(p, False) for p in self._game.players] + [(p, True) for p in reversed(self._game.players)]
        for player, gain_resource in players_order:
            # Settlement
            if player.is_human and self.get_settlement_choice:
                vertex = self.get_settlement_choice(player, self, self.view)
            else:
                vertex = self.get_settlement_choice_ai(player, self, self.view)
            self._game.try_build_settlement(player, vertex, use_resources=False,
                                            road_restriction=False, gain_resources=gain_resource)

            # Road
            if player.is_human and self.get_road_choice:
                edge = self.get_road_choice(player, self, self.view, vertex)
            else:
                edge = self.get_road_choice_ai(player, self, self.view, vertex)
            self._game.try_build_road(player, edge, use_resources=False)

    def trade_with_players(self, selling_player, selling, buying) -> List[Tuple[Player, Optional[ResourceCount]]]:
        """Sees which players are willing to trade"""
        results = []
        for player in self._game.players:
            if player != selling_player:
                if player.is_human:
                    interested, counter = self.trade_manager_hook(self, player, self.view,
                                                                  selling, buying, selling_player)
                else:
                    interested, counter = self.trade_manager_ai_hook(player, selling, buying, self.round_num)

                if interested:
                    results.append((player, counter))

        return results

    def get_game_state(self):
        """Returns the internal game state"""
        return self._game

    def roll_dice(self, player: Player) -> Tuple[int, int, int, Optional[str]]:
        """Roll two dice and distribute resources to players."""
        self.view.display_board()
        d1, d2, total = self._game.roll_dice()
        msg = None
        if total == Game.ROBBER_DICE_NUM:
            # Perform robber actions
            # 1. All players must discard half of their resources
            for p in self._game.players:
                discard_count = p.calculate_discard_count()
                if discard_count > 0:
                    if p.is_human:
                        resources_to_discard = self.robber_discard_hook(p, self, self.view, discard_count, False)
                    else:
                        resources_to_discard = self.robber_discard_ai_hook(p, self, self.view, discard_count, False)
                    p.remove_resources(resources_to_discard)

            # 2. Player who rolled dice can move robber and collect resources
            result = self.handle_robber_action(player)
            if result is not None:
                stolen_player, stolen_resource = result
                msg = f"Stole 1 {stolen_resource.name.replace('_', ' ').title()} from {stolen_player.name}."
        return d1, d2, total, msg

    def handle_robber_action(self, player) -> Optional[Tuple[Player, Resource]]:
        """
        Handles moving the robber and stealing a resource for a given player,
        supporting both human and AI players.
        """
        # Choose the robber placement and target player
        if player.is_human:
            tile, steal_from = self.place_robber_hook(player, self, self.view)
        else:
            tile, steal_from = self.place_robber_ai_hook(player, self, self.view)

        # Move the robber
        self._game.set_robber(tile)

        # If there is a player to steal from, handle the discard
        if steal_from is not None:
            resource = steal_from.random_resource()
            self._game.trade_between_players(player, {}, steal_from, resource)

            return steal_from, next(iter(resource.keys()))

    def play_development_card(self, player: Player, card_type: DevelopmentCardType) -> str:
        """Plays the development card for a player and returns a descriptive message."""
        msg = f"{player.name} played {card_type.name.replace('_', ' ').title()}."

        if card_type == DevelopmentCardType.KNIGHT:
            # KNIGHT: Move the robber and steal one resource from a player adjacent to the new robber location
            stolen_player, stolen_resource = self.handle_robber_action(player) or (None, None)
            player.army_size += 1

            # If player has at least 3 knights and largest army is bigger than others, assign Largest Army
            if player.army_size >= 3:
                other_holder = next(
                    (p for p in self._game.players if p.has_largest_army and p != player),
                    None
                )
                if other_holder is None or player.army_size > other_holder.army_size:
                    if other_holder is not None:
                        other_holder.has_largest_army = False
                    player.has_largest_army = True
                    msg += " They now have the Largest Army!"

            if stolen_player and stolen_resource:
                msg += f" Stole 1 {stolen_resource.name.replace('_', ' ').title()} from {stolen_player.name}."

        elif card_type == DevelopmentCardType.ROAD_BUILDING:
            # ROAD BUILDING: Allows player to place two roads for free
            built_edges = []
            for _ in range(2):
                if self.get_available_edges(player):
                    if player.is_human:
                        edge = self.get_road_choice(player, self, self.view, None)
                    else:
                        edge = self.get_road_choice_ai(player, self, self.view, None)
                    self._game.try_build_road(player, edge, use_resources=False)
                    built_edges.append(edge)
            msg += f" Built {len(built_edges)} road(s)."

        elif card_type == DevelopmentCardType.YEAR_OF_PLENTY:
            # YEAR OF PLENTY: Player chooses two resources from the bank to add to their hand
            if player.is_human:
                resources = self.year_of_plenty_selection(self, self.view)
            else:
                resources = self.year_of_plenty_selection_ai(self)
            player.add_resources(resources)
            resource_list = ", ".join(
                f"{amt} {res.name.replace('_', ' ').title()}" for res, amt in resources.items() if amt > 0)
            msg += f" Took {resource_list} from the bank."

        elif card_type == DevelopmentCardType.MONOPOLY:
            # MONOPOLY: Player chooses a single resource type; all other players give all of that resource to the player
            if player.is_human:
                resource = self.monopoly_selection(self, self.view)
            else:
                resource = self.monopoly_selection_ai(self)
            total_taken = 0
            for p in self._game.players:
                if p == player:
                    continue
                amount = p.resources[resource]
                self.trade_between_players(player, {}, p, {resource: amount})
                total_taken += amount
            msg += f" Monopolised {total_taken} {resource.name.replace('_', ' ').title()} from other players."

        # Remove one card of this type from player's hand
        for card in player.development_cards:
            if card.card_type == card_type:
                player.development_cards.remove(card)
                break

        return msg

    # <editor-fold desc="Controller wrapper methods for model">

    def get_ports(self) -> List[Tuple[Port, Vertex, Vertex]]:
        """Returns the list of ports and their position"""
        return self._game.get_ports()

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

    def try_buy_development_card(self, player) -> Tuple[bool, str]:
        """Attempt to buy a development card for a player."""
        return self._game.try_buy_development_card(player)

    def get_available_edges(self, player: Player) -> List[Edge]:
        """Return a list of edges where the player can build a road."""
        return self._game.get_available_edges(player)

    def get_bank_resources(self) -> ResourceCount:
        """Returns the bank's resources"""
        return self._game.bank_resources

    def get_all_edges(self):
        """Return a list of all edges on the board."""
        return self._game.get_all_edges()

    def get_all_vertices(self):
        """Return a list of all vertices on the board."""
        return self._game.get_all_vertices()

    def get_development_deck(self):
        return self._game.development_deck

    def get_all_players(self):
        return self._game.players

    # </editor-fold>
