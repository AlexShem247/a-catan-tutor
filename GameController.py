from typing import List, Tuple, Optional, Dict

from game.Edge import Edge, EdgeDirection
from game.Game import Game, PlayerConfig
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex, Port, VertexDirection
from view.View import View
from config.view_constants import AI_DECISION_ANIMATION_DELAY, AI_DECISION_ANIMATION_DELAY_SIMULATION_MODE, \
    SHOW_AI_BUILT_LOCATIONS
from view.display_utils import resource_dict_to_str


class GameController:
    """Controls the flow of a Catan game using a pure Game model."""
    _game: Game
    round_num: int

    def __init__(self, game_players: PlayerConfig, simulation_players: PlayerConfig):
        self.view: View | None = None
        self.game_players = game_players
        self.simulation_players = simulation_players
        self.reset_game(True)

    def reset_game(self, game_mode: bool):
        """Reset the game to a fresh state and reset round counter."""
        self._game = Game(self.game_players if game_mode else self.simulation_players)
        self.round_num = 1
        if self.view is not None:
            self.view.ai_decision_animation_delay = (AI_DECISION_ANIMATION_DELAY if game_mode
                                                     else AI_DECISION_ANIMATION_DELAY_SIMULATION_MODE)

    def start_game(self):
        """Run initial placement, then loop turns until game over."""
        game_mode = self.view.display_start_screen()
        self.reset_game(game_mode)

        self.run_initial_placement()
        while not self._game.game_over:
            for player in self._game.players:
                if player.is_human:
                    self.make_round_move(player)
                else:
                    self.make_round_move_ai(player)

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
            if player.is_human:
                # Let human select position
                self.view.display_board(player, "Select a position to build your settlement")

                vertices = self._game.get_available_vertices(player, Buildable.SETTLEMENT, road_restriction=False)
                vertex: Vertex = self.view.draw_selectable_vertices(vertices)
                self.view.display_board()
            else:
                available_vertices = self._game.get_available_vertices(player, Buildable.SETTLEMENT,
                                                                       road_restriction=False)
                self.view.display_board()
                self.view.draw_selectable_vertices(available_vertices, disable_interactivity=True)
                self.view.display_board_ai(player, "Select a position to build your settlement")
                vertex = player.policy.select_settlement_location(player, available_vertices)
            self._game.try_build_settlement(player, vertex, use_resources=False,
                                            road_restriction=False, gain_resources=gain_resource)

            # Road
            if player.is_human:
                edge = self.get_road_choice(player, vertex)
            else:
                edge = self.get_road_choice_ai(player, vertex)
            self._game.try_build_road(player, edge, use_resources=False)

    def get_road_choice(self, player: Player, settlement: Optional[Vertex] = None) -> Edge:
        """Human selects an edge for initial road placement."""
        self.view.display_board(player, "Select a position to build your road")

        edges = self._game.get_available_edges(player)
        if settlement is not None:
            # Restrict edges to be directly connected to settlement
            edges = [edge for edge in edges if settlement in edge.vertices]

        edge: Edge = self.view.draw_selectable_edges(edges)

        return edge

    def get_road_choice_ai(self, player: Player, settlement: Optional[Vertex] = None) -> Optional[Edge]:
        if settlement is None:
            available_edges = self._game.get_available_edges(player)
        else:
            available_edges = self._game.get_buildable_edges_for_vertex(settlement)

        if not available_edges:
            return None

        self.view.display_board()
        self.view.draw_selectable_edges(available_edges, disable_interactivity=True)
        self.view.display_board_ai(player, "Select a position to build your road")

        return player.policy.select_road_location(player, available_edges)

    def trade_with_players(self, selling_player, selling, buying) -> List[Tuple[Player, Optional[ResourceCount]]]:
        """Sees which players are willing to trade"""
        results = []
        for player in self._game.players:
            if player != selling_player:
                if player.is_human:
                    interested, counter = self.view.display_trade_manager(player, selling, buying, selling_player)
                else:
                    # AI can only respond if it has enough resources to give
                    if player.can_afford(buying):
                        interested, counter = player.policy.respond_to_trade(player, selling, buying, self.round_num)
                    else:
                        interested, counter = False, None

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
                        resources_to_discard = self.view.show_resource_chooser(
                            p, discard_count, "The robber has been rolled!", p.resources)
                    else:
                        resources_to_discard = player.policy.select_discard_resources(player, discard_count)
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
            # Get available hex tiles (exclude current robber tile)
            available_hexes = [tile for tile in self._game.get_all_hexes() if not tile.robber]
            self.view.display_board(player, "Select a hex to move the robber")
            selected_hex: HexTile = self.view.draw_selectable_tiles(available_hexes)

            # Check for stealable players on adjacent vertices
            adjacent_player_buildings: List[Vertex] = [
                v for v in selected_hex.vertices
                if v.owner is not None and v.owner != player and any(v.owner.resources.values())
            ]

            if not adjacent_player_buildings:
                tile, steal_from = selected_hex, None
            else:
                self.view.display_board(player, "Select a player to steal from")
                selected_player_building: Vertex = self.view.draw_selectable_vertices(adjacent_player_buildings)
                selected_player = selected_player_building.owner

                tile, steal_from = selected_hex, selected_player

        else:
            valid_hexes = [
                hex_tile for hex_tile in self._game.get_all_hexes()
                if not hex_tile.robber
            ]
            tile, steal_from = player.policy.select_robber_target(
                player,
                valid_hexes,
                lambda h: self._game.get_players_on_hex(h),
                lambda p: any(v > 0 for v in p.resources.values())
            )

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
                if self._game.get_available_edges(player):
                    if player.is_human:
                        edge = self.get_road_choice(player, None)
                    else:
                        edge = self.get_road_choice_ai(player, None)
                    self._game.try_build_road(player, edge, use_resources=False)
                    built_edges.append(edge)
            msg += f" Built {len(built_edges)} road(s)."

        elif card_type == DevelopmentCardType.YEAR_OF_PLENTY:
            # YEAR OF PLENTY: Player chooses two resources from the bank to add to their hand
            if player.is_human:
                resources = self.view.show_resource_chooser(
                    player, 2, "Year of Plenty: choose any two resources from the bank.", self._game.bank_resources)
            else:
                resources = player.policy.select_year_of_plenty_resources(player)
            player.add_resources(resources)
            resource_list = ", ".join(
                f"{amt} {res.name.replace('_', ' ').title()}" for res, amt in resources.items() if amt > 0)
            msg += f" Took {resource_list} from the bank."

        elif card_type == DevelopmentCardType.MONOPOLY:
            # MONOPOLY: Player chooses a single resource type; all other players give all of that resource to the player
            if player.is_human:
                chosen = self.view.show_resource_chooser(
                    player, 1, "Monopoly: choose a resource to get from the other players.",
                    {res: 1 for res in Resource})
                # Extract the single Resource enum
                resource = next(iter(chosen.keys()))
            else:
                resource = player.policy.select_monopoly_resource(player)
            total_taken = 0
            for p in self._game.players:
                if p == player:
                    continue
                amount = p.resources[resource]
                self._game.trade_between_players(player, {}, p, {resource: amount})
                total_taken += amount
            msg += f" Monopolised {total_taken} {resource.name.replace('_', ' ').title()} from other players."

        # Remove one card of this type from player's hand
        for card in player.development_cards:
            if card.card_type == card_type:
                player.development_cards.remove(card)
                break

        return msg

    def make_round_move(self, player: Player):
        playable_cards = [card for card in player.development_cards if card.playable]
        played_dev_card = False
        if playable_cards:
            # Player can play card before rolling dice
            played_card = self.view.pre_roll(player)
            played_dev_card = played_card is not False

        d1, d2, total, _ = self.roll_dice(player)
        self.view.display_board_turn(player, (d1, d2, total), played_dev_card)

    def make_round_move_ai(self, player: Player):
        """AI turn: decides what to build, trades if helpful, then attempts the build."""
        used_dev_card = False
        card_msg = ""

        # Decide whether to play a development card
        card_to_play = player.policy.decide_dev_card_usage(player)
        if card_to_play:
            card_msg = self.play_development_card(player, card_to_play) + " (Pre-roll)"
            used_dev_card = True

        d1, d2, total, roll_msg = self.roll_dice(player)

        # 1. AI chooses what it wants to build
        chosen_action = player.policy.select_build_action(player)

        # 2. Try a bank trade if needed
        trade_msg = None
        if chosen_action is not None:
            trade_msg = self.ai_attempt_trade(player, chosen_action)

        # 3. Attempt the build
        build_msg = self.ai_attempt_build(player, chosen_action)

        # 4. Use playable development card if AI has one and hasn't used it
        if not used_dev_card:
            card_to_play = player.policy.decide_dev_card_usage(player)
            if card_to_play:
                card_msg = self.play_development_card(player, card_to_play) + " (Post-roll)"

        # 5. Display results
        msg = "\n".join(msg for msg in [trade_msg, build_msg, card_msg, roll_msg] if msg)
        self.view.display_board_turn_ai(player, (d1, d2, total), msg)

    def ai_attempt_trade(self, player: Player, desired_build: Buildable):
        """Try one bank trade to help the AI reach the resources needed for a desired build."""
        cost = Game.BUILDING_COST[desired_build]

        # Use pure logic to decide trade strategy
        buying_resource, selling_resource, bank_rate, ai_buying_rate = player.policy.determine_trade(
            player,
            cost,
            self.round_num,
            bank_rate=4  # Default bank rate
        )

        if buying_resource is None or selling_resource is None:
            return None

        buying = {r: 0 for r in Resource}
        buying[buying_resource] = 1

        # Case 1: Prefer player trade if better rate
        if player.policy.is_player_trade_better(player, ai_buying_rate, bank_rate):
            selling = player.policy.choose_resources(player, ai_buying_rate)
            if not selling:
                return None

            willing_players = self.trade_with_players(player, selling, buying)

            # Only keep offers the AI can actually pay
            affordable_players = [
                (p, counter) for (p, counter) in willing_players
                if counter is None or player.can_afford(counter)
            ]

            if not affordable_players:
                return None

            deal = player.policy.choose_trade_partner(player, affordable_players, ai_buying_rate)

            if deal is not None:
                buying_player, counter = deal

                if counter is not None:
                    selling = counter

                self._game.trade_between_players(player, selling, buying_player, buying)
                return (
                    f"{player.name} trades {resource_dict_to_str(selling)} with "
                    f"{buying_player.name} for {resource_dict_to_str(buying)} "
                    f"to work towards a {desired_build.name.replace('_', ' ').lower()}."
                )

        # Case 2: Bank trade
        selling = {r: 0 for r in Resource}
        selling[selling_resource] = bank_rate

        success = self._game.try_trade_with_bank(player, selling, buying)
        if not success:
            return None

        return (
            f"{player.name} trades {resource_dict_to_str(selling)} with the bank "
            f"for {resource_dict_to_str(buying)} to work towards a {desired_build.name.replace('_', ' ').lower()}."
        )

    def ai_attempt_build(self, player: Player, action: Buildable):
        """Attempt a build action and return the resulting message."""
        buildable = self._game.get_buildable_options(player)

        # Special handling for development card
        if action == Buildable.DEVELOPMENT_CARD:
            if buildable.get(Buildable.DEVELOPMENT_CARD, False):
                success, _ = self._game.try_buy_development_card(player)
                msg = f"{player.name} bought a development card."
                return msg
            else:
                return f"{player.name} chooses to do nothing."

        # For other actions, get location
        location = player.policy.select_build_location(player, buildable, action)

        if action not in buildable or location is None:
            return f"{player.name} chooses to do nothing."

        if action == Buildable.ROAD:
            success, msg = self._game.try_build_road(player, location)
        elif action == Buildable.SETTLEMENT:
            success, msg = self._game.try_build_settlement(player, location)
        elif action == Buildable.CITY:
            success, msg = self._game.try_build_city(player, location)
        else:
            msg = "AI attempted unknown action"

        if not SHOW_AI_BUILT_LOCATIONS:
            msg = msg.partition("built")[0] + f"built by {player.name}"

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

    def get_buildable_options(self, player: Player) -> Dict:
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
