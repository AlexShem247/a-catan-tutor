from random import Random
from enum import Enum, auto
from math import ceil
from typing import Optional, List, Tuple, Dict

from ai.AI import AI
from ai.RuleBasedAI import RuleBasedAI
from ai.actions import Phase, Action, ActionType
from game.Game import Game
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Player import Player
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from game.Edge import Edge
from game.HexTile import HexTile


USE_OPTIMUM_SETTLEMENT_LOCATION = False


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

    class _State(Enum):
        DICE_ROLLED = auto()
        TRADE_DONE = auto()
        BUILD_DONE = auto()
        OPPORTUNISTIC_BUILD = auto()
        DEV_PLAYED = auto()

    def __init__(self, rng: Random):
        super().__init__(rng)
        self.build_target: Optional[Buildable | False] = None  # None = not yet initialised, False = no target
        self.turn_state: Optional[BasicAI._State] = None

    def new_turn(self):
        pass

    def _get_required_trade_ratio(self, round_num: int) -> int:
        """Compute AI's required trade ratio based on the round number."""
        return ceil(1 + (round_num - 1) / self.TOTAL_ROUNDS * (self.MAX_RATIO - 1))

    def _select_build_action(self) -> Buildable | bool:
        """Select a build action based on weighted preferences."""
        action_weights = {
            Buildable.CITY: 10,
            Buildable.SETTLEMENT: 8,
            Buildable.DEVELOPMENT_CARD: 6,
            Buildable.ROAD: 3,
            False: 4,
        }

        weighted_actions = []
        for action in Buildable:
            weighted_actions.extend([action] * action_weights[action])
        weighted_actions.extend([False] * action_weights[False])

        return self.rng.choice(weighted_actions)

    def _choose_resources(self, player: Player, num_resources: int) -> ResourceCount:
        """Randomly select a number of resources from available resources."""
        total = sum(player.resources.values())
        if total < num_resources:
            return {}

        pool = [
            resource
            for resource, count in player.resources.items()
            for _ in range(count)
        ]

        chosen = self.rng.sample(pool, num_resources)

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
        return self.rng.choices(players, weights=weights, k=1)[0]

    def choose_trade_partner(self, player: Player, game: "Game", selling: ResourceCount, buying: ResourceCount,
                             available_players: List[Tuple[Player, Optional[ResourceCount]]],
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
        over_cost = min_cost - self._get_required_trade_ratio(game.round_num)
        if self.rng.random() > self._accept_probability(over_cost):
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
        return self.rng.choice(list(missing_resources.keys()))

    def _select_selling_resource(self, spare_resources: Dict[Resource, int]) -> Optional[Resource]:
        """Pick a spare resource to sell."""
        if not spare_resources:
            return None
        return self.rng.choice(list(spare_resources.keys()))

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

    def _is_player_trade_better(self, ai_buying_rate: int, bank_rate: int) -> bool:
        """Check if a player trade is preferable to bank trade."""
        return ai_buying_rate < bank_rate

    def select_initial_settlement_location(self, player: Player, game: Game, available_vertices: List[Vertex]) \
            -> Optional[Vertex]:
        """Select a settlement location from available vertices using a simple heuristic."""
        if not available_vertices:
            return None

        if USE_OPTIMUM_SETTLEMENT_LOCATION:
            # Optimum settlement location heuristic:
            return max(
                available_vertices,
                key=lambda v: RuleBasedAI.vertex_utility(
                    vertex=v,
                    player=player,
                    game=game,
                    available_vertices=available_vertices,
                    first_settlement=(len(player.settlements) == 0),
                ),
                default=None,
            )

        # Fallback: prefer vertices that add missing resources
        existing_resources = {
            tile.resource
            for settlement in player.settlements
            for tile in settlement.hexes
            if tile.resource
        }

        missing_resources = {r for r in Resource} - existing_resources

        candidates = [
            v for v in available_vertices
            if any(tile.resource in missing_resources for tile in v.hexes if tile.resource)
        ]

        return self.rng.choice(candidates if candidates else available_vertices)

    def select_initial_road_location(self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
        """Select a road location from available edges."""
        return self.rng.choice(available_edges) if available_edges else None

    def _select_build_location(self,
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
            return self.rng.choice(value)

        return None

    def _decide_dev_card_usage(self, player: Player) -> Optional[DevelopmentCardType]:
        """Decide which playable development card to use, if any."""
        playable_cards = [c.card_type for c in player.development_cards if c.playable]

        if playable_cards and self.rng.random() < 0.3:
            return self.rng.choice(playable_cards)
        return None

    def select_robber_target(self,
                             player: Player,
                             game: Game,
                             valid_hexes: List[HexTile],
                             ) -> Tuple[HexTile, Optional[Player]]:
        """Select a hex for the robber and a player to steal from, if any."""
        # Filter hexes that have at least one stealable opponent
        stealable_hexes = [
            hex_tile for hex_tile in valid_hexes
            if any(
                p != player and p.has_resources()
                for p in game.get_players_on_hex(hex_tile)
            )
        ]

        if stealable_hexes:
            # Pick a random hex where stealing is possible
            hex_tile = self.rng.choice(stealable_hexes)

            stealable_players = [
                p for p in game.get_players_on_hex(hex_tile)
                if p != player and p.has_resources()
            ]

            target_player = self.rng.choice(stealable_players)
            return hex_tile, target_player

        # Otherwise, move robber to any other valid hex (no stealing)
        hex_tile = self.rng.choice(valid_hexes)
        return hex_tile, None

    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        """Select resources to discard when required."""
        return self._choose_resources(player, num_resources)

    def select_year_of_plenty_resources(self, player: Player, game: Game) -> ResourceCount:
        """Select two resources for a Year of Plenty card."""
        return self._choose_resources(player, 2)

    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        """Select a resource for a Monopoly card."""
        return self.rng.choice(list(Resource))

    def respond_to_trade(self, player: Player, game: "Game", opponent: Player, selling: ResourceCount,
                         buying: ResourceCount) -> Tuple[bool, Optional[ResourceCount]]:
        """Decide whether to accept or counter a trade, assuming AI can afford it."""

        # 1. AI expected trade ratio for this round
        required_ratio = self._get_required_trade_ratio(game.round_num)

        # 2. Compute totals
        total_selling = sum(selling.values())  # What AI would receive
        total_buying = sum(buying.values())  # What AI would give

        over_cost = total_selling - required_ratio * total_buying
        over_cost_int = int(abs(over_cost))

        # 3. Decide to accept probabilistically
        prob = self.ACCEPT_PROBABILITY_BY_OVERCOST.get(over_cost_int, 0.0)
        if self.rng.random() < prob:
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

    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        """Decide the next atomic action for BasicAI this turn."""
        if phase == Phase.PRE_ROLL:
            # Start of a new turn: reset planning state
            self.build_target = None
            self.turn_state = None

            if not dev_played:
                card = self._decide_dev_card_usage(player)
                if card:
                    return Action(ActionType.PLAY_DEV_CARD, card)
            return Action(ActionType.ROLL)

        # Main phase

        if self.build_target is None:
            # Decide next build target
            self.build_target = self._select_build_action()
            self.turn_state = self._State.DICE_ROLLED

        # 1. Trade phase
        if self.turn_state in (self._State.DICE_ROLLED, None):
            while True:
                # Only trade if target is not yet affordable
                if self.build_target and self.build_target is not False:
                    cost = Game.BUILDING_COST[self.build_target]
                    if all(player.resources.get(r, 0) >= n for r, n in cost.items()):
                        break  # Target affordable, stop trading

                trade_action = self.trade_turn(player, game.round_num)
                if trade_action is None:
                    break  # No further trade possible

                # Execute trade action
                self.turn_state = self._State.TRADE_DONE
                return trade_action  # Return a single atomic action

            # After all trades attempted
            self.turn_state = self._State.TRADE_DONE

        # 2. Planned build
        if self.turn_state == self._State.TRADE_DONE:
            if self.build_target is not False:
                selection = self._select_build_location(
                    game.get_buildable_options(player),
                    self.build_target
                )
                if selection is True:
                    self.turn_state = self._State.BUILD_DONE
                    return Action(ActionType.BUY_DEV_CARD)
                elif selection is not None:
                    self.turn_state = self._State.BUILD_DONE
                    return Action(ActionType.BUILD, (self.build_target, selection))

            # Planned build failed → opportunistic fallback
            self.turn_state = self._State.OPPORTUNISTIC_BUILD

        # 3. Opportunistic build
        if self.turn_state == self._State.OPPORTUNISTIC_BUILD:
            options = game.get_buildable_options(player)
            for buildable, locs in options.items():
                if not locs:
                    continue
                self.turn_state = self._State.BUILD_DONE
                if buildable == Buildable.DEVELOPMENT_CARD:
                    return Action(ActionType.BUY_DEV_CARD)
                loc = self.rng.choice(locs) if isinstance(locs, list) else locs
                return Action(ActionType.BUILD, (buildable, loc))

        # 4. Dev card phase
        if self.turn_state == self._State.BUILD_DONE:
            self.turn_state = self._State.DEV_PLAYED
            playable_cards = [c.card_type for c in player.development_cards if c.playable]
            if playable_cards and not dev_played:
                return Action(ActionType.PLAY_DEV_CARD, self.rng.choice(playable_cards))

        # 5. End turn
        return Action(ActionType.END_TURN)

    def trade_turn(self, player: Player, round_num: int) -> Optional[Action]:
        # Suppress trade if the build target is already affordable
        if self.build_target and self.build_target is not False:
            if player.can_afford(Game.BUILDING_COST[self.build_target]):
                return None

        # No build target → cannot trade purposefully
        if self.build_target is False:
            return None

        # Determine trade strategy
        cost = Game.BUILDING_COST[self.build_target]
        buying_resource, selling_resource, bank_rate, ai_buying_rate = self.determine_trade(
            player,
            cost,
            round_num,
            bank_rate=4  # Default bank rate
        )

        if buying_resource is None or selling_resource is None:
            return None

        buying = {r: 0 for r in Resource}
        buying[buying_resource] = 1

        # Prefer player trade if better
        if self._is_player_trade_better(ai_buying_rate, bank_rate):
            selling = self._choose_resources(player, ai_buying_rate)
            if selling is None:
                return None
            return Action(ActionType.TRADE_WITH_PLAYER, (selling, buying))

        # Otherwise, bank trade
        selling = {r: 0 for r in Resource}
        selling[selling_resource] = bank_rate
        return Action(ActionType.TRADE_WITH_BANK, (selling, buying))
