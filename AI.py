import random
from math import ceil
from typing import Optional, List, Tuple, Dict
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Player import Player
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from game.Edge import Edge
from game.HexTile import HexTile


class AI:
    """Pure AI decision-making logic without dependencies on GameController or View."""

    TOTAL_ROUNDS = 20
    MAX_RATIO = 4
    HUMAN_BIAS_WEIGHT, AI_BIAS_WEIGHT = 1.2, 1.0

    ACCEPT_PROBABILITY_BY_OVERCOST = {
        0: 1.0,
        1: 0.4,
        2: 0.1,
    }

    @staticmethod
    def get_required_trade_ratio(round_num: int) -> int:
        """Return the AI's required trade ratio for the current round."""
        return ceil(1 + (round_num - 1) / AI.TOTAL_ROUNDS * (AI.MAX_RATIO - 1))

    @staticmethod
    def choose_build_action() -> Buildable | str:
        """Choose a desired build action for the AI based on weighted preferences."""
        action_weights = {
            Buildable.CITY: 10,
            Buildable.SETTLEMENT: 8,
            Buildable.DEVELOPMENT_CARD: 6,
            Buildable.ROAD: 3,
            "NOTHING": 4,
        }

        weighted_actions = []
        for action in Buildable:
            weighted_actions.extend([action] * action_weights[action])
        weighted_actions.extend(["NOTHING"] * action_weights["NOTHING"])

        return random.choice(weighted_actions)

    @staticmethod
    def pick_random_resources(resources: ResourceCount, num_resources: int) -> ResourceCount:
        """Randomly pick num_resources resource units from the given resource dict."""
        total = sum(resources.values())
        if total < num_resources:
            return {}

        pool = [
            resource
            for resource, count in resources.items()
            for _ in range(count)
        ]

        chosen = random.sample(pool, num_resources)

        result: ResourceCount = {}
        for resource in chosen:
            result[resource] = result.get(resource, 0) + 1

        return result

    @staticmethod
    def resource_cost(resources: ResourceCount) -> int:
        """Calculate total resource cost from a ResourceCount dictionary."""
        return sum(resources.values())

    @staticmethod
    def player_trade_weight(player: Player) -> float:
        """Return selection weight for a player in trade decisions."""
        return AI.HUMAN_BIAS_WEIGHT if player.is_human else AI.AI_BIAS_WEIGHT

    @staticmethod
    def accept_probability(over_cost: int) -> float:
        """Probability of accepting a counteroffer exceeding estimated cost."""
        if over_cost <= 0:
            return 1.0
        return AI.ACCEPT_PROBABILITY_BY_OVERCOST.get(over_cost, 0.0)

    @staticmethod
    def weighted_pick(players: List[Player]) -> Player:
        """Pick a player based on weights."""
        weights = [AI.player_trade_weight(p) for p in players]
        return random.choices(players, weights=weights, k=1)[0]

    @staticmethod
    def pick_trade_partner(
            available_players: List[Tuple[Player, Optional[ResourceCount]]],
            estimated_cost: int
    ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        """Decide which trade to follow through with. Returns (Player, counteroffer) or None."""

        if not available_players:
            return None

        # Prefer original trades
        originals = [(p, c) for (p, c) in available_players if c is None]
        if originals:
            players = [p for (p, _) in originals]
            chosen = AI.weighted_pick(players)
            return chosen, None

        # Evaluate Counteroffers
        counters_with_cost = [
            (p, c, AI.resource_cost(c))
            for (p, c) in available_players
            if c is not None
        ]

        if not counters_with_cost:
            return None

        # Find minimum cost
        min_cost = min(cost for (_, _, cost) in counters_with_cost)
        cheapest = [(p, c, cost) for (p, c, cost) in counters_with_cost if cost == min_cost]

        # Acceptance probability
        over_cost = min_cost - estimated_cost
        if random.random() > AI.accept_probability(over_cost):
            return None

        # Bias toward human if tied
        players = [p for (p, _, _) in cheapest]
        chosen_player = AI.weighted_pick(players)

        # Retrieve that player's counteroffer
        for p, c, _ in cheapest:
            if p == chosen_player:
                return p, c

        return None

    @staticmethod
    def determine_missing_resources(
            player_resources: ResourceCount,
            cost: ResourceCount
    ) -> Dict[Resource, int]:
        """Determine which resources are missing for a build."""
        return {
            r: needed - player_resources.get(r, 0)
            for r, needed in cost.items()
            if player_resources.get(r, 0) < needed
        }

    @staticmethod
    def determine_spare_tradable_resources(
            player_resources: ResourceCount,
            cost: ResourceCount,
            required_rate: int
    ) -> Dict[Resource, int]:
        """Determine spare resources that can be traded away."""
        return {
            r: player_resources.get(r, 0)
            for r in Resource
            if r not in cost and player_resources.get(r, 0) >= required_rate
        }

    @staticmethod
    def select_buying_resource(missing_resources: Dict[Resource, int]) -> Optional[Resource]:
        """Select a resource to buy from missing resources."""
        if not missing_resources:
            return None
        return random.choice(list(missing_resources.keys()))

    @staticmethod
    def select_selling_resource(spare_resources: Dict[Resource, int]) -> Optional[Resource]:
        """Select a resource to sell from spare resources."""
        if not spare_resources:
            return None
        return random.choice(list(spare_resources.keys()))

    @staticmethod
    def decide_trade_strategy(
            player_resources: ResourceCount,
            cost: ResourceCount,
            round_num: int,
            bank_rate: int
    ) -> Tuple[Optional[Resource], Optional[Resource], int, int]:
        """Decide trade strategy: what to buy, what to sell, and rates."""
        missing = AI.determine_missing_resources(player_resources, cost)
        if not missing:
            return None, None, 0, 0

        spare = AI.determine_spare_tradable_resources(player_resources, cost, bank_rate)
        if not spare:
            return None, None, 0, 0

        buying_resource = AI.select_buying_resource(missing)
        selling_resource = AI.select_selling_resource(spare)
        ai_buying_rate = AI.get_required_trade_ratio(round_num)

        return buying_resource, selling_resource, bank_rate, ai_buying_rate

    @staticmethod
    def should_trade_with_player(ai_buying_rate: int, bank_rate: int) -> bool:
        """Determine if player trade is preferable to bank trade."""
        return ai_buying_rate < bank_rate

    @staticmethod
    def choose_random_settlement(available_vertices: List[Vertex]) -> Optional[Vertex]:
        """Choose a random settlement vertex from available options."""
        return random.choice(available_vertices) if available_vertices else None

    @staticmethod
    def choose_random_road(available_edges: List[Edge]) -> Optional[Edge]:
        """Choose a random road edge from available options."""
        return random.choice(available_edges) if available_edges else None

    @staticmethod
    def choose_random_build_location(
            buildable_options: Dict[Buildable, List | bool],
            action: Buildable
    ) -> Optional[Vertex | Edge | bool]:
        """Choose a random location for a build action. Handles mixed types."""
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

    @staticmethod
    def can_build_development_card(buildable_options: Dict[Buildable, List | bool]) -> bool:
        """Check if development card can be built."""
        return buildable_options.get(Buildable.DEVELOPMENT_CARD, False)

    @staticmethod
    def decide_dev_card_usage(
            playable_cards: List[DevelopmentCardType],
            used_dev_card: bool
    ) -> Optional[DevelopmentCardType]:
        """Decide whether to use a development card and which one."""
        if playable_cards and not used_dev_card and random.random() < 0.3:
            return random.choice(playable_cards)
        return None

    @staticmethod
    def decide_robber_placement(
            valid_hexes: List[HexTile],
            current_player: Player,
            get_players_on_hex_func,
            has_resources_func
    ) -> Tuple[HexTile, Optional[Player]]:
        """Decide where to place the robber and who to steal from."""
        # Filter hexes that have at least one stealable opponent
        stealable_hexes = [
            hex_tile for hex_tile in valid_hexes
            if any(
                p != current_player and has_resources_func(p)
                for p in get_players_on_hex_func(hex_tile)
            )
        ]

        if stealable_hexes:
            # Pick a random hex where stealing is possible
            hex_tile = random.choice(stealable_hexes)

            stealable_players = [
                p for p in get_players_on_hex_func(hex_tile)
                if p != current_player and has_resources_func(p)
            ]

            target_player = random.choice(stealable_players)
            return hex_tile, target_player

        # Otherwise, move robber to any other valid hex (no stealing)
        hex_tile = random.choice(valid_hexes)
        return hex_tile, None

    @staticmethod
    def decide_robber_discard(player_resources: ResourceCount, num_resources: int) -> ResourceCount:
        """Decide which resources to discard."""
        return AI.pick_random_resources(player_resources, num_resources)

    @staticmethod
    def decide_year_of_plenty_resources(available_resources: ResourceCount) -> ResourceCount:
        """Decide which two resources to take for Year of Plenty."""
        return AI.pick_random_resources(available_resources, 2)

    @staticmethod
    def decide_monopoly_resource(available_resources: ResourceCount) -> Resource:
        """Decide which resource to monopolise."""
        res_dict = AI.pick_random_resources(available_resources, 1)
        return next(iter(res_dict.keys()))

    @staticmethod
    def trade_manager_ai_logic(
            player_resources: ResourceCount,
            selling: ResourceCount,
            buying: ResourceCount,
            round_num: int
    ) -> Tuple[bool, Optional[ResourceCount]]:
        """
        Pure AI logic for accepting or rejecting a trade.
        Returns (accept, counteroffer).
        """
        # 1. Check if AI has the resources it is being asked to give
        for resource, amount in buying.items():
            if player_resources.get(resource, 0) < amount:
                return False, None  # Cannot trade what you don't have

        # 2. AI expected ratio
        required_ratio = AI.get_required_trade_ratio(round_num)

        # 3. Totals
        total_selling = sum(selling.values())  # What AI would get
        total_buying = sum(buying.values())  # What AI would give

        over_cost = total_selling - required_ratio * total_buying
        over_cost_int = int(abs(over_cost))

        # 4. Decide accept or counter probabilistically
        prob = AI.ACCEPT_PROBABILITY_BY_OVERCOST.get(over_cost_int, 0.0)
        if random.random() < prob:
            return True, None  # Accept

        # 5. Generate simple counteroffer if not accepting
        if total_selling < required_ratio * total_buying:
            missing = required_ratio * total_buying - total_selling
            # Pick one offered resource to increase
            resource_to_increase = max(selling, key=lambda r: selling[r])
            counter_selling = selling.copy()
            counter_selling[resource_to_increase] += int(missing)
            return True, counter_selling

        # Otherwise, reject
        return False, None

    @staticmethod
    def decide_post_roll_dev_card_usage(
            playable_cards: List[DevelopmentCardType],
            used_dev_card: bool
    ) -> Optional[DevelopmentCardType]:
        """Decide whether to use a development card post-roll (if not used pre-roll)."""
        if playable_cards and not used_dev_card:
            return random.choice(playable_cards)
        return None
