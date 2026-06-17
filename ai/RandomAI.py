from random import Random

from ai.actions import Action, ActionType, Phase
from ai.AI import AI
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex


class RandomAI(AI):
    """Purely random Catan AI with no strategic logic."""

    def __init__(self, rng: Random):
        super().__init__(rng)

    def new_turn(self):
        """Reset turn-specific state for a new turn."""
        pass

    def _choose_resources(self, player: Player, num_resources: int) -> ResourceCount:
        """Choose a bundle of resources from the player's hand."""
        # Flatten all available resources into a pool
        pool = [r for r, count in player.resources.items() for _ in range(count)]

        # Cap number of resources to what is actually available
        num_resources = min(num_resources, len(pool))
        if num_resources == 0:
            return {}

        chosen = self.rng.sample(pool, num_resources)
        result: ResourceCount = {}
        for r in chosen:
            result[r] = result.get(r, 0) + 1
        return result

    def choose_trade_partner(
        self,
        player: Player,
        game: "Game",
        selling: ResourceCount,
        buying: ResourceCount,
        available_players: list[tuple[Player, ResourceCount | None]],
    ) -> tuple[Player, ResourceCount | None] | None:
        """Choose the trade partner and offer to pursue."""
        if not available_players:
            return None

        # Pick randomly among valid options
        return self.rng.choice(available_players)

    def select_initial_settlement_location(self, player: Player, game: Game, available_vertices: list[Vertex]) \
            -> Vertex | None:
        """Select the opening settlement location."""
        return self.rng.choice(available_vertices) if available_vertices else None

    def select_initial_road_location(self, player: Player, game: Game, available_edges: list[Edge]) -> Edge | None:
        """Select the opening road location."""
        return self.rng.choice(available_edges) if available_edges else None

    def select_robber_target(
        self,
        player: Player,
        game: Game,
        valid_hexes: list[HexTile],
    ) -> tuple[HexTile, Player | None]:
        """Select the robber placement and steal target."""
        hex_tile = self.rng.choice(valid_hexes)

        players = [p for p in game.get_players_on_hex(hex_tile) if p != player and p.has_resources()]

        target = self.rng.choice(players) if players else None
        return hex_tile, target

    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        """Select the resources to discard."""
        return self._choose_resources(player, num_resources)

    def select_year_of_plenty_resources(self, player: Player, game: Game) -> ResourceCount:
        """Select the resources to take from Year of Plenty."""
        return self._choose_resources(player, 2)

    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        """Select the resource to claim with Monopoly."""
        return self.rng.choice(list(Resource))

    def respond_to_trade(self, player: Player, game: "Game", opponent: Player, selling: ResourceCount,
                         buying: ResourceCount) -> tuple[bool, ResourceCount | None]:
        """Decide how to respond to a trade offer."""
        return self.rng.choice([True, False]), None

    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        """Choose the next action for the current turn state."""

        if phase == Phase.PRE_ROLL:
            if not dev_played:
                # Play a dev card if possible
                playable_cards = [c.card_type for c in player.development_cards if c.playable]
                if playable_cards and self.rng.choice([True, False]):
                    return Action(ActionType.PLAY_DEV_CARD, self.rng.choice(playable_cards))
            return Action(ActionType.ROLL)

        # Main phase

        # 1. Build if possible
        buildables_options = game.get_buildable_options(player)
        buildables = [b for b, locs in buildables_options.items() if locs]
        if buildables and self.rng.choice([True, False]):
            chosen_build = self.rng.choice(buildables)
            locations = buildables_options[chosen_build]

            # Pick a random location for the build
            if isinstance(locations, list) and locations:
                loc = self.rng.choice(locations)
            else:
                loc = locations  # could be True/False for dev card
            return Action(ActionType.BUILD, (chosen_build, loc))

        # 2. Buy a development card if affordable
        if buildables_options[Buildable.DEVELOPMENT_CARD] and self.rng.choice([True, False]):
            return Action(ActionType.BUY_DEV_CARD)

        # 3. Trade randomly (with bank or players)
        if player.has_resources() and self.rng.choice([True, False]):
            return self.random_trade_action(player, game)

        # 5. End turn if nothing else is chosen
        return Action(ActionType.END_TURN)

    def random_trade_action(self, player: Player, game: Game) -> Action | None:
        """Choose a random legal trade action."""
        # Flatten available resources
        tradable_resources = [r for r, count in player.resources.items() if count > 0]
        if not tradable_resources:
            return None

        # Pick a random resource to sell
        sell_resource = self.rng.choice(tradable_resources)
        bank_rate = game.get_trade_rate(player, sell_resource)  # Fetch correct bank rate

        selling: ResourceCount = {}
        buying: ResourceCount = {}

        # Decide amount to sell
        if player.resources.get(sell_resource, 0) >= bank_rate:
            # Can do a bank trade
            selling[sell_resource] = bank_rate
            # Pick a different random resource to buy
            buying_resource = self.rng.choice([r for r in Resource if r != sell_resource])
            buying[buying_resource] = 1
            return Action(ActionType.TRADE_WITH_BANK, (selling, buying))
        else:
            # Otherwise propose a trade with a player (random sell quantity)
            num_to_sell = self.rng.randint(1, player.resources[sell_resource])
            selling[sell_resource] = num_to_sell
            # Pick a random resource to acquire
            buying_resource = self.rng.choice([r for r in Resource if r != sell_resource])
            buying[buying_resource] = 1
            return Action(ActionType.TRADE_WITH_PLAYER, (selling, buying))
