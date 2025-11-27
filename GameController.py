from typing import Callable

from game.Edge import Edge
from game.Game import Game
from game.Player import Player
from game.Vertex import Vertex, Buildable
from view.display import display_board


class GameController:
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
        play_round_hook: Callable[[Player, Game], None] = None,
        play_round_ai_hook: Callable[[Player, Game], None] = None
    ):
        self.game = game

        self.get_settlement_choice = get_settlement_choice
        self.get_road_choice = get_road_choice
        self.play_round_hook = play_round_hook

        self.get_settlement_choice_ai = get_settlement_choice_ai
        self.get_road_choice_ai = get_road_choice_ai
        self.play_round_ai_hook = play_round_ai_hook

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
                        self.play_round_hook(player, self.game)
                else:
                    if self.play_round_ai_hook:
                        self.play_round_ai_hook(player, self.game)

                # TODO: Implement game-over check logic
                if self.game.game_over:
                    break

        print("Board final values:")
        display_board(self.game)

    def perform_build_action(
        self, player: Player, build_type: Buildable, target
    ) -> tuple[bool, str]:
        """
        Perform a build action via the Game model.
        'target' is either a Vertex (settlement/city) or Edge (road).
        """
        if build_type == Buildable.ROAD:
            return self.game.try_build_road(player, target, build=True, use_resources=True)
        elif build_type == Buildable.SETTLEMENT:
            return self.game.try_build_settlement(player, target, build=True, use_resources=True, road_restriction=True)
        elif build_type == Buildable.CITY:
            return self.game.try_build_city(player, target, build=True, use_resources=True)
        else:
            return False, "Unknown build type"

    def roll_dice_for_turn(self) -> tuple[int, int, int]:
        """Roll dice and distribute resources for the current turn."""
        return self.game.roll_dice()

    def get_available_build_options(self, player: Player) -> dict:
        """Return all buildable options for this player."""
        return self.game.get_buildable_options(player)
