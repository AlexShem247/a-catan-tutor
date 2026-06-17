import argparse
import csv
import multiprocessing as mp
import re
import time
from pathlib import Path
from random import Random

from tqdm import tqdm

from ai.actions import ActionType, Phase
from ai.rule_based_ai.RuleBasedAI import RuleBasedAI
from ai.tutor.explanations import ActionExplanation
from config.player_policies import PolicyFactory, make_rule_based_policy
from config.StrategyWeights import EVO_STRATEGY_WEIGHTS, ORIGINAL_STRATEGY_WEIGHTS
from controllers.GameController import GameController
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.Resources import Resource, ResourceCount
from view.HeadlessView import HeadlessView

NUM_SIMULATIONS = 5
DEFAULT_SEED = 20260506
DEFAULT_OUTPUT_PATH = "evaluation/tutor_explanations_dataset.csv"
SHUFFLE_ORDER = True
NUM_PROCESSES = mp.cpu_count()
SHOW_PROGRESS_BAR = True
MAX_EVALUATION_ROUNDS = 200
MAX_ATTEMPTS_MULTIPLIER = 5
WRITE_EVERY_N_GAMES = 1

CSV_HEADERS = ["game_id", "explanation_num", "action_label", "detailed_explanation"]


class InstrumentedTutorAI(RuleBasedAI):

    def __init__(self, rng: Random, **kwargs):
        super().__init__(rng, **kwargs)
        self._explanations: list[dict[str, str]] = []

    @staticmethod
    def _normalise_detail_text(text: str) -> str:
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _record_explanation(self, explanation: ActionExplanation | None) -> None:
        if explanation is None:
            return
        if explanation.chosen_action.type == ActionType.ROLL:
            return
        action_label, _ = explanation.generate_text_concise()
        self._explanations.append({
            "action_label": action_label.strip(),
            "detailed_explanation": self._normalise_detail_text(explanation.generate_text_detail()),
        })

    def export_explanation_rows(self, game_id: int) -> list[dict[str, object]]:
        return [{
            "game_id": game_id,
            "explanation_num": explanation_num,
            "action_label": row["action_label"],
            "detailed_explanation": row["detailed_explanation"],
        } for explanation_num, row in enumerate(self._explanations)]

    def select_initial_settlement_location(self, player, game, available_vertices):
        vertex, explanation = self.select_initial_settlement_location_with_explanation(player, game, available_vertices)
        self._record_explanation(explanation)
        return vertex

    def select_initial_road_location(self, player, game, available_edges):
        edge, explanation = self.select_initial_road_location_with_explanation(player, game, available_edges)
        self._record_explanation(explanation)
        return edge

    def choose_trade_partner(
        self,
        player: Player,
        game,
        selling: ResourceCount,
        buying: ResourceCount,
        available_players: list[tuple[Player, ResourceCount | None]],
    ):
        selection, explanation = self.choose_trade_partner_with_explanation(player, game, selling, buying,
                                                                            available_players)
        self._record_explanation(explanation)
        return selection

    def select_robber_target(self, player: Player, game, valid_hexes: list[HexTile]):
        tile, steal_from, explanation = self.select_robber_target_with_explanation(player, game, valid_hexes)
        self._record_explanation(explanation)
        return tile, steal_from

    def select_discard_resources(self, player: Player, game, num_resources: int) -> ResourceCount:
        discard, explanation = self.select_discard_resources_with_explanation(player, game, num_resources)
        self._record_explanation(explanation)
        return discard

    def select_year_of_plenty_resources(self, player: Player, game) -> ResourceCount:
        resources, explanation = self.select_year_of_plenty_resources_with_explanation(player, game)
        self._record_explanation(explanation)
        return resources

    def select_monopoly_resource(self, player: Player, game) -> Resource:
        resource, explanation = self.select_monopoly_resource_with_explanation(player, game)
        self._record_explanation(explanation)
        return resource

    def respond_to_trade(
        self,
        player: Player,
        game,
        opponent: Player,
        selling: ResourceCount,
        buying: ResourceCount,
    ) -> tuple[bool, ResourceCount | None]:
        accepted, counter, explanation = self.respond_to_trade_with_explanation(player, game, opponent, selling, buying)
        self._record_explanation(explanation)
        return accepted, counter

    def next_action(self, player: Player, game, phase: Phase, dev_played: bool):
        action, explanation = self.next_action_with_explanation(player, game, phase, dev_played)
        self._record_explanation(explanation)
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


def _collect_tutor_explanation_rows(controller: GameController, game_id: int) -> list[dict[str, object]]:
    game = controller.get_game_state()
    tutor_policy = next(
        (player.policy for player in game.players if isinstance(player.policy, InstrumentedTutorAI)),
        None,
    )
    if tutor_policy is None:
        return []
    return tutor_policy.export_explanation_rows(game_id=game_id)


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
        "rows": _collect_tutor_explanation_rows(controller, game_id),
    }


def _initialise_output_csv(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_HEADERS)
        writer.writeheader()


def _append_rows_to_csv(output_path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with output_path.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_HEADERS)
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
    pending_rows: list[dict[str, object]] = []
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
                            progress.write(f"Wrote explanation rows after {completed_games} completed games "
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

    print(f"Wrote {total_rows_written} explanation rows from {completed_games} completed games.")
    print(f"Simulation of {completed_games} games took {elapsed:.1f} seconds "
          f"({elapsed / max(completed_games, 1):.2f} seconds/game).")


def parse_args():
    parser = argparse.ArgumentParser(description="Collect tutor explanation text from self-play Catan games.")
    parser.add_argument("--runs", type=int, default=NUM_SIMULATIONS, help="Number of completed games to collect.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Base seed for deterministic reruns.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(DEFAULT_OUTPUT_PATH),
        help="CSV file to write the collected explanation rows to.",
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
    print("Experiment: evo tutor explanation generation against 3 original rule-based AIs")
    experiment_config = _build_experiment_config()
    run_simulations_parallel(
        experiment_config,
        output_path=cli_args.output,
        num_runs=cli_args.runs,
        seed=cli_args.seed,
        write_every_n_games=max(1, cli_args.write_every),
    )
