import argparse
import multiprocessing as mp
import time
from collections import defaultdict
from dataclasses import dataclass
from random import Random
from typing import Dict, List
from tqdm import tqdm

from GameController import GameController
from config.player_policies import POLICY_EVALUATION_EXPERIMENT
from game.Player import PlayerNumber
from view.HeadlessView import HeadlessView

NUM_SIMULATIONS = 220
DEFAULT_SEED = 20260504
SHUFFLE_ORDER = True
NUM_PROCESSES = mp.cpu_count()
SHOW_PROGRESS_BAR = True
MAX_EVALUATION_ROUNDS = 200
MAX_ATTEMPTS_MULTIPLIER = 5
PRINT_EVERY_N_GAMES = 20


@dataclass(frozen=True)
class PlayerResult:
    policy_name: str
    player_number: PlayerNumber
    victory_points: int
    vp_gap_to_second: int
    won: bool


def _policy_name(policy) -> str:
    return getattr(policy, "policy_name", type(policy).__name__)


def _build_shuffled_config(player_policies, seed: int):
    rng = Random(seed)
    ordered_player_numbers = list(player_policies.keys())
    ordered_policies = list(player_policies.values())

    if SHUFFLE_ORDER:
        rng.shuffle(ordered_policies)

    return {
        player_number: policy
        for player_number, policy in zip(ordered_player_numbers, ordered_policies)
    }


def run_single_game(job_args):
    game_seed, shuffle_seed, player_policies, game_id, max_rounds = job_args

    shuffled_config = _build_shuffled_config(player_policies, shuffle_seed)

    controller = GameController({}, shuffled_config, game_seed=game_seed)
    controller.view = HeadlessView()
    controller.start_game(max_rounds=max_rounds)
    game = controller.get_game_state()

    if controller.round_limit_reached or controller.ai_action_limit_reached:
        return {
            "game_id": game_id,
            "turns": game.round_num,
            "completed": False,
            "reason": "ai_action_limit" if controller.ai_action_limit_reached else "round_limit",
        }

    final_vp = {
        player.player_number: player.calc_victory_points()[1]
        for player in game.players
    }
    sorted_vps = sorted(final_vp.values(), reverse=True)

    player_results: List[PlayerResult] = []
    for player in game.players:
        player_vp = final_vp[player.player_number]
        best_other_vp = max(
            vp for other_number, vp in final_vp.items()
            if other_number != player.player_number
        )
        player_results.append(PlayerResult(
            policy_name=_policy_name(player.policy),
            player_number=player.player_number,
            victory_points=player_vp,
            vp_gap_to_second=player_vp - best_other_vp,
            won=player_vp == sorted_vps[0] and sorted_vps.count(sorted_vps[0]) == 1,
        ))

    return {
        "game_id": game_id,
        "turns": game.round_num,
        "completed": True,
        "players": player_results,
    }


def _format_results_table(summary: Dict[str, Dict[str, float]]) -> str:
    headers = ["Policy", "Win Rate (%)", "Avg VP", "VP Gap to 2nd", "Avg Turns"]
    rows = [
        [
            policy_name,
            f"{metrics['win_rate']:.2f}",
            f"{metrics['avg_vp']:.2f}",
            f"{metrics['avg_gap']:.2f}",
            f"{metrics['avg_turns']:.2f}",
        ]
        for policy_name, metrics in summary.items()
    ]

    widths = [
        max(len(header), *(len(row[column_index]) for row in rows))
        for column_index, header in enumerate(headers)
    ]

    def fmt(row):
        return " | ".join(cell.ljust(widths[column_index]) for column_index, cell in enumerate(row))

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join([fmt(headers), separator, *(fmt(row) for row in rows)])


def _format_position_win_rate_table(position_summary: Dict[str, Dict[str, float]]) -> str:
    headers = ["Starting Position", "Win Rate (%)", "Wins / Games"]
    rows = [
        [
            position_name,
            f"{metrics['win_rate']:.2f}",
            f"{metrics['wins']} / {metrics['games']}",
        ]
        for position_name, metrics in position_summary.items()
    ]

    widths = [
        max(len(header), *(len(row[column_index]) for row in rows))
        for column_index, header in enumerate(headers)
    ]

    def fmt(row):
        return " | ".join(cell.ljust(widths[column_index]) for column_index, cell in enumerate(row))

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join([fmt(headers), separator, *(fmt(row) for row in rows)])


def _summarise_results(results):
    policy_totals = defaultdict(lambda: {
        "games": 0,
        "wins": 0,
        "vp_total": 0,
        "gap_total": 0,
        "win_turn_total": 0,
    })

    for game_result in results:
        turns = game_result["turns"]
        for player_result in game_result["players"]:
            totals = policy_totals[player_result.policy_name]
            totals["games"] += 1
            totals["wins"] += int(player_result.won)
            totals["vp_total"] += player_result.victory_points
            totals["gap_total"] += player_result.vp_gap_to_second
            if player_result.won:
                totals["win_turn_total"] += turns

    return {
        policy_name: {
            "win_rate": totals["wins"] / totals["games"] * 100.0,
            "avg_vp": totals["vp_total"] / totals["games"],
            "avg_gap": totals["gap_total"] / totals["games"],
            "avg_turns": (totals["win_turn_total"] / totals["wins"]) if totals["wins"] else 0.0,
        }
        for policy_name, totals in sorted(policy_totals.items())
    }


def _summarise_position_win_rates(results):
    position_totals = defaultdict(lambda: defaultdict(lambda: {
        "games": 0,
        "wins": 0,
    }))

    for game_result in results:
        for player_result in game_result["players"]:
            totals = position_totals[player_result.policy_name][player_result.player_number.name]
            totals["games"] += 1
            totals["wins"] += int(player_result.won)

    summary = {}
    for policy_name, positions in sorted(position_totals.items()):
        summary[policy_name] = {
            player_number.name: {
                "games": positions[player_number.name]["games"],
                "wins": positions[player_number.name]["wins"],
                "win_rate": (
                    positions[player_number.name]["wins"] / positions[player_number.name]["games"] * 100.0
                    if positions[player_number.name]["games"] else 0.0
                ),
            }
            for player_number in PlayerNumber
        }

    return summary


def _print_progress_table(results, progress=None):
    partial_summary = _summarise_results(results)
    partial_position_summary = _summarise_position_win_rates(results)

    lines = [
        "",
        f"Results after {len(results)} completed games:",
        _format_results_table(partial_summary),
        "",
    ]

    for policy_name, policy_position_summary in partial_position_summary.items():
        lines.extend([
            f"{policy_name} win rate by starting position:",
            _format_position_win_rate_table(policy_position_summary),
            "",
        ])

    if progress is not None:
        for line in lines:
            progress.write(line)
    else:
        print("\n".join(lines))


def run_simulations_parallel(player_policies, num_runs: int = NUM_SIMULATIONS, seed: int = DEFAULT_SEED):
    start = time.time()

    print(f"Running {num_runs} games using {NUM_PROCESSES} CPU cores...")
    print(f"Experiment seed: {seed}")
    print(f"Round cap per evaluation game: {MAX_EVALUATION_ROUNDS}")

    results = []
    aborted_games = 0
    attempts_started = 0
    max_attempts = max(num_runs, num_runs * MAX_ATTEMPTS_MULTIPLIER)
    progress = tqdm(total=num_runs, desc="Policy evaluation") if SHOW_PROGRESS_BAR else None

    with mp.Pool(processes=NUM_PROCESSES) as pool:
        while len(results) < num_runs:
            remaining_runs = num_runs - len(results)
            remaining_attempt_budget = max_attempts - attempts_started

            if remaining_attempt_budget <= 0:
                if progress is not None:
                    progress.close()
                raise RuntimeError(
                    f"Policy evaluation exceeded the retry budget after {aborted_games} capped games."
                )

            batch_size = min(remaining_runs, remaining_attempt_budget)
            args_list = [
                (
                    seed + attempts_started + i,
                    seed * 10_000 + attempts_started + i,
                    player_policies,
                    attempts_started + i,
                    MAX_EVALUATION_ROUNDS,
                )
                for i in range(batch_size)
            ]
            attempts_started += batch_size

            for game_result in pool.imap_unordered(run_single_game, args_list):
                if game_result["completed"]:
                    results.append(game_result)

                    if progress is not None:
                        progress.update(1)

                    if len(results) % PRINT_EVERY_N_GAMES == 0:
                        _print_progress_table(results, progress)
                else:
                    aborted_games += 1

                    if progress is not None:
                        progress.set_postfix_str(f"retries={aborted_games}")

    if progress is not None:
        progress.close()

    results.sort(key=lambda result: result["game_id"])

    summary = _summarise_results(results)
    position_summary = _summarise_position_win_rates(results)

    elapsed = time.time() - start
    print()
    print(_format_results_table(summary))
    print()
    for policy_name, policy_position_summary in position_summary.items():
        print(f"{policy_name} win rate by starting position:")
        print(_format_position_win_rate_table(policy_position_summary))
        print()

    if aborted_games:
        print(
            f"Skipped {aborted_games} games that either hit the {MAX_EVALUATION_ROUNDS}-round cap "
            f"or exceeded the per-turn AI action request limit, and retried them."
        )

    print(
        f"Simulation of {num_runs} games took {elapsed:.1f} seconds "
        f"({elapsed / num_runs:.2f} seconds/game)."
    )

    return results, summary


def parse_args():
    parser = argparse.ArgumentParser(description="Run policy evaluation experiments for Catan AIs.")
    parser.add_argument("--runs", type=int, default=NUM_SIMULATIONS, help="Number of games to simulate.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Base seed for deterministic reruns.")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_args()
    print(f"Running {cli_args.runs} Catan simulations...")
    print(f"CPU cores available: {NUM_PROCESSES}")
    print("Experiment: RandomAI vs BasicAI vs RuleBasedAI Original vs RuleBasedAI Evo")
    run_simulations_parallel(POLICY_EVALUATION_EXPERIMENT, num_runs=cli_args.runs, seed=cli_args.seed)

    if SHOW_PROGRESS_BAR:
        input("Press enter to terminate")
