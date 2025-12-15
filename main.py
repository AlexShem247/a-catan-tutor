from GameController import GameController
from game.Game import Game
from view.ai import random_initial_settlement_placement, random_initial_road_placement, make_round_move_ai, \
    trade_manager_ai, robber_discard_ai, place_robber_ai
from view.ui import initial_settlement_placement, initial_road_placement, make_round_move, trade_manager, \
    place_robber, robber_discard

if __name__ == "__main__":
    game = Game()

    controller = GameController(
        game,
        get_settlement_choice=random_initial_settlement_placement,  # Testing - Add back manual placement
        get_road_choice=random_initial_road_placement,
        get_settlement_choice_ai=random_initial_settlement_placement,
        get_road_choice_ai=random_initial_road_placement,
        play_round_hook=make_round_move,
        play_round_ai_hook=make_round_move_ai,
        trade_manager_hook=trade_manager,
        trade_manager_ai_hook=trade_manager_ai,
        robber_discard_hook=robber_discard,
        robber_discard_ai_hook=robber_discard_ai,
        place_robber_hook=place_robber,
        place_robber_ai_hook=place_robber_ai,
    )
    controller.start_game()
