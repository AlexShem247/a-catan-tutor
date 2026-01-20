import random
from typing import List, Optional, Tuple

from ai.AI import AI
from ai.actions import Action, ActionType, Phase
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex


class RandomAI(AI):
    """Purely random Catan AI with no strategic logic."""
    def _choose_resources(self, player: Player, num_resources: int) -> ResourceCount:
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
                             game: Game,
                             available_players: List[Tuple[Player, Optional[ResourceCount]]],
                             ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        """Randomly select a trade partner from offers the AI can afford."""
        if not available_players:
            return None

        # Pick randomly among valid options
        return random.choice(available_players)

    def select_settlement_location(self, player: Player, game: Game, available_vertices: List[Vertex]) \
            -> Optional[Vertex]:
        """Randomly select a settlement location from available vertices."""
        return random.choice(available_vertices) if available_vertices else None

    def select_road_location(self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
        """Randomly select a road location from available edges."""
        return random.choice(available_edges) if available_edges else None

    def select_robber_target(self,
                             player: Player,
                             game: Game,
                             valid_hexes: List[HexTile],
                             ) -> Tuple[HexTile, Optional[Player]]:
        """Randomly select a hex for the robber and a victim player, if any."""
        hex_tile = random.choice(valid_hexes)

        players = [
            p for p in game.get_players_on_hex(hex_tile)
            if p != player and p.has_resources()
        ]

        target = random.choice(players) if players else None
        return hex_tile, target

    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        """Randomly choose resources to discard when required."""
        return self._choose_resources(player, num_resources)

    def select_year_of_plenty_resources(self, player: Player, game: Game) -> ResourceCount:
        """Randomly pick two resources for a Year of Plenty card."""
        return self._choose_resources(player, 2)

    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        """Randomly pick a resource to monopolise."""
        return random.choice(list(Resource))

    def respond_to_trade(self,
                         player: Player,
                         game: Game,
                         selling: ResourceCount,
                         buying: ResourceCount,
                         ) -> Tuple[bool, Optional[ResourceCount]]:
        """Randomly accept or reject a trade, assuming AI can afford it."""

        # Randomly decide to accept or reject the trade
        return random.choice([True, False]), None

    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        """
        Return the next action for this AI.
        Can be called repeatedly until the AI returns END_TURN or None.
        """

        if phase == Phase.PRE_ROLL:
            if not dev_played:
                # Play a dev card if possible
                playable_cards = [c.card_type for c in player.development_cards if c.playable]
                if playable_cards and random.choice([True, False]):
                    return Action(ActionType.PLAY_DEV_CARD, random.choice(playable_cards))
            return Action(ActionType.ROLL)

        # Main phase

        # 1. Build if possible
        buildables_options = game.get_buildable_options(player)
        buildables = [b for b, locs in buildables_options.items() if locs]
        if buildables and random.choice([True, False]):
            chosen_build = random.choice(buildables)
            locations = buildables_options[chosen_build]

            # Pick a random location for the build
            if isinstance(locations, list) and locations:
                loc = random.choice(locations)
            else:
                loc = locations  # could be True/False for dev card
            return Action(ActionType.BUILD, (chosen_build, loc))

        # 2. Buy a development card if affordable
        if buildables_options[Buildable.DEVELOPMENT_CARD] and random.choice([True, False]):
            return Action(ActionType.BUY_DEV_CARD)

        # 3. Trade randomly (with bank or players)
        if player.has_resources() and random.choice([True, False]):
            return self.random_trade_action(player, game)

        # 5. End turn if nothing else is chosen
        return Action(ActionType.END_TURN)

    def random_trade_action(self, player: Player, game: Game) -> Optional[Action]:
        """Generate a random trade action (bank or player) if the AI has resources."""
        # Flatten available resources
        tradable_resources = [r for r, count in player.resources.items() if count > 0]
        if not tradable_resources:
            return None

        # Pick a random resource to sell
        sell_resource = random.choice(tradable_resources)
        bank_rate = game.get_trade_rate(player, sell_resource)  # Fetch correct bank rate

        selling: ResourceCount = {}
        buying: ResourceCount = {}

        # Decide amount to sell
        if player.resources.get(sell_resource, 0) >= bank_rate:
            # Can do a bank trade
            selling[sell_resource] = bank_rate
            # Pick a different random resource to buy
            buying_resource = random.choice([r for r in Resource if r != sell_resource])
            buying[buying_resource] = 1
            return Action(ActionType.TRADE_WITH_BANK, (selling, buying))
        else:
            # Otherwise propose a trade with a player (random sell quantity)
            num_to_sell = random.randint(1, player.resources[sell_resource])
            selling[sell_resource] = num_to_sell
            # Pick a random resource to acquire
            buying_resource = random.choice([r for r in Resource if r != sell_resource])
            buying[buying_resource] = 1
            return Action(ActionType.TRADE_WITH_PLAYER, (selling, buying))
