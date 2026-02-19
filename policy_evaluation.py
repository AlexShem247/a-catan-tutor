import sys
import time
from collections import defaultdict
from random import Random
from typing import Dict, Type
import multiprocessing as mp

import matplotlib.pyplot as plt

from GameController import GameController
from ai.AI import AI
from config.player_policies import RULE_BASED_VS_BASIC
from game.Player import PlayerNumber
from view.HeadlessView import HeadlessView

NUM_SIMULATIONS = 100
SHUFFLE_ORDER = True
NUM_PROCESSES = mp.cpu_count()
SEED = 4321


def run_single_game(args):
    """Run a single game simulation - must be at module level for multiprocessing."""
    game_seed, player_policies, first_policy_class, game_id = args

    # RNG specific to THIS GAME only
    rng = Random(game_seed)

    if SHUFFLE_ORDER:
        other_policies = list(player_policies.values())[1:]
        all_players = other_policies + [first_policy_class]
        rng.shuffle(all_players)
        shuffled_config = {pn: pol for pn, pol in zip(player_policies.keys(), all_players)}
        first_player_number = [pn for pn, pol in shuffled_config.items() if pol == first_policy_class][0]
    else:
        shuffled_config = player_policies
        first_player_number = list(player_policies.keys())[0]

    # Important: use game_seed (NOT global SEED)
    controller = GameController({}, shuffled_config, game_seed=game_seed)
    controller.view = HeadlessView()
    controller.start_game()
    game = controller.get_game_state()

    sorted_players = sorted(game.players, key=lambda p: p.calc_victory_points()[1], reverse=True)
    winner = sorted_players[0]

    player_data = []
    for player in game.players:
        policy_name = type(player.policy).__name__
        if player.player_number != first_player_number:
            policy_name += " (Other)"
        player_data.append((policy_name, player.calc_victory_points()[1]))

    return {
        'game_id': game_id,
        'first_policy_won': winner.player_number == first_player_number,
        'player_data': player_data,
        'first_player_number': first_player_number,
        'first_policy_name': first_policy_class.__name__
    }


def run_simulations_parallel(player_policies: Dict[PlayerNumber, Type[AI]],
                             num_runs: int = NUM_SIMULATIONS,
                             use_progress: bool = True):
    """Run simulations in parallel using multiprocessing."""
    start = time.time()
    first_policy_class = list(player_policies.values())[0]
    first_policy_name = first_policy_class.__name__

    # Deterministic seed list from master SEED
    master_rng = Random(SEED)
    seeds = [master_rng.randrange(10**12) for _ in range(num_runs)]

    args_list = [
        (seeds[i], player_policies, first_policy_class, i)
        for i in range(num_runs)
    ]

    print(f"Running {num_runs} games using {NUM_PROCESSES} CPU cores...")

    if use_progress:
        from tqdm import tqdm
        with mp.Pool(processes=NUM_PROCESSES) as pool:
            # Use ordered imap to keep results deterministic with respect to args_list
            results = list(tqdm(pool.imap(run_single_game, args_list), total=num_runs, desc="Simulating games"))
    else:
        with mp.Pool(processes=NUM_PROCESSES) as pool:
            results = pool.map(run_single_game, args_list)

    first_policy_wins = 0
    points_summary: Dict[str, list[int]] = defaultdict(list)

    for result in results:
        if result['first_policy_won']:
            first_policy_wins += 1

        for policy_name, points in result['player_data']:
            points_summary[policy_name].append(points)

    vp_bins = list(range(1, 13))
    first_policy_points = points_summary[first_policy_name]

    other_keys = [k for k in points_summary.keys() if k != first_policy_name]
    other_points = points_summary[other_keys[0]] if other_keys else []

    first_counts = [first_policy_points.count(vp) / num_runs * 100 for vp in vp_bins]
    other_counts = [other_points.count(vp) / num_runs * 100 for vp in vp_bins] if other_points else [0] * 12

    first_avg = sum(first_policy_points) / len(first_policy_points)
    first_win_rate = first_policy_wins / num_runs * 100

    other_avg = sum(other_points) / len(other_points) if other_points else 0
    other_win_rate = 100 - first_win_rate if other_points else 0

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    axes[0].bar(vp_bins, first_counts, color='red', width=0.8, edgecolor='black')
    axes[0].set_xticks(vp_bins)
    axes[0].set_xlabel("Victory Points")
    axes[0].set_ylabel("% of games")
    axes[0].set_title(f"{first_policy_name}\nWin rate: {first_win_rate:.1f}% | Avg VP: {first_avg:.2f}")

    axes[1].bar(vp_bins, [x / 3 for x in other_counts], color='red', width=0.8, edgecolor='black')
    axes[1].set_xticks(vp_bins)
    axes[1].set_xlabel("Victory Points")
    axes[1].set_title(f"{other_keys[0]}\nWin rate: {other_win_rate / 3:.1f}% | Avg VP: {other_avg:.2f}")

    elapsed = time.time() - start
    print(
        f"Simulation of {NUM_SIMULATIONS} games: "
        f"1 {first_policy_name} vs 3 {other_keys[0].rstrip(' (Other)')} - "
        f"Took {elapsed:.1f} seconds. "
        f"({NUM_SIMULATIONS / elapsed:.1f} games/second)"
    )

    plt.tight_layout()
    plt.show()

    return results


if __name__ == "__main__":
    print(f"Running {NUM_SIMULATIONS} Catan simulations...")
    print(f"CPU cores available: {NUM_PROCESSES}")

    use_tqdm = "--no-progress" not in sys.argv
    policy = RULE_BASED_VS_BASIC

    print("Using parallel processing...")
    test_args = (1234, policy, list(policy.values())[0], 0)
    run_single_game(test_args)
    print("Test game completed successfully, starting batch...")

    run_simulations_parallel(policy, NUM_SIMULATIONS, use_tqdm)
