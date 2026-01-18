import random
from typing import List, Optional, Tuple, Dict

from ai.AI import AI
from game.Edge import Edge
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import DevelopmentCardType, Buildable
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex


class RandomAI(AI):
    """Purely random Catan AI with no strategic logic."""

    def select_build_action(self, player: Player) -> Optional[Buildable]:
        """Randomly choose a build action for the AI."""
        return random.choice(list(Buildable))

    def choose_resources(self, player: Player, num_resources: int) -> ResourceCount:
        """Randomly select a number of resources from available ones."""
        # Flatten all available resources into a pool
        pool = [r for r, count in player.resources.items() for _ in range(count)]

        # Cap number of resources to what is actually available
        num_resources = min(num_resources, len(pool))
        if num_resources == 0:
            return {}

        chosen = random.sample(pool, num_resources)
        result: ResourceCount = {}
        for r in chosen:
            result[r] = result.get(r, 0) + 1
        return result

    def choose_trade_partner(self,
                             player: Player,
                             available_players: List[Tuple[Player, Optional[ResourceCount]]],
                             estimated_cost: int
                             ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        """Randomly select a trade partner from affordable offers."""
        if not available_players:
            return None

        # Keep only offers the AI can actually pay
        affordable_players = [
            (p, counter)
            for (p, counter) in available_players
            if counter is None or all(player.resources.get(res, 0) >= amt for res, amt in counter.items())
        ]

        if not affordable_players:
            return None

        # Pick randomly among valid options
        return random.choice(affordable_players)

    def determine_trade(self,
                        player: Player,
                        cost: ResourceCount,
                        round_num: int,
                        bank_rate: int
                        ) -> Tuple[Optional[Resource], Optional[Resource], int, int]:
        """Randomly decide which resource to buy/sell and at what rate."""
        if not player.resources:
            return None, None, 0, 0

        # Only pick resources that the AI actually owns for selling
        tradable = [r for r, count in player.resources.items() if count > 0]
        if not tradable:
            return None, None, 0, 0

        buying = random.choice(list(Resource))
        selling = random.choice(tradable)

        if buying == selling:
            return None, None, 0, 0

        ai_buying_rate = random.randint(1, bank_rate)
        return buying, selling, bank_rate, ai_buying_rate

    def is_player_trade_better(self, player: Player, ai_buying_rate: int, bank_rate: int) -> bool:
        """Randomly decide whether a player trade is preferable to bank trade."""
        return random.choice([True, False])

    def select_settlement_location(self, player: Player, available_vertices: List[Vertex]) -> Optional[Vertex]:
        """Randomly select a settlement location from available vertices."""
        return random.choice(available_vertices) if available_vertices else None

    def select_road_location(self, player: Player, available_edges: List[Edge]) -> Optional[Edge]:
        """Randomly select a road location from available edges."""
        return random.choice(available_edges) if available_edges else None

    def select_build_location(self,
                              player: Player,
                              buildable_options: Dict[Buildable, List | bool],
                              action: Buildable
                              ) -> Optional[Vertex | Edge | bool]:
        """Randomly pick a location for a chosen build action."""
        if action not in buildable_options:
            return None

        value = buildable_options[action]

        if isinstance(value, list):
            return random.choice(value) if value else None

        return value if value else None

    def decide_dev_card_usage(self, player: Player) -> Optional[DevelopmentCardType]:
        """Randomly choose a playable development card to use, if any."""
        playable_cards = [c.card_type for c in player.development_cards if c.playable]

        if playable_cards:
            return random.choice(playable_cards)
        return None

    def select_robber_target(self,
                             player: Player,
                             valid_hexes: List[HexTile],
                             get_players_on_hex_func,
                             has_resources_func
                             ) -> Tuple[HexTile, Optional[Player]]:
        """Randomly select a hex for the robber and a victim player, if any."""
        hex_tile = random.choice(valid_hexes)

        players = [
            p for p in get_players_on_hex_func(hex_tile)
            if p != player and has_resources_func(p)
        ]

        target = random.choice(players) if players else None
        return hex_tile, target

    def select_discard_resources(self, player: Player, num_resources: int) -> ResourceCount:
        """Randomly choose resources to discard when required."""
        return self.choose_resources(player, num_resources)

    def select_year_of_plenty_resources(self, player: Player) -> ResourceCount:
        """Randomly pick two resources for a Year of Plenty card."""
        return self.choose_resources(player, 2)

    def select_monopoly_resource(self, player: Player) -> Resource:
        """Randomly pick a resource to monopolise."""
        return random.choice(list(Resource))

    def respond_to_trade(self,
                         player: Player,
                         selling: ResourceCount,
                         buying: ResourceCount,
                         round_num: int
                         ) -> Tuple[bool, Optional[ResourceCount]]:
        """Randomly accept or reject a trade if affordable."""
        # Check AI has enough resources to give
        for resource, amount in buying.items():
            if player.resources.get(resource, 0) < amount:
                return False, None  # Cannot trade what you don't have

        # Random accept/reject logic
        return random.choice([True, False]), None
