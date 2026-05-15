import argparse
import csv
import multiprocessing as mp
import time
from pathlib import Path
from random import Random
from typing import List, Optional, TypedDict

from tqdm import tqdm

from ai.actions import Action, ActionType, Phase
from ai.rule_based_ai.RuleBasedAI import RuleBasedAI
from config.player_policies import PolicyFactory, make_rule_based_policy
from config.StrategyWeights import EVO_STRATEGY_WEIGHTS, ORIGINAL_STRATEGY_WEIGHTS
from controllers.GameController import GameController
from game.Player import PlayerNumber
from game.PlayerAssets import Buildable
from view.HeadlessView import HeadlessView

NUM_SIMULATIONS = 120
DEFAULT_SEED = 20260506
DEFAULT_OUTPUT_PATH = "behaviour_over_time.csv"
SHUFFLE_ORDER = True
NUM_PROCESSES = mp.cpu_count()
SHOW_PROGRESS_BAR = True
MAX_EVALUATION_ROUNDS = 200
MAX_ATTEMPTS_MULTIPLIER = 5
WRITE_EVERY_N_GAMES = 20

CSV_HEADERS = ["game_id", "turn", "final_turns", "progress", "action_type"]

ACTION_BUILD_ROAD = "BUILD_ROAD"
ACTION_BUILD_SETTLEMENT = "BUILD_SETTLEMENT"
ACTION_BUILD_CITY = "BUILD_CITY"
ACTION_DEVELOPMENT_CARD = "DEVELOPMENT_CARD"
ACTION_TRADE_WITH_PLAYER = "TRADE_WITH_PLAYER"


class ActionRow(TypedDict):
    turn: int
    action_type: str


class ExportedActionRow(TypedDict):
    game_id: int
    turn: int
    final_turns: int
    progress: str
    action_type: str


class InstrumentedTutorAI(RuleBasedAI):

    def __init__(self, rng: Random, **kwargs):
        super().__init__(rng, **kwargs)
        self._action_rows: List[ActionRow] = []

    @staticmethod
    def _tracked_action_type(action: Action) -> Optional[str]:
        if action.type == ActionType.BUILD and isinstance(action.payload, tuple):
            buildable = action.payload[0]
            if buildable == Buildable.ROAD:
                return ACTION_BUILD_ROAD
            if buildable == Buildable.SETTLEMENT:
                return ACTION_BUILD_SETTLEMENT
            if buildable == Buildable.CITY:
                return ACTION_BUILD_CITY
            return None

        if action.type in {ActionType.BUY_DEV_CARD, ActionType.PLAY_DEV_CARD}:
            return ACTION_DEVELOPMENT_CARD

        if action.type == ActionType.TRADE_WITH_PLAYER:
            return ACTION_TRADE_WITH_PLAYER

        return None

    def _record_action(self, game, action: Action) -> None:
        tracked_action_type = self._tracked_action_type(action)
        if tracked_action_type is None:
            return
        self._action_rows.append({
            "turn": int(game.round_num),
            "action_type": tracked_action_type,
        })

    def export_action_rows(self, game_id: int, final_turns: int) -> List[ExportedActionRow]:
        if final_turns <= 0:
            return []

        exported_rows: List[ExportedActionRow] = []
        for row in self._action_rows:
            turn = row["turn"]
            exported_rows.append({
                "game_id": game_id,
                "turn": turn,
                "final_turns": final_turns,
                "progress": f"{turn / final_turns:.3f}",
                "action_type": row["action_type"],
            })
        return exported_rows

    def next_action(self, player, game, phase: Phase, dev_played: bool) -> Action:
        action = super().next_action(player, game, phase, dev_played)
        self._record_action(game, action)
        return action


def _make_instrumented_tutor_policy(name: str) -> PolicyFactory:
    return PolicyFactory(
        ai_cls=InstrumentedTutorAI,
        name=name,
        kwargs={"strategy_weights": EVO_STRATEGY_WEIGHTS},
    )


def _build_experiment_config():
    tutor_policy = _make_instrumented_tutor_policy("Tutor")
    original_policy = make_rule_based_policy("RuleBasedAI Original", ORIGINAL_STRATEGY_WEIGHTS)
    return {
        PlayerNumber.P1: tutor_policy,
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


def _collect_tutor_action_rows(controller: GameController, game_id: int) -> List[ExportedActionRow]:
    game = controller.get_game_state()
    final_turns = int(game.round_num)
    tutor_policy = next(
        (player.policy for player in game.players if isinstance(player.policy, InstrumentedTutorAI)),
        None,
    )
    if tutor_policy is None:
        return []
    return tutor_policy.export_action_rows(game_id=game_id, final_turns=final_turns)


def run_single_game(job_args):
    game_seed, order_seed, player_policies, game_id, max_rounds = job_args

    shuffled_config = _build_player_config(player_policies, order_seed)
    controller = GameController({}, shuffled_config, game_seed=game_seed)
    controller.view = HeadlessView()
    controller.start_game(max_rounds=max_rounds)

    if controller.round_limit_reached or controller.ai_action_limit_reached:
        return {
            "game_id": game_id,
            "completed": False,
        }

    return {
        "game_id": game_id,
        "completed": True,
        "rows": _collect_tutor_action_rows(controller, game_id),
    }


def _initialise_output_csv(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_HEADERS)
        writer.writeheader()


def _append_rows_to_csv(output_path: Path, rows: List[ExportedActionRow]) -> None:
    if not rows:
        return
    with output_path.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_HEADERS)
        # noinspection PyTypeChecker
        writer.writerows(rows)


def run_simulations_parallel(
    player_policies,
    output_path: Path,
    num_runs: int = NUM_SIMULATIONS,
    seed: int = DEFAULT_SEED,
    write_every_n_games: int = WRITE_EVERY_N_GAMES,
):
    start = time.time()

    print(f"Running {num_runs} games using {NUM_PROCESSES} CPU cores...")
    print(f"Experiment seed: {seed}")
    print(f"Round cap per evaluation game: {MAX_EVALUATION_ROUNDS}")
    print(f"Random starting order: {SHUFFLE_ORDER}")
    print(f"Writing rows to: {output_path}")

    _initialise_output_csv(output_path)

    completed_games = 0
    aborted_games = 0
    attempts_started = 0
    max_attempts = max(num_runs, num_runs * MAX_ATTEMPTS_MULTIPLIER)
    pending_rows: List[ExportedActionRow] = []
    total_rows_written = 0
    progress = tqdm(total=num_runs, desc="Policy evaluation") if SHOW_PROGRESS_BAR else None

    with mp.Pool(processes=NUM_PROCESSES) as pool:
        while completed_games < num_runs:
            remaining_runs = num_runs - completed_games
            remaining_attempt_budget = max_attempts - attempts_started

            if remaining_attempt_budget <= 0:
                if pending_rows:
                    _append_rows_to_csv(output_path, pending_rows)
                    total_rows_written += len(pending_rows)
                    pending_rows.clear()
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
                    completed_games += 1
                    pending_rows.extend(game_result["rows"])

                    if progress is not None:
                        progress.update(1)

                    if completed_games % write_every_n_games == 0:
                        _append_rows_to_csv(output_path, pending_rows)
                        total_rows_written += len(pending_rows)
                        pending_rows.clear()
                        if progress is not None:
                            progress.write(f"Wrote rows after {completed_games} completed games "
                                           f"(total rows: {total_rows_written}).")
                else:
                    aborted_games += 1
                    if progress is not None:
                        progress.set_postfix_str(f"retries={aborted_games}")

    if pending_rows:
        _append_rows_to_csv(output_path, pending_rows)
        total_rows_written += len(pending_rows)

    if progress is not None:
        progress.close()

    elapsed = time.time() - start

    if aborted_games:
        print(f"Skipped {aborted_games} games that either hit the {MAX_EVALUATION_ROUNDS}-round cap "
              f"or exceeded the per-turn AI action request limit, and retried them.")

    print(f"Wrote {total_rows_written} action rows from {completed_games} completed games.")
    print(f"Simulation of {completed_games} games took {elapsed:.1f} seconds "
          f"({elapsed / max(completed_games, 1):.2f} seconds/game).")


def parse_args():
    parser = argparse.ArgumentParser(description="Collect tutor action-timing data for Catan games.")
    parser.add_argument("--runs", type=int, default=NUM_SIMULATIONS, help="Number of completed games to collect.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Base seed for deterministic reruns.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(DEFAULT_OUTPUT_PATH),
        help="CSV file to write the collected action rows to.",
    )
    parser.add_argument(
        "--write-every",
        type=int,
        default=WRITE_EVERY_N_GAMES,
        help="Flush collected rows to disk after every N completed games.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_args()
    print(f"Running {cli_args.runs} Catan simulations...")
    print(f"CPU cores available: {NUM_PROCESSES}")
    print("Experiment: evo tutor action timing against 3 original rule-based AIs")
    experiment_config = _build_experiment_config()
    run_simulations_parallel(
        experiment_config,
        output_path=cli_args.output,
        num_runs=cli_args.runs,
        seed=cli_args.seed,
        write_every_n_games=max(1, cli_args.write_every),
    )

    input("Press enter to terminate")
