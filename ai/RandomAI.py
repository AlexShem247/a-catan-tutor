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

    def choose_build_action(self) -> Optional[Buildable]:
        return random.choice(list(Buildable))

    def pick_random_resources(self, resources: ResourceCount, num_resources: int) -> ResourceCount:
        # Flatten all available resources into a pool
        pool = [r for r, count in resources.items() for _ in range(count)]

        # Cap number of resources to what is actually available
        num_resources = min(num_resources, len(pool))
        if num_resources == 0:
            return {}

        chosen = random.sample(pool, num_resources)
        result: ResourceCount = {}
        for r in chosen:
            result[r] = result.get(r, 0) + 1
        return result

    def pick_trade_partner(self,
                           resources: ResourceCount,
                           available_players: List[Tuple[Player, Optional[ResourceCount]]],
                           estimated_cost: int
                           ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        if not available_players:
            return None

        # Keep only offers the AI can actually pay
        affordable_players = [
            (p, counter)
            for (p, counter) in available_players
            if counter is None or all(resources.get(res, 0) >= amt for res, amt in counter.items())
        ]

        if not affordable_players:
            return None

        # Pick randomly among valid options
        return random.choice(affordable_players)

    def decide_trade_strategy(
            self,
            player_resources: ResourceCount,
            cost: ResourceCount,
            round_num: int,
            bank_rate: int
    ) -> Tuple[Optional[Resource], Optional[Resource], int, int]:
        if not player_resources:
            return None, None, 0, 0

        # Only pick resources that the AI actually owns for selling
        tradable = [r for r, count in player_resources.items() if count > 0]
        if not tradable:
            return None, None, 0, 0

        buying = random.choice(list(Resource))
        selling = random.choice(tradable)

        if buying == selling:
            return None, None, 0, 0

        ai_buying_rate = random.randint(1, bank_rate)
        return buying, selling, bank_rate, ai_buying_rate

    def should_trade_with_player(self, ai_buying_rate: int, bank_rate: int) -> bool:
        return random.choice([True, False])

    def choose_random_settlement(self, available_vertices: List[Vertex]) -> Optional[Vertex]:
        return random.choice(available_vertices) if available_vertices else None

    def choose_random_road(self, available_edges: List[Edge]) -> Optional[Edge]:
        return random.choice(available_edges) if available_edges else None

    def choose_random_build_location(self,
                                     buildable_options: Dict[Buildable, List | bool],
                                     action: Buildable
                                     ) -> Optional[Vertex | Edge | bool]:
        if action not in buildable_options:
            return None

        value = buildable_options[action]

        if isinstance(value, list):
            return random.choice(value) if value else None

        return value if value else None

    def can_build_development_card(self, buildable_options: Dict[Buildable, List | bool]) -> bool:
        return bool(buildable_options.get(Buildable.DEVELOPMENT_CARD, False))

    def decide_dev_card_usage(self,
                              playable_cards: List[DevelopmentCardType],
                              used_dev_card: bool
                              ) -> Optional[DevelopmentCardType]:
        if playable_cards and not used_dev_card:
            return random.choice(playable_cards)
        return None

    def decide_robber_placement(self,
                                valid_hexes: List[HexTile],
                                current_player: Player,
                                get_players_on_hex_func,
                                has_resources_func
                                ) -> Tuple[HexTile, Optional[Player]]:
        hex_tile = random.choice(valid_hexes)

        players = [
            p for p in get_players_on_hex_func(hex_tile)
            if p != current_player and has_resources_func(p)
        ]

        target = random.choice(players) if players else None
        return hex_tile, target

    def decide_robber_discard(self,
                              player_resources: ResourceCount,
                              num_resources: int
                              ) -> ResourceCount:
        return self.pick_random_resources(player_resources, num_resources)

    def decide_year_of_plenty_resources(self,
                                        available_resources: ResourceCount
                                        ) -> ResourceCount:
        return self.pick_random_resources(available_resources, 2)

    def decide_monopoly_resource(self,
                                 available_resources: ResourceCount
                                 ) -> Resource:
        return random.choice(list(Resource))

    def trade_manager_ai_logic(
            self,
            player_resources: ResourceCount,
            selling: ResourceCount,
            buying: ResourceCount,
            round_num: int
    ) -> Tuple[bool, Optional[ResourceCount]]:

        # Check AI has enough resources to give
        for resource, amount in buying.items():
            if player_resources.get(resource, 0) < amount:
                return False, None  # Cannot trade what you don't have

        # Random accept/reject logic
        return random.choice([True, False]), None

    def decide_post_roll_dev_card_usage(self,
                                        playable_cards: List[DevelopmentCardType],
                                        used_dev_card: bool
                                        ) -> Optional[DevelopmentCardType]:
        if playable_cards and not used_dev_card:
            return random.choice(playable_cards)
        return None
