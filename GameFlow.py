from typing import Callable, List, Dict

from game.Edge import Edge
from game.Game import Game
from game.Player import Player
from game.Resources import Resource
from game.Vertex import Vertex
from view.display import display_results


class GameFlow:
    """
    Controls the flow of a Catan game using a pure Game model.
    Handles turns, building actions, and dice rolls via hooks.
    """

    def __init__(
        self,
        game: Game,
        get_settlement_choice: Callable[[Player, Game], Vertex] = None,
        get_road_choice: Callable[[Vertex, Game], Edge] = None,
        get_settlement_choice_ai: Callable[[Player, Game], Vertex] = None,
        get_road_choice_ai: Callable[[Vertex, Game], Edge] = None,
        play_round_hook: Callable[[Player, "GameFlow"], None] = None,
        play_round_ai_hook: Callable[[Player, Game], None] = None,
        trade_manager_hook: Callable[[Player, Dict[Resource, int], Dict[Resource, int], Player], bool] = None,
        trade_manager_ai_hook: Callable[[Player, Dict[Resource, int], Dict[Resource, int], Player, int], bool] = None
    ):
        self.game = game
        self.round_num = 1

        self.get_settlement_choice = get_settlement_choice
        self.get_road_choice = get_road_choice
        self.play_round_hook = play_round_hook

        self.get_settlement_choice_ai = get_settlement_choice_ai
        self.get_road_choice_ai = get_road_choice_ai
        self.play_round_ai_hook = play_round_ai_hook

        self.trade_manager_hook = trade_manager_hook
        self.trade_manager_ai_hook = trade_manager_ai_hook

    # Initial placement phase

    def run_initial_placement(self):
        """
        Each player places two settlements and two roads in order:
        forward + reverse order for second placement.
        """
        players_order = self.game.players + list(reversed(self.game.players))
        for player in players_order:
            # Settlement
            if player.is_human and self.get_settlement_choice:
                vertex = self.get_settlement_choice(player, self.game)
            else:
                vertex = self.get_settlement_choice_ai(player, self.game)
            self.game.try_build_settlement(player, vertex, use_resources=False, road_restriction=False)

            # Road
            if player.is_human and self.get_road_choice:
                edge = self.get_road_choice(vertex, self.game)
            else:
                edge = self.get_road_choice_ai(vertex, self.game)
            self.game.try_build_road(player, edge, use_resources=False)

    # Main game loop

    def start_game(self):
        """Run initial placement, then loop turns until game over."""
        self.run_initial_placement()
        while not self.game.game_over:
            for player in self.game.players:
                if player.is_human:
                    if self.play_round_hook:
                        self.play_round_hook(player, self)
                else:
                    if self.play_round_ai_hook:
                        self.play_round_ai_hook(player, self.game)

                if self.game.game_over:
                    break

            self.round_num += 1

        display_results(self.game)

    def trade_with_players(self, selling_player, selling, buying) -> List[Player]:
        """Sees which players are willing to trade"""
        return [
            p for p in self.game.players
            if p != selling_player and (
                self.trade_manager_hook(p, selling, buying, selling_player) if p.is_human
                else self.trade_manager_ai_hook(p, selling, buying, selling_player, self.round_num)
            )
        ]
