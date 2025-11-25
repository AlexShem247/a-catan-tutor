from game.Board import Board
from game.Game import Game
from game.Player import Player, PlayerNumber
from view.ai import random_settlement, random_road
from view.display import display_board, clear_screen
from view.ui import choose_vertex, choose_edge

if __name__ == "__main__":
    board = Board()
    players = [Player(True, PlayerNumber.P1), Player(False, PlayerNumber.P2),
               Player(False, PlayerNumber.P3), Player(False, PlayerNumber.P4)]
    game = Game(players, board)

    # Human player
    game.get_settlement_choice = lambda player: choose_vertex(board, player, game.try_build_settlement)
    game.get_road_choice = lambda player, vertex: choose_edge(board, player, vertex, game.try_build_road)

    # Random AI for P2, P3, P4
    game.get_settlement_choice_ai = lambda player: random_settlement(board, player, game.try_build_settlement)
    game.get_road_choice_ai = lambda vertex: random_road(vertex, game.try_build_road)

    game.run_initial_placement()
    clear_screen()
    print("Board Values:\n")
    display_board(board)
