import random
from math import ceil
from typing import Optional, List, Tuple, Dict

from ai.AI import AI
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Player import Player
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from game.Edge import Edge
from game.HexTile import HexTile


class BasicAI(AI):
    """Baseline Catan AI using mostly random decisions with simple heuristic bias."""

    TOTAL_ROUNDS = 20
    MAX_RATIO = 4
    HUMAN_BIAS_WEIGHT, AI_BIAS_WEIGHT = 1.2, 1.0

    ACCEPT_PROBABILITY_BY_OVERCOST = {
        0: 1.0,
        1: 0.4,
        2: 0.1,
    }

    def _get_required_trade_ratio(self, round_num: int) -> int:
        """Compute AI's required trade ratio based on the round number."""
        return ceil(1 + (round_num - 1) / self.TOTAL_ROUNDS * (self.MAX_RATIO - 1))

    def select_build_action(self, player: Player) -> Optional[Buildable]:
        """Select a build action based on weighted preferences."""
        action_weights = {
            Buildable.CITY: 10,
            Buildable.SETTLEMENT: 8,
            Buildable.DEVELOPMENT_CARD: 6,
            Buildable.ROAD: 3,
            None: 4,
        }

        weighted_actions = []
        for action in Buildable:
            weighted_actions.extend([action] * action_weights[action])
        weighted_actions.extend([None] * action_weights[None])

        return random.choice(weighted_actions)

    def choose_resources(self, player: Player, num_resources: int) -> ResourceCount:
        """Randomly select a number of resources from available resources."""
        total = sum(player.resources.values())
        if total < num_resources:
            return {}

        pool = [
            resource
            for resource, count in player.resources.items()
            for _ in range(count)
        ]

        chosen = random.sample(pool, num_resources)

        result: ResourceCount = {}
        for resource in chosen:
            result[resource] = result.get(resource, 0) + 1

        return result

    def _resource_cost(self, resources: ResourceCount) -> int:
        """Compute total quantity of resources in a ResourceCount dict."""
        return sum(resources.values())

    def _player_trade_weight(self, player: Player) -> float:
        """Return selection weight for a player in trade decisions."""
        return self.HUMAN_BIAS_WEIGHT if player.is_human else self.AI_BIAS_WEIGHT

    def _accept_probability(self, over_cost: int) -> float:
        """Return probability of accepting a counteroffer above estimated cost."""
        if over_cost <= 0:
            return 1.0
        return self.ACCEPT_PROBABILITY_BY_OVERCOST.get(over_cost, 0.0)

    def _weighted_pick(self, players: List[Player]) -> Player:
        """Select a player randomly, weighted by human/AI bias."""
        weights = [self._player_trade_weight(p) for p in players]
        return random.choices(players, weights=weights, k=1)[0]

    def choose_trade_partner(self,
                             player: Player,
                             available_players: List[Tuple[Player, Optional[ResourceCount]]],
                             estimated_cost: int
                             ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        """Select a trade partner or counteroffer from offers the AI can afford."""

        if not available_players:
            return None

        # Prefer original trades
        originals = [(p, c) for (p, c) in available_players if c is None]
        if originals:
            players = [p for (p, _) in originals]
            chosen = self._weighted_pick(players)
            return chosen, None

        # Evaluate counteroffers
        counters_with_cost = [
            (p, c, self._resource_cost(c))
            for (p, c) in available_players
            if c is not None
        ]

        if not counters_with_cost:
            return None

        # Find minimum cost counteroffer
        min_cost = min(cost for (_, _, cost) in counters_with_cost)
        cheapest = [(p, c, cost) for (p, c, cost) in counters_with_cost if cost == min_cost]

        # Acceptance probability
        over_cost = min_cost - estimated_cost
        if random.random() > self._accept_probability(over_cost):
            return None

        # Bias toward human if tied
        players = [p for (p, _, _) in cheapest]
        chosen_player = self._weighted_pick(players)

        # Return the chosen player's counteroffer
        for p, c, _ in cheapest:
            if p == chosen_player:
                return p, c

        return None

    def _determine_missing_resources(self,
                                     player_resources: ResourceCount,
                                     cost: ResourceCount
                                     ) -> Dict[Resource, int]:
        """Compute which resources the player lacks for a desired build."""
        return {
            r: needed - player_resources.get(r, 0)
            for r, needed in cost.items()
            if player_resources.get(r, 0) < needed
        }

    def _determine_spare_tradable_resources(self,
                                            player_resources: ResourceCount,
                                            cost: ResourceCount,
                                            required_rate: int
                                            ) -> Dict[Resource, int]:
        """Identify spare resources the player can trade without affecting builds."""
        return {
            r: player_resources.get(r, 0)
            for r in Resource
            if r not in cost and player_resources.get(r, 0) >= required_rate
        }

    def _select_buying_resource(self, missing_resources: Dict[Resource, int]) -> Optional[Resource]:
        """Pick a missing resource to buy."""
        if not missing_resources:
            return None
        return random.choice(list(missing_resources.keys()))

    def _select_selling_resource(self, spare_resources: Dict[Resource, int]) -> Optional[Resource]:
        """Pick a spare resource to sell."""
        if not spare_resources:
            return None
        return random.choice(list(spare_resources.keys()))

    def determine_trade(self,
                        player: Player,
                        cost: ResourceCount,
                        round_num: int,
                        bank_rate: int
                        ) -> Tuple[Optional[Resource], Optional[Resource], int, int]:
        """Determine trade strategy: what to buy, what to sell, and trade ratios."""
        missing = self._determine_missing_resources(player.resources, cost)
        if not missing:
            return None, None, 0, 0

        spare = self._determine_spare_tradable_resources(player.resources, cost, bank_rate)
        if not spare:
            return None, None, 0, 0

        buying_resource = self._select_buying_resource(missing)
        selling_resource = self._select_selling_resource(spare)
        ai_buying_rate = self._get_required_trade_ratio(round_num)

        return buying_resource, selling_resource, bank_rate, ai_buying_rate

    def is_player_trade_better(self, player: Player, ai_buying_rate: int, bank_rate: int) -> bool:
        """Check if a player trade is preferable to bank trade."""
        return ai_buying_rate < bank_rate

    def select_settlement_location(self, player: Player, available_vertices: List[Vertex]) -> Optional[Vertex]:
        """Select a settlement location from available vertices."""
        return random.choice(available_vertices) if available_vertices else None

    def select_road_location(self, player: Player, available_edges: List[Edge]) -> Optional[Edge]:
        """Select a road location from available edges."""
        return random.choice(available_edges) if available_edges else None

    def select_build_location(self,
                              player: Player,
                              buildable_options: Dict[Buildable, List | bool],
                              action: Buildable
                              ) -> Optional[Vertex | Edge | bool]:
        """Select a build location or option for a given build action."""
        if action not in buildable_options:
            return None

        value = buildable_options[action]

        # Development card returns a boolean, not a location list
        if action == Buildable.DEVELOPMENT_CARD:
            return value if value else None

        # For other actions, expect a list of locations
        if isinstance(value, list) and value:
            return random.choice(value)

        return None

    def decide_dev_card_usage(self, player: Player) -> Optional[DevelopmentCardType]:
        """Decide which playable development card to use, if any."""
        playable_cards = [c.card_type for c in player.development_cards if c.playable]

        if playable_cards and random.random() < 0.3:
            return random.choice(playable_cards)
        return None

    def select_robber_target(self,
                             player: Player,
                             valid_hexes: List[HexTile],
                             get_players_on_hex_func,
                             has_resources_func
                             ) -> Tuple[HexTile, Optional[Player]]:
        """Select a hex for the robber and a player to steal from, if any."""
        # Filter hexes that have at least one stealable opponent
        stealable_hexes = [
            hex_tile for hex_tile in valid_hexes
            if any(
                p != player and has_resources_func(p)
                for p in get_players_on_hex_func(hex_tile)
            )
        ]

        if stealable_hexes:
            # Pick a random hex where stealing is possible
            hex_tile = random.choice(stealable_hexes)

            stealable_players = [
                p for p in get_players_on_hex_func(hex_tile)
                if p != player and has_resources_func(p)
            ]

            target_player = random.choice(stealable_players)
            return hex_tile, target_player

        # Otherwise, move robber to any other valid hex (no stealing)
        hex_tile = random.choice(valid_hexes)
        return hex_tile, None

    def select_discard_resources(self, player: Player, num_resources: int) -> ResourceCount:
        """Select resources to discard when required."""
        return self.choose_resources(player, num_resources)

    def select_year_of_plenty_resources(self, player: Player) -> ResourceCount:
        """Select two resources for a Year of Plenty card."""
        return self.choose_resources(player, 2)

    def select_monopoly_resource(self, player: Player) -> Resource:
        """Select a resource for a Monopoly card."""
        res_dict = self.choose_resources(player, 1)
        return next(iter(res_dict.keys()))

    def respond_to_trade(self,
                         player: Player,
                         selling: ResourceCount,
                         buying: ResourceCount,
                         round_num: int
                         ) -> Tuple[bool, Optional[ResourceCount]]:
        """Decide whether to accept or counter a trade, assuming AI can afford it."""

        # 1. AI expected trade ratio for this round
        required_ratio = self._get_required_trade_ratio(round_num)

        # 2. Compute totals
        total_selling = sum(selling.values())  # What AI would receive
        total_buying = sum(buying.values())    # What AI would give

        over_cost = total_selling - required_ratio * total_buying
        over_cost_int = int(abs(over_cost))

        # 3. Decide to accept probabilistically
        prob = self.ACCEPT_PROBABILITY_BY_OVERCOST.get(over_cost_int, 0.0)
        if random.random() < prob:
            return True, None  # Accept trade as-is

        # 4. Generate a simple counteroffer if AI wants more
        if total_selling < required_ratio * total_buying:
            missing = required_ratio * total_buying - total_selling
            # Increase the quantity of the most valuable offered resource
            resource_to_increase = max(selling, key=lambda r: selling[r])
            counter_selling = selling.copy()
            counter_selling[resource_to_increase] += int(missing)
            return True, counter_selling

        # 5. Otherwise, reject
        return False, None
