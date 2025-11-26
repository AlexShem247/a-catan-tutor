from game.Board import Board
from game.Game import Game
from game.Player import Player, PlayerNumber
from game.Resources import Resource
from view.ai import random_settlement, random_road, make_round_move_ai
from view.display import display_board
from view.ui import choose_vertex, choose_edge, make_round_move

if __name__ == "__main__":
    board = Board()
    players = [Player(True, PlayerNumber.P1), Player(False, PlayerNumber.P2),
               Player(False, PlayerNumber.P3), Player(False, PlayerNumber.P4)]
    game = Game(players, board)
    for resource in Resource:
        players[0].add_resource(resource, 2)

    # Human player - Temp AI
    game.get_settlement_choice = lambda player: random_settlement(board, player, game.try_build_settlement)
    game.get_road_choice = lambda player, vertex: random_road(vertex, game.try_build_road)

    # Random AI for P2, P3, P4
    game.get_settlement_choice_ai = lambda player: random_settlement(board, player, game.try_build_settlement)
    game.get_road_choice_ai = lambda vertex: random_road(vertex, game.try_build_road)

    game.play_round = lambda player: make_round_move(player, game)
    game.play_round_ai = lambda player: make_round_move_ai(board, player, game.roll_dice)

    game.start_game()
    print("Board final values:")
    display_board(game.board)
