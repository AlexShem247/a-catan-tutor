import random

from GameFlow import GameFlow
from game.Board import Board
from game.Game import Game
from game.Player import Player, PlayerNumber
from game.Resources import Resource
from view.ai import random_initial_settlement_placement, random_initial_road_placement, make_round_move_ai
from view.ui import initial_settlement_placement, initial_road_placement, make_round_move

if __name__ == "__main__":
    board = Board()
    players = [Player(True, PlayerNumber.P1), Player(False, PlayerNumber.P2),
               Player(False, PlayerNumber.P3), Player(False, PlayerNumber.P4)]
    game = Game(players, board)

    # Give player extra resources
    for res in Resource:
        players[0].add_resource(res, random.randint(1, 5))

    controller = GameFlow(
        game,
        get_settlement_choice=initial_settlement_placement,
        get_road_choice=random_initial_road_placement,
        get_settlement_choice_ai=random_initial_settlement_placement,
        get_road_choice_ai=random_initial_road_placement,
        play_round_hook=make_round_move,
        play_round_ai_hook=make_round_move_ai
    )
    controller.start_game()
