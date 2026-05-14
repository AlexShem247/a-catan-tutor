from typing import List, Tuple

from ai.actions import Action, ActionType
from ai.simulation.SimGame import SimGame
from ai.simulation.SimPlayerState import SimPlayerState, dice_probability
from ai.utils.action_utils import (
    distant_settlement_candidates,
    play_development_card_action,
    purchase_development_card_action,
)
from config.StrategyWeights import StrategyWeights
from config.performance_constants import (
    ETW_SIMULATION_MAX_CANDIDATES,
    MAX_SETTLEMENT_CANDIDATES,
    ROAD_ETB_THRESHOLD,
)
from game.Game import Game
from game.PlayerAssets import Buildable
from game.Resources import Resource


class EtwCandidateGenerator:
    def __init__(self, timing, estimator):
        self.timing = timing
        self.estimator = estimator

    @staticmethod
    def _immediate_vp_gain(action: Action) -> float:
        if action.type != ActionType.BUILD:
            return 0.0
        buildable, _ = action.payload
        if buildable in (Buildable.SETTLEMENT, Buildable.CITY):
            return 1.0
        return 0.0

    def _estimate_single_action_etb(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        action: Action,
        include_player_trades: bool = True,
    ) -> float:
        cost = Game.BUILDING_COST.get(action.payload[0], {}) if action.type == ActionType.BUILD else None
        if cost is None:
            from ai.utils.resource_utils import calc_step_resources
            cost = calc_step_resources(action)
        if not any(cost.values()):
            return 0.0
        return self.timing.estimated_time_to_build(
            player,
            sim_game,
            cost,
            include_player_trades=include_player_trades,
        )

    def estimate_single_action_etb(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        action: Action,
        include_player_trades: bool = True,
    ) -> float:
        return self._estimate_single_action_etb(
            player,
            sim_game,
            action,
            include_player_trades=include_player_trades,
        )

    def get_candidate_actions(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        dev_played: bool,
        include_player_trades: bool = True,
        allow_development_cards: bool = True,
        use_planning: bool = True,
    ) -> List[Tuple[List[Action], float, float]]:
        """Generate and prune candidates, returning (actions, etb, expected_vp_gain)."""
        cache_key = (
            player.player_number,
            dev_played,
            include_player_trades,
            allow_development_cards,
            use_planning,
            len(player.settlements),
            len(player.cities),
            len(player.roads),
            tuple((resource.value, player.resources.get(resource, 0)) for resource in Resource),
        )
        if cache_key in player.candidate_cache:
            return player.candidate_cache[cache_key][:ETW_SIMULATION_MAX_CANDIDATES]

        candidate_actions: List[Tuple[List[Action], float, float]] = []

        if len(player.cities) < Buildable.CITY.max_on_board and player.settlements:
            city_etb = self.timing.estimated_time_to_build(
                player,
                sim_game,
                Game.BUILDING_COST[Buildable.CITY],
                include_player_trades=include_player_trades,
            )
            sorted_settlements = sorted(
                player.settlements,
                key=lambda s: sum(
                    dice_probability(hex_tile.production_number)
                    for hex_tile in s.hexes
                ),
                reverse=True,
            )[:StrategyWeights.MAX_SETTLEMENTS_FOR_CITY_UPGRADE]
            for settlement in sorted_settlements:
                candidate_actions.append(([Action(ActionType.BUILD, (Buildable.CITY, settlement))], city_etb, 1))

        settlement_candidates = distant_settlement_candidates(player, sim_game, self.estimator)
        settlement_candidates.sort(key=lambda candidate_item: candidate_item[1])
        candidate_actions.extend(settlement_candidates[:MAX_SETTLEMENT_CANDIDATES])

        points_needed = Game.VICTORY_POINTS_TO_WIN - player.victory_points()
        if allow_development_cards and (player.army_size >= 2 or points_needed <= 2):
            candidate_actions.extend(purchase_development_card_action(player, sim_game, self.estimator))

        if allow_development_cards and not dev_played:
            candidate_actions.extend(play_development_card_action(player, sim_game))

        if len(candidate_actions) < StrategyWeights.MIN_CANDIDATES_FOR_ROAD:
            road_cost = Game.BUILDING_COST[Buildable.ROAD]
            road_etb = self.timing.estimated_time_to_build(
                player,
                sim_game,
                road_cost,
                include_player_trades=include_player_trades,
            )
            if road_etb < ROAD_ETB_THRESHOLD:
                added_road_candidate = False
                for vertex in player.settlements + player.cities:
                    for edge in vertex.edges:
                        if not sim_game.overlay.is_edge_taken(edge):
                            candidate_actions.append(([Action(ActionType.BUILD, (Buildable.ROAD, edge))], road_etb, 0))
                            added_road_candidate = True
                            break
                    if added_road_candidate:
                        break

        if not use_planning:
            collapsed_candidates: List[Tuple[List[Action], float, float]] = []
            seen_actions: set[str] = set()
            for action_plan, _, _ in candidate_actions:
                if not action_plan:
                    continue
                next_action = action_plan[0]
                action_key = repr(next_action)
                if action_key in seen_actions:
                    continue
                seen_actions.add(action_key)
                collapsed_candidates.append((
                    [next_action],
                    self._estimate_single_action_etb(
                        player,
                        sim_game,
                        next_action,
                        include_player_trades=include_player_trades,
                    ),
                    self._immediate_vp_gain(next_action),
                ))
            candidate_actions = collapsed_candidates

        candidate_actions.sort(key=lambda candidate_item: candidate_item[1])
        player.candidate_cache[cache_key] = candidate_actions
        return candidate_actions[:ETW_SIMULATION_MAX_CANDIDATES]
