import argparse
import multiprocessing as mp
import time
from dataclasses import dataclass
from random import Random

from tqdm import tqdm

from ai.actions import Action, ActionType, Phase
from ai.rule_based_ai.RuleBasedAI import RuleBasedAI
from ai.simulation.board_sim_utils import (find_edge_toward_vertex, get_legal_settlement_vertices, moves_toward_vertex,
                                           score_hex_for_opponent)
from ai.simulation.SimGame import make_sim_game_for_player
from ai.tutor.move_quality import initial_settlement_move_quality, move_quality_from_margin
from ai.utils.action_utils import calc_step_resources
from config.player_policies import PolicyFactory, make_rule_based_policy
from config.StrategyWeights import EVO_STRATEGY_WEIGHTS, ORIGINAL_STRATEGY_WEIGHTS, StrategyWeights
from controllers.GameController import GameController
from game.Edge import Edge
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.PlayerAssets import Buildable
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from view.HeadlessView import HeadlessView

NUM_SIMULATIONS = 120
DEFAULT_SEED = 20260506
SHUFFLE_ORDER = True
NUM_PROCESSES = mp.cpu_count()
SHOW_PROGRESS_BAR = True
MAX_EVALUATION_ROUNDS = 200
MAX_ATTEMPTS_MULTIPLIER = 5
PRINT_EVERY_N_GAMES = 20

CATEGORY_OPENING_SETTLEMENT = "Initial Settlement Placement"
CATEGORY_SETTLEMENT_CITY = "Settlement / City Build"
CATEGORY_ROAD = "Road Placement"
CATEGORY_TRADING = "Trading Decisions"
CATEGORY_ROBBER = "Robber Placement"
CATEGORY_DEV_CARD = "Development Card Usage"

CATEGORY_ORDER = [
    CATEGORY_OPENING_SETTLEMENT,
    CATEGORY_SETTLEMENT_CITY,
    CATEGORY_ROAD,
    CATEGORY_TRADING,
    CATEGORY_ROBBER,
    CATEGORY_DEV_CARD,
]


@dataclass
class MoveCategoryStats:
    count: int = 0
    move_quality_total: float = 0.0
    utility_gap_total: float = 0.0

    def add(self, move_quality: float, utility_gap: float) -> None:
        self.count += 1
        self.move_quality_total += float(move_quality)
        self.utility_gap_total += float(utility_gap)


def _empty_move_stats() -> dict[str, MoveCategoryStats]:
    return {category: MoveCategoryStats() for category in CATEGORY_ORDER}


class InstrumentedTutorAI(RuleBasedAI):

    def __init__(self, rng: Random, **kwargs):
        super().__init__(rng, **kwargs)
        self._move_stats = _empty_move_stats()

    def export_move_stats(self) -> dict[str, dict[str, float]]:
        return {
            category: {
                "count": stats.count,
                "move_quality_total": stats.move_quality_total,
                "utility_gap_total": stats.utility_gap_total,
            }
            for category, stats in self._move_stats.items() if stats.count > 0
        }

    def _record(self, category: str | None, move_quality: float, utility_gap: float) -> None:
        if category is None:
            return
        self._move_stats[category].add(move_quality, max(0.0, utility_gap))

    @staticmethod
    def _normalised_gap_from_scores(scores: list[float]) -> float:
        if not scores:
            return 0.0
        ranked = sorted((float(score) for score in scores), reverse=True)
        if len(ranked) < 2:
            return 0.0
        return move_quality_from_margin(ranked[0], ranked[1], ranked[-1])

    @staticmethod
    def _normalised_gap_from_explanation(explanation) -> float:
        chosen_utility = float(getattr(explanation.chosen_candidate, "utility_total", 0.0) or 0.0)
        if explanation.alternatives:
            second_utility = float(getattr(explanation.alternatives[0], "utility_total", chosen_utility) or 0.0)
        else:
            second_utility = chosen_utility
        worst_utility = min(
            [
                chosen_utility, *(float(getattr(candidate, "utility_total", chosen_utility) or 0.0)
                                  for candidate in explanation.alternatives)
            ],
            default=chosen_utility,
        )
        return move_quality_from_margin(chosen_utility, second_utility, worst_utility)

    @staticmethod
    def _main_action_category(action: Action) -> str | None:
        if action.type == ActionType.BUILD and isinstance(action.payload, tuple):
            buildable = action.payload[0]
            if buildable in {Buildable.SETTLEMENT, Buildable.CITY}:
                return CATEGORY_SETTLEMENT_CITY
            if buildable == Buildable.ROAD:
                return CATEGORY_ROAD
            return None
        if action.type in {ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER}:
            return CATEGORY_TRADING
        if action.type == ActionType.PLAY_DEV_CARD:
            return CATEGORY_DEV_CARD
        return None

    def _opening_settlement_gap(
        self,
        player: Player,
        game,
        available_vertices: list[Vertex],
    ) -> float:
        _, scores = self._opening_settlement_baseline_scores(player, game, available_vertices)
        if not scores:
            return 0.0
        return self._normalised_gap_from_scores(scores)

    def _opening_settlement_baseline_vertices(
        self,
        player: Player,
        game,
        available_vertices: list[Vertex],
    ) -> list[Vertex]:
        if not available_vertices:
            return []

        own_vertices = set(player.settlements + player.cities)
        if not own_vertices:
            return list(game.get_all_vertices())

        baseline_vertices: list[Vertex] = []
        for vertex in game.get_all_vertices():
            if vertex in own_vertices:
                continue
            if any(edge.get_other_vertex(vertex) in own_vertices for edge in vertex.edges):
                continue
            baseline_vertices.append(vertex)
        return baseline_vertices

    def _opening_settlement_baseline_scores(
        self,
        player: Player,
        game,
        available_vertices: list[Vertex],
    ) -> tuple[list[Vertex], list[float]]:
        baseline_vertices = self._opening_settlement_baseline_vertices(player, game, available_vertices)
        if not baseline_vertices:
            return [], []

        first_settlement = len(player.settlements) == 0
        scores = [
            self.vertex_utility(
                vertex,
                player,
                game,
                baseline_vertices,
                first_settlement,
                use_opponent_interference=self.decision_config.use_opponent_interference,
            ) for vertex in baseline_vertices
        ]
        return baseline_vertices, scores

    def _opening_settlement_absolute_quality(
        self,
        player: Player,
        game,
        available_vertices: list[Vertex],
        chosen_vertex: Vertex | None,
    ) -> float:
        if chosen_vertex is None:
            return 0.0

        baseline_vertices, scores = self._opening_settlement_baseline_scores(player, game, available_vertices)
        if not baseline_vertices or not scores:
            return 0.0

        try:
            chosen_index = baseline_vertices.index(chosen_vertex)
        except ValueError:
            return 0.0

        chosen_score = scores[chosen_index]
        best_score = max(scores, default=chosen_score)
        return initial_settlement_move_quality(chosen_score, best_score)

    def _opening_road_gap(
        self,
        player: Player,
        game,
        available_edges: list[Edge],
    ) -> float:
        if not available_edges:
            return 0.0
        if len(player.settlements) + len(player.cities) >= 2:
            return 0.0

        current_settlement = player.settlements[-1]
        legal_vertices = get_legal_settlement_vertices(make_sim_game_for_player(game, player))
        if not legal_vertices:
            return 0.0

        vertex_scores = {
            vertex: self.vertex_utility(
                vertex,
                player,
                game,
                legal_vertices,
                first_settlement=False,
                use_opponent_interference=self.decision_config.use_opponent_interference,
            )
            for vertex in legal_vertices
        }

        if len(player.settlements) == 1:
            edge_scores = [
                max(
                    (vertex_scores[vertex] for vertex in legal_vertices
                     if find_edge_toward_vertex(current_settlement, vertex, available_edges) == edge),
                    default=0.0,
                ) for edge in available_edges
            ]
            return self._normalised_gap_from_scores(edge_scores)

        connection_edges = [
            edge for edge in available_edges
            if moves_toward_vertex(edge.get_other_vertex(current_settlement), player.settlements[0])
        ]
        if connection_edges:
            return 0.0

        edge_scores = [
            max(
                (vertex_scores[vertex] for vertex in legal_vertices
                 if find_edge_toward_vertex(current_settlement, vertex, available_edges) == edge),
                default=0.0,
            ) for edge in available_edges
        ]
        return self._normalised_gap_from_scores(edge_scores)

    def _robber_gap(
        self,
        player: Player,
        game,
        valid_hexes: list[HexTile],
    ) -> float:
        if not valid_hexes or not self.decision_config.use_opponent_interference:
            return 0.0

        our_resource_tiles = {h for v in (player.settlements + player.cities) for h in v.hexes}
        sim_game_for_robber = make_sim_game_for_player(game, player)
        our_vp = player.calc_victory_points()[0]
        opp_vps = [p.calc_victory_points()[0] for p in game.players if p != player]
        best_opp_vp = max(opp_vps, default=0)
        diversion_boost = StrategyWeights.DIVERSION_BOOST if our_vp >= best_opp_vp else 1.0

        opponent_importance: dict[PlayerNumber, dict[Resource, float]] = {}
        for opponent in game.players:
            if opponent == player:
                continue
            sim_game_opp = make_sim_game_for_player(game, opponent)
            best_action = self.etw_estimator.calculate_best_game_action(
                sim_game=sim_game_opp,
                player_number=opponent.player_number,
                dev_played=False,
                ignore_affordability=True,
                **self._planner_kwargs(ignore_opponents=True),
            )
            required = calc_step_resources(best_action)
            total = sum(required.values())
            opponent_importance[opponent.player_number] = ({
                res: amt / total
                for res, amt in required.items() if amt > 0
            } if total > 0 else {})

        scores: list[float] = []
        for hex_tile in valid_hexes:
            players_on_hex = [p for p in game.get_players_on_hex(hex_tile) if p != player]
            if not players_on_hex:
                scores.append(0.0)
                continue

            score = 0.0
            for opponent in players_on_hex:
                score += score_hex_for_opponent(
                    opponent_number=opponent.player_number,
                    sim_game=sim_game_for_robber,
                    hex_tile=hex_tile,
                    importance=opponent_importance.get(opponent.player_number, {}),
                ) * (opponent.calc_victory_points()[0] * diversion_boost)

            if hex_tile in our_resource_tiles:
                score *= StrategyWeights.ROBBER_OWN_HEX_PENALTY
            scores.append(score)

        return self._normalised_gap_from_scores(scores)

    def _trade_response_gap(
        self,
        player: Player,
        game,
        selling: ResourceCount,
        buying: ResourceCount,
        accepted: bool,
        counter: ResourceCount | None,
    ) -> float:
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        etw_before = self.etw_estimator.estimated_time_to_win(
            sim_us,
            sim_game,
            False,
            **self._etw_kwargs(include_player_trades=False),
        )

        offered_after = sim_us.copy()
        offered_after.add_resources(selling)
        offered_after.remove_resources(buying)
        offered_game = make_sim_game_for_player(sim_game.game, player)
        offered_game.overlay.set_sim_player(offered_after)
        accept_utility = max(
            0.0,
            etw_before - self.etw_estimator.estimated_time_to_win(
                offered_after,
                offered_game,
                False,
                **self._etw_kwargs(include_player_trades=False),
            ),
        )

        option_utilities = {"reject": 0.0, "accept": accept_utility}
        if counter is not None:
            counter_after = sim_us.copy()
            counter_after.add_resources(selling)
            counter_after.remove_resources(counter)
            counter_game = make_sim_game_for_player(sim_game.game, player)
            counter_game.overlay.set_sim_player(counter_after)
            option_utilities["counter"] = max(
                0.0,
                etw_before - self.etw_estimator.estimated_time_to_win(
                    counter_after,
                    counter_game,
                    False,
                    **self._etw_kwargs(include_player_trades=False),
                ),
            )

        chosen_label = "reject"
        if accepted and counter is None:
            chosen_label = "accept"
        elif accepted and counter is not None:
            chosen_label = "counter"

        chosen_utility = option_utilities.get(chosen_label, 0.0)
        second_best = max(
            (utility for label, utility in option_utilities.items() if label != chosen_label),
            default=chosen_utility,
        )
        worst_utility = min(option_utilities.values(), default=chosen_utility)
        return move_quality_from_margin(chosen_utility, second_best, worst_utility)

    def select_initial_settlement_location(
        self,
        player: Player,
        game,
        available_vertices: list[Vertex],
    ) -> Vertex | None:
        vertex, explanation = self.select_initial_settlement_location_with_explanation(player, game, available_vertices)
        if explanation is not None:
            self._record(
                CATEGORY_OPENING_SETTLEMENT,
                self._opening_settlement_absolute_quality(player, game, available_vertices, vertex),
                self._opening_settlement_gap(player, game, available_vertices),
            )
        return vertex

    def select_initial_road_location(
        self,
        player: Player,
        game,
        available_edges: list[Edge],
    ) -> Edge | None:
        edge, explanation = self.select_initial_road_location_with_explanation(player, game, available_edges)
        if explanation is not None:
            self._record(
                CATEGORY_ROAD,
                explanation.move_quality,
                self._opening_road_gap(player, game, available_edges),
            )
        return edge

    def choose_trade_partner(
        self,
        player: Player,
        game,
        selling: ResourceCount,
        buying: ResourceCount,
        available_players: list[tuple[Player, ResourceCount | None]],
    ) -> tuple[Player, ResourceCount | None] | None:
        selection, explanation = self.choose_trade_partner_with_explanation(
            player,
            game,
            selling,
            buying,
            available_players,
        )
        if explanation is not None:
            self._record(CATEGORY_TRADING, explanation.move_quality, self._normalised_gap_from_explanation(explanation))
        return selection

    def select_robber_target(
        self,
        player: Player,
        game,
        valid_hexes: list[HexTile],
    ) -> tuple[HexTile, Player | None]:
        tile, target_player, explanation = self.select_robber_target_with_explanation(player, game, valid_hexes)
        if explanation is not None:
            self._record(CATEGORY_ROBBER, explanation.move_quality, self._robber_gap(player, game, valid_hexes))
        return tile, target_player

    def respond_to_trade(
        self,
        player: Player,
        game,
        opponent: Player,
        selling: ResourceCount,
        buying: ResourceCount,
    ) -> tuple[bool, ResourceCount | None]:
        accepted, counter, explanation = self.respond_to_trade_with_explanation(player, game, opponent, selling, buying)
        if explanation is not None:
            self._record(
                CATEGORY_TRADING,
                explanation.move_quality,
                self._trade_response_gap(player, game, selling, buying, accepted, counter),
            )
        return accepted, counter

    def next_action(self, player: Player, game, phase: Phase, dev_played: bool) -> Action:
        action, explanation = self.next_action_with_explanation(player, game, phase, dev_played)
        category = self._main_action_category(action)
        if explanation is not None and category is not None:
            self._record(category, explanation.move_quality, self._normalised_gap_from_explanation(explanation))
        return action


def _make_instrumented_tutor_policy(name: str) -> PolicyFactory:
    return PolicyFactory(
        ai_cls=InstrumentedTutorAI,
        name=name,
        kwargs={"strategy_weights": EVO_STRATEGY_WEIGHTS},
    )


def _build_experiment_config():
    tested_policy = _make_instrumented_tutor_policy("Tutor")
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


def _collect_game_move_stats(controller: GameController) -> dict[str, dict[str, float]]:
    aggregate = _empty_move_stats()
    for player in controller.get_game_state().players:
        if not isinstance(player.policy, InstrumentedTutorAI):
            continue
        for category, values in player.policy.export_move_stats().items():
            aggregate[category].count += int(values["count"])
            aggregate[category].move_quality_total += float(values["move_quality_total"])
            aggregate[category].utility_gap_total += float(values["utility_gap_total"])
    return {
        category: {
            "count": stats.count,
            "move_quality_total": stats.move_quality_total,
            "utility_gap_total": stats.utility_gap_total,
        }
        for category, stats in aggregate.items() if stats.count > 0
    }


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
            "completed": False,
        }

    tutor_player = next(
        (player for player in game.players if isinstance(player.policy, InstrumentedTutorAI)),
        None,
    )
    winning_score = max((player.calc_victory_points()[1] for player in game.players), default=0)
    tutor_won = (tutor_player is not None and tutor_player.calc_victory_points()[1] >= winning_score)

    return {
        "game_id": game_id,
        "completed": True,
        "tutor_won": tutor_won,
        "move_stats": _collect_game_move_stats(controller),
    }


def _merge_move_stats(results) -> dict[str, MoveCategoryStats]:
    merged = _empty_move_stats()
    for game_result in results:
        for category, values in game_result.get("move_stats", {}).items():
            merged[category].count += int(values["count"])
            merged[category].move_quality_total += float(values["move_quality_total"])
            merged[category].utility_gap_total += float(values["utility_gap_total"])
    return merged


def _format_move_table(summary: dict[str, MoveCategoryStats]) -> str:
    headers = ["Action Type", "Avg Move Quality", "Avg Utility Gap"]
    rows = []
    for category in CATEGORY_ORDER:
        stats = summary[category]
        if stats.count:
            avg_move_quality = f"{stats.move_quality_total / stats.count:.4f}"
            avg_utility_gap = f"{stats.utility_gap_total / stats.count:.4f}"
        else:
            avg_move_quality = "N/A"
            avg_utility_gap = "N/A"
        rows.append([category, avg_move_quality, avg_utility_gap])

    widths = [max(len(header), *(len(row[index]) for row in rows)) for index, header in enumerate(headers)]

    def fmt(row):
        return " | ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join([fmt(headers), separator, *(fmt(row) for row in rows)])


def _tutor_win_rate(results) -> float:
    if not results:
        return 0.0
    tutor_wins = sum(1 for game_result in results if game_result.get("tutor_won"))
    return tutor_wins / len(results)


def _print_progress_table(results, progress=None):
    partial_summary = _merge_move_stats(results)
    tutor_win_rate = _tutor_win_rate(results)
    lines = [
        "",
        f"Results after {len(results)} completed games:",
        f"Tutor win rate: {tutor_win_rate:.1%}",
        _format_move_table(partial_summary),
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
    summary = _merge_move_stats(results)
    tutor_win_rate = _tutor_win_rate(results)

    elapsed = time.time() - start
    print()
    print(f"Tutor win rate: {tutor_win_rate:.1%}")
    print(_format_move_table(summary))
    print()

    if aborted_games:
        print(f"Skipped {aborted_games} games that either hit the {MAX_EVALUATION_ROUNDS}-round cap "
              f"or exceeded the per-turn AI action request limit, and retried them.")

    print(f"Simulation of {num_runs} games took {elapsed:.1f} seconds "
          f"({elapsed / num_runs:.2f} seconds/game).")

    return results, summary


def parse_args():
    parser = argparse.ArgumentParser(description="Run tutor move-quality experiments for Catan AIs.")
    parser.add_argument("--runs", type=int, default=NUM_SIMULATIONS, help="Number of games to simulate.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Base seed for deterministic reruns.")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_args()
    print(f"Running {cli_args.runs} Catan simulations...")
    print(f"CPU cores available: {NUM_PROCESSES}")
    print("Experiment: tutor move quality and best-vs-second-best utility gap")
    experiment_config = _build_experiment_config()
    run_simulations_parallel(experiment_config, num_runs=cli_args.runs, seed=cli_args.seed)

    input("Press enter to terminate")
