import math

from ai.actions import Action
from ai.simulation.board_sim_utils import get_opponents
from ai.simulation.SimGame import SimGame
from ai.simulation.SimPlayerState import SimPlayerState
from ai.utils.resource_utils import calc_step_resources, get_bank_trade_ratio
from config.StrategyWeights import StrategyWeights
from game.Resources import Resource, ResourceCount


class EtwTiming:

    def estimated_time_to_build(
        self,
        player: SimPlayerState,
        sim_game: SimGame,
        target_resources: ResourceCount,
        include_player_trades: bool = True,
    ) -> float:
        """Handle estimated time to build."""
        target_key = tuple((resource.value, target_resources.get(resource, 0)) for resource in Resource)
        player_key = (
            player.player_number,
            tuple(player.settlements),
            tuple(player.cities),
            tuple((resource.value, player.resources.get(resource, 0)) for resource in Resource),
        )
        cache_key = (player_key, target_key, include_player_trades)

        if cache_key in player.etb_cache:
            return player.etb_cache[cache_key]

        current = {resource: player.resources.get(resource, 0) for resource in Resource}
        rolls_per_unit = {resource: self._expected_rolls_for_resource(player, resource) for resource in Resource}
        deficits, excesses = self._calculate_deficits_and_excesses(current, target_resources)
        opponents = get_opponents(sim_game, player.player_number)
        trade_adjusted_rolls = self._calculate_trade_adjusted_rolls(
            player=player,
            opponents=opponents,
            deficits=deficits,
            excesses=excesses,
            rolls_per_unit=rolls_per_unit,
            bank_trade_ratio_func=lambda resource: get_bank_trade_ratio(player.settlements + player.cities, resource),
            include_player_trades=include_player_trades,
        )

        etb = max(trade_adjusted_rolls.values())
        player.etb_cache[cache_key] = etb
        return etb

    @staticmethod
    def _expected_rolls_for_resource(player: SimPlayerState, resource: Resource) -> float:
        """Handle expected rolls for resource."""
        production_rate = player.get_production_rate(resource)
        if production_rate <= 0.0:
            return float("inf")
        return 1.0 / production_rate

    def _calculate_trade_adjusted_rolls(
        self,
        player: SimPlayerState,
        opponents: list[SimPlayerState],
        deficits: dict[Resource, int],
        excesses: dict[Resource, int],
        rolls_per_unit: dict[Resource, float],
        bank_trade_ratio_func,
        include_player_trades: bool,
    ) -> dict[Resource, float]:
        """Handle calculate trade adjusted rolls."""
        trade_adjusted: dict[Resource, float] = {}

        for resource_i in Resource:
            if deficits[resource_i] <= 0:
                trade_adjusted[resource_i] = 0.0
                continue

            direct_rolls = deficits[resource_i] * rolls_per_unit[resource_i]
            immediate_trade_savings = 0.0
            for resource_j, excess in excesses.items():
                if resource_j == resource_i or excess <= 0:
                    continue
                best_ratio = bank_trade_ratio_func(resource_j)
                if include_player_trades:
                    best_ratio = min(
                        best_ratio,
                        self._player_trade_ratio(resource_j, resource_i, player, opponents, rolls_per_unit),
                    )
                units_gained = excess / max(1, best_ratio)
                immediate_trade_savings += units_gained * rolls_per_unit[resource_i]

            adjusted_rolls = max(0.0, direct_rolls - immediate_trade_savings)
            future_trade_rolls = self._future_trade_rolls_for_resource(
                resource_i=resource_i,
                player=player,
                opponents=opponents,
                deficits=deficits,
                excesses=excesses,
                rolls_per_unit=rolls_per_unit,
                bank_trade_ratio_func=bank_trade_ratio_func,
                include_player_trades=include_player_trades,
            )
            trade_adjusted[resource_i] = min(adjusted_rolls, future_trade_rolls)

        return trade_adjusted

    def _future_trade_rolls_for_resource(
        self,
        resource_i: Resource,
        player: SimPlayerState,
        opponents: list[SimPlayerState],
        deficits: dict[Resource, int],
        excesses: dict[Resource, int],
        rolls_per_unit: dict[Resource, float],
        bank_trade_ratio_func,
        include_player_trades: bool,
    ) -> float:
        """Handle future trade rolls for resource."""
        units_needed = deficits.get(resource_i, 0)
        if units_needed <= 0:
            return 0.0

        best_rolls = float("inf")
        for resource_j in Resource:
            if resource_j == resource_i:
                continue
            if deficits.get(resource_j, 0) > 0:
                continue

            source_rolls = rolls_per_unit.get(resource_j, float("inf"))
            if not math.isfinite(source_rolls) or source_rolls <= 0.0:
                continue

            best_ratio = bank_trade_ratio_func(resource_j)
            if include_player_trades:
                best_ratio = min(
                    best_ratio,
                    self._player_trade_ratio(resource_j, resource_i, player, opponents, rolls_per_unit),
                )

            tradable_now = excesses.get(resource_j, 0)
            future_rolls = max(0.0, units_needed * best_ratio - tradable_now) * source_rolls
            best_rolls = min(best_rolls, future_rolls)

        return best_rolls

    @staticmethod
    def _player_trade_ratio(
        resource_give: Resource,
        resource_need: Resource,
        player: SimPlayerState,
        opponents: list[SimPlayerState],
        rolls_per_unit: dict[Resource, float],
    ) -> int:
        """Handle player trade ratio."""
        give_rolls = rolls_per_unit.get(resource_give, float("inf"))
        need_rolls = rolls_per_unit.get(resource_need, float("inf"))

        if need_rolls == float("inf"):
            base_ratio = StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO
        else:
            if give_rolls <= 0.0 or give_rolls == float("inf"):
                base_ratio = 1
            else:
                base_ratio = math.ceil(need_rolls / give_rolls)
                base_ratio = max(1, min(StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO, base_ratio))

        leading = max([player, *opponents], key=lambda opponent: opponent.victory_points()) if opponents else player
        if leading is not player and base_ratio < StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO:
            base_ratio = min(StrategyWeights.MAX_PLAYER_TRADE_GIVE_RATIO, base_ratio + 1)
        return base_ratio

    @staticmethod
    def _calculate_deficits_and_excesses(
        current: ResourceCount,
        target: ResourceCount,
    ) -> tuple[dict[Resource, int], dict[Resource, int]]:
        """Handle calculate deficits and excesses."""
        deficits: dict[Resource, int] = {}
        excesses: dict[Resource, int] = {}
        for resource in Resource:
            needed = target.get(resource, 0)
            have = current.get(resource, 0)
            if have >= needed:
                excesses[resource] = have - needed
                deficits[resource] = 0
            else:
                excesses[resource] = 0
                deficits[resource] = needed - have
        return deficits, excesses

    def calculate_deficits_and_excesses(
        self,
        current: ResourceCount,
        target: ResourceCount,
    ) -> tuple[dict[Resource, int], dict[Resource, int]]:
        """Handle calculate deficits and excesses."""
        return self._calculate_deficits_and_excesses(current, target)

    def calc_etb_actions(self, player: SimPlayerState, sim_game: SimGame, total_actions: list[Action]) -> float:
        """Handle calc etb actions."""
        total_resources: ResourceCount = {resource: 0 for resource in Resource}
        for action in total_actions:
            step_resources = calc_step_resources(action)
            for resource, cost in step_resources.items():
                total_resources[resource] = total_resources.get(resource, 0) + cost
        return self.estimated_time_to_build(player, sim_game, total_resources)
