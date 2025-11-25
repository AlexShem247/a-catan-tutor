from game.Board import Board
from game.Game import Game
from game.Player import Player, PlayerNumber
from view.display import display_board
from view.ui import choose_vertex, choose_edge

if __name__ == "__main__":
    board = Board()
    players = [Player(PlayerNumber.P1), Player(PlayerNumber.P2), Player(PlayerNumber.P3), Player(PlayerNumber.P4)]
    game = Game(players, board)

    game.get_settlement_choice = lambda player: choose_vertex(board, player, game.try_build_settlement)
    game.get_road_choice = lambda player: choose_edge(board, player, game.try_build_road)

    game.run_initial_placement()
    display_board(board)
