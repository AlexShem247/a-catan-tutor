from collections import defaultdict
from random import randint
from typing import List, Optional, Dict

from game.Board import Board
from game.Edge import Edge, EdgeDirection
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.PlayerAssets import Buildable, DevelopmentDeck
from game.Resources import Resource, ResourceCount
from game.Vertex import Building, Vertex, VertexDirection, Port


class Game:
    # Resource cost for each building type
    BUILDING_COST: Dict[Buildable, ResourceCount] = {
        Buildable.ROAD: {Resource.WOOD: 1, Resource.BRICK: 1},
        Buildable.SETTLEMENT: {
            Resource.WOOD: 1, Resource.BRICK: 1, Resource.SHEEP: 1, Resource.WHEAT: 1
        },
        Buildable.CITY: {Resource.ORE: 3, Resource.WHEAT: 2},
        Buildable.DEVELOPMENT_CARD: {Resource.ORE: 1, Resource.WOOD: 1, Resource.WHEAT: 1}
    }

    BANK_INITIAL_RESOURCES: ResourceCount = {
        Resource.WOOD: 19, Resource.BRICK: 19, Resource.SHEEP: 19, Resource.WHEAT: 19, Resource.ORE: 19,
    }

    VICTORY_POINTS_TO_WIN = 10
    ROBBER_DICE_NUM = 7

    def __init__(self, human_player_one: bool = True):
        self.bank_resources = self.BANK_INITIAL_RESOURCES.copy()
        self.players: List[Player] = [Player(human_player_one if p == PlayerNumber.P1
                                             else False, p, bank_resources=self.bank_resources) for p in PlayerNumber]
        self._board = Board()
        self.development_deck = DevelopmentDeck()
        self.game_over = False

    def can_afford(self, player: Player, building_type: Buildable) -> bool:
        """Check if the player has enough resources to build the given type."""
        cost = self.BUILDING_COST[building_type]
        return all(player.resources.get(res, 0) >= amt for res, amt in cost.items())

    def roll_dice(self) -> tuple[int, int, int]:
        """Roll two dice and distribute resources to players."""
        d1, d2 = randint(1, 6), randint(1, 6)
        total = d1 + d2

        # 1. Aggregate production demands per player per resource
        production: Dict[Player, Dict[Resource, int]] = defaultdict(lambda: defaultdict(int))

        tiles = self._board.production_to_hex.get(total, [])
        for tile in tiles:
            if tile.robber:
                continue  # Robber blocks production

            for vertex in tile.vertices:
                if vertex.owner is not None:
                    amount = vertex.building.get_resource_yield()
                    production[vertex.owner][tile.resource] += amount

        # 2. Aggregate total demand per resource
        total_needed: Dict[Resource, int] = defaultdict(int)
        for res_map in production.values():
            for res, amount in res_map.items():
                total_needed[res] += amount

        # 3. Distribute only if the bank can satisfy the FULL amount
        for res, needed in total_needed.items():
            if self.bank_resources[res] < needed:
                # Not enough -> nobody gets this resource
                for res_map in production.values():
                    res_map.pop(res, None)

        # 4. Apply distribution
        for player, res_map in production.items():
            player.add_resources(res_map)

        return d1, d2, total

    def get_buildable_options(self, player: Player) -> dict:
        """
        Returns dict of possible Buildable actions and valid board locations.
        Empty list if player cannot afford or no legal space.
        """
        options = {Buildable.ROAD: [], Buildable.SETTLEMENT: [], Buildable.CITY: [], Buildable.DEVELOPMENT_CARD: False}

        # Roads
        if self.can_afford(player, Buildable.ROAD) and len(player.roads) < Buildable.ROAD.max_on_board:
            options[Buildable.ROAD] = self.get_available_edges(player)

        # Settlements
        if self.can_afford(player, Buildable.SETTLEMENT) and len(
                player.settlements) < Buildable.SETTLEMENT.max_on_board:
            options[Buildable.SETTLEMENT] = self.get_available_vertices(player, Buildable.SETTLEMENT)

        # Cities
        if self.can_afford(player, Buildable.CITY) and len(player.cities) < Buildable.CITY.max_on_board:
            options[Buildable.CITY] = self.get_available_vertices(player, Buildable.CITY)

        # Development Cards
        if self.can_afford(player, Buildable.DEVELOPMENT_CARD) and not self.development_deck.empty():
            options[Buildable.DEVELOPMENT_CARD] = True

        return options

    @staticmethod
    def get_trade_rate(player: Player, resource: Resource) -> int:
        """Return the best trade rate for 'player' when selling 'resource'."""
        player_ports = player.get_ports()

        # Try specific 2:1 port first
        try:
            specific_port = Port[resource.name]
        except KeyError:
            specific_port = None

        if specific_port is not None and specific_port in player_ports:
            return 2

        if Port.THREE_TO_ONE in player_ports:
            return 3

        return 4

    def try_trade_with_bank(
            self, player: Player, selling: ResourceCount,
            buying: ResourceCount, use_resources: bool = True
    ) -> bool:
        """Attempt a bank trade using correct port discounts (2:1, 3:1, 4:1)."""

        # Filter zeros
        selling_nonzero = {r: amt for r, amt in selling.items() if amt > 0}
        buying_nonzero = {r: amt for r, amt in buying.items() if amt > 0}

        # Must sell and buy exactly ONE resource type
        if len(selling_nonzero) != 1 or len(buying_nonzero) != 1:
            return False

        selling_resource, selling_amount = next(iter(selling_nonzero.items()))
        buying_resource, buying_amount = next(iter(buying_nonzero.items()))

        # Calculate cost
        total_cost = self.get_trade_rate(player, selling_resource) * buying_amount

        # Validate the selling amount
        if selling_nonzero.get(selling_resource, 0) < total_cost:
            return False

        # Execute trade
        if use_resources:
            player.remove_resource(selling_resource, total_cost)
            player.add_resource(buying_resource, buying_amount)

        return True

    def try_build_settlement(
            self,
            player: Player,
            vertex: Vertex,
            build: bool = True,
            use_resources: bool = True,
            road_restriction: bool = True,
            gain_resources: bool = False,
    ) -> tuple[bool, str]:
        """Attempt to build a settlement with rules enforced."""
        if vertex.owner is not None or vertex.building is not None:
            if vertex.owner:
                return False, f"Vertex already owned by {vertex.owner.name}"
            return False, f"Vertex already has a building: {vertex.building}"

        for edge in vertex.edges:
            for neighbor in edge.vertices:
                if neighbor is not vertex and neighbor.building is not None:
                    return False, "Adjacent vertex already has a building"

        if road_restriction and not any(edge.owner == player for edge in vertex.edges):
            return False, "Settlement must be connected to one of your roads"

        if build:
            Board.build_settlement(vertex, player)
            if use_resources:
                player.remove_resources(Game.BUILDING_COST[Buildable.SETTLEMENT])
            if gain_resources:
                # Add resources from neighbouring tiles
                for tile in vertex.hexes:
                    if tile.resource is not None:
                        player.add_resource(tile.resource, 1)

            self.update_best_opponent_victory_points()

        return True, f"Settlement built at {vertex}"

    def try_build_city(
            self,
            player: Player,
            vertex: Vertex,
            build: bool = True,
            use_resources: bool = True
    ) -> tuple[bool, str]:
        """Attempt to upgrade a settlement to a city."""
        if vertex.owner != player:
            return False, f"Vertex is owned by {vertex.owner.name if vertex.owner else 'nobody'}"
        if vertex.building != Building.SETTLEMENT:
            return False, "Vertex does not have a settlement to upgrade"

        if build:
            Board.build_city(vertex, player)
            if use_resources:
                player.remove_resources(Game.BUILDING_COST[Buildable.CITY])

            self.update_best_opponent_victory_points()

        return True, f"City built at {vertex}"

    def try_build_road(
            self,
            player: Player,
            edge: Edge,
            on_vertex: Optional[Vertex] = None,
            build: bool = True,
            use_resources: bool = True
    ) -> tuple[bool, str]:
        """Attempt to build a road with rules enforced."""

        def _finalise() -> tuple[bool, str]:
            if build:
                Board.build_road(edge, player)
                if use_resources:
                    player.remove_resources(Game.BUILDING_COST[Buildable.ROAD])

                # Recalculate longest road length
                player.longest_road_length = Board.calculate_longest_road_length(player.roads)

                # Update the longest road ownership for ALL players
                self._update_longest_road_ownership()

            return True, f"Road built at {edge}"

        if edge.owner is not None:
            return False, f"Edge already owned by {edge.owner.name}"

        # Special case: must connect to specified vertex
        if on_vertex is not None:
            if edge not in on_vertex.edges:
                return False, f"Edge must connect to the specified vertex at {on_vertex}"
            return _finalise()

        # Standard rules: adjacent to player's settlement
        if any(v.owner == player for v in edge.vertices):
            return _finalise()

        # Or connected to player's road WITHOUT passing through opponent settlement
        for v in edge.vertices:
            # If vertex is occupied by another player, it blocks road continuation
            if v.owner is not None and v.owner != player:
                continue

            for connected_edge in v.edges:
                if connected_edge is not edge and connected_edge.owner == player:
                    return _finalise()

        v_info = ", ".join(v.owner.name if v.owner else "EMPTY" for v in edge.vertices)
        return False, f"Cannot build road: no adjacent settlement or connecting road. Vertices: {v_info}"

    def _update_longest_road_ownership(self) -> None:
        """Update the longest road ownership across all players."""
        # Recalculate for all players (in case roads were broken by settlements)
        for p in self.players:
            p.longest_road_length = Board.calculate_longest_road_length(p.roads)

        # Find the player(s) with the longest road
        max_length = max(p.longest_road_length for p in self.players)

        # Longest road must be at least 5 to qualify
        if max_length < 5:
            # No one qualifies for longest road
            for p in self.players:
                p.has_longest_road = False
            return

        # Check if there's a tie
        players_with_max = [p for p in self.players if p.longest_road_length == max_length]

        if len(players_with_max) == 1:
            # Clear longest road from all players first
            for p in self.players:
                p.has_longest_road = False
            # Award to the single player with the longest road
            players_with_max[0].has_longest_road = True
        else:
            # Tie case: keep with current holder if they're tied, otherwise no one gets it
            current_holder = next((p for p in self.players if p.has_longest_road), None)
            if current_holder and current_holder.longest_road_length == max_length:
                # Current holder keeps it
                pass
            else:
                # No current holder or they don't have max length - no one gets it
                for p in self.players:
                    p.has_longest_road = False

        self.update_best_opponent_victory_points()

    def update_best_opponent_victory_points(self) -> None:
        """Update best_opponents_victory_point for all players."""
        # Calculate victory points for all players
        player_vp = {player: player.calc_victory_points()[0] for player in self.players}

        # For each player, find the highest VP among their opponents
        for player in self.players:
            opponent_vps = [vp for p, vp in player_vp.items() if p != player]
            player.best_opponents_victory_point = max(opponent_vps) if opponent_vps else 0

            if player.calc_victory_points()[1] >= Game.VICTORY_POINTS_TO_WIN:
                # Player has won
                self.game_over = True

    def get_row_hexes(self, r: int) -> List[HexTile]:
        """Return a list of hex tiles in row r, sorted by their q coordinate."""
        return sorted([h for h in self._board.hexes if h.r == r], key=lambda h: h.q)

    def get_hex_tile(self, q: int, r: int) -> Optional[HexTile]:
        """Return the HexTile object for hex (q,r)."""
        return self._board.hex_map.get((q, r))

    def get_vertex(self, q: int, r: int, corner_index: VertexDirection) -> Optional[Vertex]:
        """Return the Vertex object for hex (q,r) at corner_index 0-5."""
        return self._board.vertex_map.get((q, r, corner_index))

    def get_edge(self, q: int, r: int, edge_index: EdgeDirection) -> Optional[Edge]:
        """Return the Edge object for hex (q,r) at edge_index 0-5."""
        return self._board.edge_map.get((q, r, edge_index))

    def get_available_vertices(self, player: Player, building_type: Buildable, road_restriction: bool = True) -> \
            List[Vertex]:
        """Return a list of vertices where the player can build a settlement or city."""
        available = []
        if building_type == Buildable.SETTLEMENT:
            for vertex in self._board.vertices:
                success, _ = self.try_build_settlement(player, vertex, build=False, road_restriction=road_restriction)
                if success:
                    available.append(vertex)
        elif building_type == Buildable.CITY:
            for vertex in player.settlements:
                success, _ = self.try_build_city(player, vertex, build=False)
                if success:
                    available.append(vertex)
        return available

    def get_available_edges(self, player: Player) -> List[Edge]:
        """Return a list of edges where the player can build a road."""
        available = []
        for edge in self._board.edges:
            success, _ = self.try_build_road(player, edge, build=False)
            if success:
                available.append(edge)
        return available

    def get_buildable_edges_for_vertex(self, vertex: Vertex) -> List[Edge]:
        """Return edges adjacent to a vertex where the player can build a road."""
        return [e for e in vertex.edges if self.try_build_road(vertex.owner, e, build=False)[0]]

    @staticmethod
    def trade_between_players(player: Player, selling: ResourceCount,
                              buying_player: Player, buying: ResourceCount):
        """Execute a trade of resources between two players."""

        # Remove resources from the selling player
        for resource, amount in selling.items():
            player.resources[resource] -= amount

        # Add those resources to the buying player
        for resource, amount in selling.items():
            buying_player.resources[resource] += amount

        # Remove resources from the buying player
        for resource, amount in buying.items():
            buying_player.resources[resource] -= amount

        # Add those resources to the selling player
        for resource, amount in buying.items():
            player.resources[resource] += amount

    def set_robber(self, tile: HexTile):
        """Replace the robber tile with 'tile'"""
        self._board.robber_position.robber = False
        self._board.robber_position = tile
        self._board.robber_position.robber = True

    @staticmethod
    def get_players_on_hex(hex_tile: HexTile) -> List[Player]:
        """Return a list of players who own a settlement or city on the given hex tile."""
        return list(set([v.owner for v in hex_tile.vertices if v.owner is not None]))

    def get_all_hexes(self) -> List[HexTile]:
        """Return a list of all hex tiles on the board."""
        return self._board.hexes

    def get_all_vertices(self) -> List[Vertex]:
        """Return a list of all vertices on the board."""
        return self._board.vertices

    def get_all_edges(self) -> List[Edge]:
        """Return a list of all edges on the board."""
        return self._board.edges

    def get_hex_tiles_with_players(self):
        """Return a list of hex tiles that have at least one player on them."""
        return [h for h in self._board.hexes if Game.get_players_on_hex(h)]

    def get_robber_tile(self) -> HexTile:
        """Returns the robber's current position"""
        return self._board.robber_position

    def try_buy_development_card(self, player) -> tuple[bool, str]:
        """Attempt to buy a development card for a player."""
        if self.development_deck.empty():
            return False, "There are no more development cards"

        card = self.development_deck.draw()
        player.development_cards.append(card)
        player.remove_resources(Game.BUILDING_COST[Buildable.DEVELOPMENT_CARD])

        return True, f"You got a {card.card_type.name.replace('_', ' ').capitalize()} card!"
