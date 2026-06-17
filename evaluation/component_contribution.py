import argparse
import multiprocessing as mp
import time
from collections import defaultdict
from dataclasses import dataclass
from random import Random

from tqdm import tqdm

from ai.rule_based_ai.RuleBasedAI import RuleBasedAIDecisionConfig
from config.player_policies import make_rule_based_policy
from config.StrategyWeights import EVO_STRATEGY_WEIGHTS, ORIGINAL_STRATEGY_WEIGHTS
from controllers.GameController import GameController
from game.Player import PlayerNumber
from view.HeadlessView import HeadlessView

NUM_SIMULATIONS = 100
DEFAULT_SEED = 20260506
SHUFFLE_ORDER = True
NUM_PROCESSES = mp.cpu_count()
SHOW_PROGRESS_BAR = True
MAX_EVALUATION_ROUNDS = 200
MAX_ATTEMPTS_MULTIPLIER = 5
PRINT_EVERY_N_GAMES = 20

MODE_FULL_SYSTEM = "full_system"
MODE_SINGLE_STEP_ETW_ROLLOUT = "single_step_etw_rollout"
MODE_NO_MULTI_STEP_ETW_PLANNING = "no_multi_step_etw_planning"
MODE_NO_OPPONENT_INTERFERENCE = "no_opponent_interference"
MODE_NO_TIME_DISCOUNT = "no_time_discount"
MODE_NO_PLAYER_TRADING = "no_player_trading"
MODE_NO_DEVELOPMENT_CARDS = "no_development_cards"
MODE_ALL = "all"

MODE_LABELS = {
    MODE_FULL_SYSTEM: "Full System",
    MODE_SINGLE_STEP_ETW_ROLLOUT: "Single-step ETW Rollout",
    MODE_NO_MULTI_STEP_ETW_PLANNING: "Single-step ETW Rollout",
    MODE_NO_OPPONENT_INTERFERENCE: "No Opponent Interference",
    MODE_NO_TIME_DISCOUNT: "No Time Discount",
    MODE_NO_PLAYER_TRADING: "No Player Trading",
    MODE_NO_DEVELOPMENT_CARDS: "No Development Cards",
    MODE_ALL: "All Modes",
}

EVALUATION_MODES = [
    MODE_FULL_SYSTEM,
    MODE_SINGLE_STEP_ETW_ROLLOUT,
    MODE_NO_OPPONENT_INTERFERENCE,
    MODE_NO_TIME_DISCOUNT,
    MODE_NO_PLAYER_TRADING,
    MODE_NO_DEVELOPMENT_CARDS,
]


@dataclass(frozen=True)
class PlayerResult:
    policy_name: str
    player_number: PlayerNumber
    victory_points: int
    won: bool


def _policy_name(policy) -> str:
    return getattr(policy, "policy_name", type(policy).__name__)


def _decision_config_for_mode(mode: str) -> RuleBasedAIDecisionConfig:
    if mode == MODE_FULL_SYSTEM:
        return RuleBasedAIDecisionConfig.full_system()
    if mode in (MODE_SINGLE_STEP_ETW_ROLLOUT, MODE_NO_MULTI_STEP_ETW_PLANNING):
        return RuleBasedAIDecisionConfig.single_step_etw_rollout()
    if mode == MODE_NO_OPPONENT_INTERFERENCE:
        return RuleBasedAIDecisionConfig.no_opponent_interference()
    if mode == MODE_NO_TIME_DISCOUNT:
        return RuleBasedAIDecisionConfig.no_time_discount()
    if mode == MODE_NO_PLAYER_TRADING:
        return RuleBasedAIDecisionConfig.no_player_trading()
    if mode == MODE_NO_DEVELOPMENT_CARDS:
        return RuleBasedAIDecisionConfig.no_development_cards()
    raise ValueError(f"Unsupported mode: {mode}")


def _build_experiment_config(mode: str):
    mode_label = MODE_LABELS[mode]
    tested_policy = make_rule_based_policy(
        f"RuleBasedAI Evo - {mode_label}",
        EVO_STRATEGY_WEIGHTS,
        decision_config=_decision_config_for_mode(mode),
    )
    original_policy = make_rule_based_policy("RuleBasedAI Original", ORIGINAL_STRATEGY_WEIGHTS)
    return {
        PlayerNumber.P1: tested_policy,
        PlayerNumber.P2: original_policy,
        PlayerNumber.P3: original_policy,
        PlayerNumber.P4: original_policy,
    }


def _build_player_config(player_policies, order_seed: int):
    rng = Random(order_seed)
    ordered_player_numbers = list(player_policies.keys())
    ordered_policies = list(player_policies.values())

    if SHUFFLE_ORDER:
        rng.shuffle(ordered_policies)

    return {player_number: policy for player_number, policy in zip(ordered_player_numbers, ordered_policies)}


def run_single_game(job_args):
    game_seed, order_seed, player_policies, game_id, max_rounds = job_args

    shuffled_config = _build_player_config(player_policies, order_seed)

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

    final_vp = {player.player_number: player.calc_victory_points()[1] for player in game.players}
    sorted_vps = sorted(final_vp.values(), reverse=True)

    player_results: list[PlayerResult] = []
    for player in game.players:
        player_vp = final_vp[player.player_number]
        player_results.append(
            PlayerResult(
                policy_name=_policy_name(player.policy),
                player_number=player.player_number,
                victory_points=player_vp,
                won=player_vp == sorted_vps[0] and sorted_vps.count(sorted_vps[0]) == 1,
            ))

    return {
        "game_id": game_id,
        "turns": game.round_num,
        "completed": True,
        "players": player_results,
    }


def _format_results_table(summary: dict[str, dict[str, float]]) -> str:
    headers = ["Policy", "Win Rate (%)", "Avg VP"]
    rows = [[
        policy_name,
        f"{metrics['win_rate']:.2f}",
        f"{metrics['avg_vp']:.2f}",
    ] for policy_name, metrics in summary.items()]

    widths = [
        max(len(header), *(len(row[column_index]) for row in rows)) for column_index, header in enumerate(headers)
    ]

    def fmt(row):
        return " | ".join(cell.ljust(widths[column_index]) for column_index, cell in enumerate(row))

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join([fmt(headers), separator, *(fmt(row) for row in rows)])


def _summarise_results(results):
    policy_totals = defaultdict(lambda: {
        "games": 0,
        "wins": 0,
        "appearances": 0,
        "vp_total": 0,
    })

    for game_result in results:
        policy_won_game = set()

        for player_result in game_result["players"]:
            totals = policy_totals[player_result.policy_name]
            totals["appearances"] += 1
            totals["vp_total"] += player_result.victory_points
            if player_result.won:
                policy_won_game.add(player_result.policy_name)

        for policy_name, totals in policy_totals.items():
            if any(player_result.policy_name == policy_name for player_result in game_result["players"]):
                totals["games"] += 1

        for policy_name in policy_won_game:
            policy_totals[policy_name]["wins"] += 1

    return {
        policy_name: {
            "win_rate": totals["wins"] / totals["games"] * 100.0,
            "avg_vp": totals["vp_total"] / totals["appearances"],
        }
        for policy_name, totals in sorted(policy_totals.items())
    }


def _print_progress_table(results, progress=None):
    partial_summary = _summarise_results(results)
    lines = [
        "",
        f"Results after {len(results)} completed games:",
        _format_results_table(partial_summary),
        "",
    ]

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
    print(f"Random starting order: {SHUFFLE_ORDER}")

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
                raise RuntimeError(f"Policy evaluation exceeded the retry budget after {aborted_games} aborted games.")

            batch_size = min(remaining_runs, remaining_attempt_budget)
            args_list = [(
                seed + attempts_started + i,
                seed * 10_000 + attempts_started + i,
                player_policies,
                attempts_started + i,
                MAX_EVALUATION_ROUNDS,
            ) for i in range(batch_size)]
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

    elapsed = time.time() - start
    print()
    print(_format_results_table(summary))
    print()

    if aborted_games:
        print(f"Skipped {aborted_games} games that either hit the {MAX_EVALUATION_ROUNDS}-round cap "
              f"or exceeded the per-turn AI action request limit, and retried them.")

    print(f"Simulation of {num_runs} games took {elapsed:.1f} seconds "
          f"({elapsed / num_runs:.2f} seconds/game).")

    return results, summary


def parse_args():
    parser = argparse.ArgumentParser(description="Run policy evaluation experiments for Catan AIs.")
    parser.add_argument("--runs", type=int, default=NUM_SIMULATIONS, help="Number of games to simulate.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Base seed for deterministic reruns.")
    parser.add_argument(
        "--mode",
        type=str,
        default=MODE_FULL_SYSTEM,
        choices=list(MODE_LABELS.keys()),
        help="Evaluation mode for the single Evo policy under test, or 'all' to run every mode sequentially.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_args()
    print(f"Running {cli_args.runs} Catan simulations...")
    print(f"CPU cores available: {NUM_PROCESSES}")
    print("Experiment: 1x tested RuleBasedAI Evo vs 3x RuleBasedAI Original")

    modes_to_run = EVALUATION_MODES if cli_args.mode == MODE_ALL else [cli_args.mode]

    for mode_index, evaluation_mode in enumerate(modes_to_run, start=1):
        if len(modes_to_run) > 1:
            print()
            print(f"=== Mode {mode_index}/{len(modes_to_run)}: {MODE_LABELS[evaluation_mode]} ===")
        else:
            print(f"Mode: {MODE_LABELS[evaluation_mode]}")

        experiment_config = _build_experiment_config(evaluation_mode)
        run_simulations_parallel(experiment_config, num_runs=cli_args.runs, seed=cli_args.seed)

    input("Press enter to terminate")
