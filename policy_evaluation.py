import time
from collections import defaultdict
from random import shuffle
from typing import Dict, Type

import matplotlib.pyplot as plt

from GameController import GameController
from ai.AI import AI
from config.player_policies import RULE_BASED_VS_RANDOM
from game.Player import PlayerNumber
from view.HeadlessView import HeadlessView

NUM_SIMULATIONS = 500
SHUFFLE_ORDER = True  # Randomise player order


def run_simulations(player_policies: Dict[PlayerNumber, Type[AI]], num_runs: int = NUM_SIMULATIONS):
    start = time.time()
    first_policy_class = list(player_policies.values())[0]
    first_policy_name = first_policy_class.__name__

    first_policy_wins = 0
    points_summary: Dict[str, list[int]] = defaultdict(list)

    for sim in range(num_runs):
        if SHUFFLE_ORDER:
            other_policies = list(player_policies.values())[1:]
            all_players = other_policies + [first_policy_class]
            shuffle(all_players)
            shuffled_config = {pn: pol for pn, pol in zip(player_policies.keys(), all_players)}
            first_player_number = [pn for pn, pol in shuffled_config.items() if pol == first_policy_class][0]
        else:
            shuffled_config = player_policies
            first_player_number = list(player_policies.keys())[0]

        controller = GameController({}, shuffled_config)
        controller.view = HeadlessView()
        controller.start_game()
        game = controller.get_game_state()

        sorted_players = sorted(game.players, key=lambda p: p.calc_victory_points()[1], reverse=True)
        winner = sorted_players[0]

        if winner.player_number == first_player_number:
            first_policy_wins += 1

        for player in game.players:
            policy_name = type(player.policy).__name__
            if player.player_number != first_player_number:
                policy_name += " (Other)"
            points_summary[policy_name].append(player.calc_victory_points()[1])

    # Build bar charts with discrete VP columns 1–12
    vp_bins = list(range(1, 13))  # Victory points 1 to 12

    first_policy_points = points_summary[first_policy_name]

    # Get first "Other" policy dynamically
    other_keys = [k for k in points_summary.keys() if k != first_policy_name]
    other_points = points_summary[other_keys[0]] if other_keys else []

    first_counts = [first_policy_points.count(vp) / num_runs * 100 for vp in vp_bins]
    other_counts = [other_points.count(vp) / num_runs * 100 for vp in vp_bins] if other_points else [0] * 12

    first_avg = sum(first_policy_points) / len(first_policy_points)
    first_win_rate = first_policy_wins / num_runs * 100

    other_avg = sum(other_points) / len(other_points) if other_points else 0
    other_win_rate = 100 - first_win_rate if other_points else 0

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    # Policy under test
    axes[0].bar(vp_bins, first_counts, color='red', width=0.8, edgecolor='black')
    axes[0].set_xticks(vp_bins)
    axes[0].set_xlabel("Victory Points")
    axes[0].set_ylabel("% of games")
    axes[0].set_title(f"{first_policy_name}\nWin rate: {first_win_rate:.1f}% | Avg VP: {first_avg:.2f}")

    # Other players
    axes[1].bar(vp_bins, [x / 3 for x in other_counts], color='red', width=0.8, edgecolor='black')
    axes[1].set_xticks(vp_bins)
    axes[1].set_xlabel("Victory Points")
    axes[1].set_title(f"{other_keys[0]}\nWin rate: {other_win_rate / 3:.1f}% | Avg VP: {other_avg:.2f}")

    print(
        f"Simulation of {NUM_SIMULATIONS} games: "
        f"1 {first_policy_name} vs 3 {other_keys[0].rstrip(' (Other)')} - "
        f"Took {time.time() - start:.1f} seconds."
    )

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    print("Running Catan simulations...")
    run_simulations(RULE_BASED_VS_RANDOM)
    # run_simulations(BASIC_VS_RANDOM)
    # run_simulations(ALL_RANDOM)
