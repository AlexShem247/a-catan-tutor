from GameFlow import GameFlow
from game.Game import Game
from view.ai import random_initial_settlement_placement, random_initial_road_placement, make_round_move_ai, \
    trade_manager_ai
from view.ui import initial_settlement_placement, initial_road_placement, make_round_move, trade_manager

if __name__ == "__main__":
    game = Game()

    controller = GameFlow(
        game,
        get_settlement_choice=random_initial_settlement_placement,
        get_road_choice=random_initial_road_placement,
        get_settlement_choice_ai=random_initial_settlement_placement,
        get_road_choice_ai=random_initial_road_placement,
        play_round_hook=make_round_move,
        play_round_ai_hook=make_round_move_ai,
        trade_manager_hook=trade_manager,
        trade_manager_ai_hook=trade_manager_ai,
    )
    controller.start_game()
