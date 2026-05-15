from random import Random
from typing import Dict, List, Optional, Tuple

from ai.actions import Action, ActionType
from ai.RandomAI import RandomAI
from ai.simulation.board_sim_utils import score_hex_for_opponent
from ai.simulation.SimGame import make_sim_game_for_player
from ai.simulation.SimPlayerState import dice_probability
from ai.tutor.explanations import (ActionExplanation, CandidateExplanation, ExplanationTemplate, Reason, ReasonLabel,
                                   ReasonType)
from ai.tutor.move_quality import robber_move_quality
from ai.utils.resource_utils import calc_step_resources
from config.StrategyWeights import StrategyWeights
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.Resources import Resource


class RobberPolicy:

    def __init__(self, rng: Random, random_ai: RandomAI, etw_estimator, decision_config, use_strategic_move,
                 planner_kwargs):
        self.rng = rng
        self.random_ai = random_ai
        self.etw_estimator = etw_estimator
        self.decision_config = decision_config
        self._use_strategic_move = use_strategic_move
        self._planner_kwargs = planner_kwargs

    def select_robber_target(self, player: Player, game: Game,
                             valid_hexes: List[HexTile]) -> Tuple[HexTile, Optional[Player]]:
        """Select the robber target hex and victim."""
        tile, steal_from, _ = self.select_robber_target_with_explanation(player, game, valid_hexes)
        return tile, steal_from

    def select_robber_target_with_explanation(
            self, player: Player, game: Game,
            valid_hexes: List[HexTile]) -> Tuple[HexTile, Optional[Player], Optional[ActionExplanation]]:
        """Select the robber target with explanation."""
        if not self._use_strategic_move():
            tile, steal_from = self.random_ai.select_robber_target(player, game, valid_hexes)
            return tile, steal_from, self.explain_robber_choice(player, game, valid_hexes, tile, steal_from)

        best_score = float("-inf")
        best_hex: Optional[HexTile] = None
        our_resource_tiles = {h for v in (player.settlements + player.cities) for h in v.hexes}

        if not self.decision_config.use_opponent_interference:
            neutral_hexes = [hex_tile for hex_tile in valid_hexes if hex_tile not in our_resource_tiles]
            best_hex = self.rng.choice(neutral_hexes or valid_hexes)
            players_on_best_hex = [p for p in game.get_players_on_hex(best_hex) if p != player]
            best_player = self.rng.choice(players_on_best_hex) if players_on_best_hex else None
            self_harm = 0.0
            if best_hex in our_resource_tiles:
                self_harm = sum(
                    dice_probability(best_hex.production_number) * (2.0 if vertex in player.cities else 1.0)
                    for vertex in (player.settlements + player.cities) if best_hex in vertex.hexes)
            explanation = self._build_robber_explanation(best_hex, best_player, 0.0, best_hex in our_resource_tiles,
                                                         self_harm, 0.0)
            return best_hex, best_player, explanation

        sim_game_for_robber = make_sim_game_for_player(game, player)
        our_vp = player.calc_victory_points()[0]
        opp_vps = [p.calc_victory_points()[0] for p in game.players if p != player]
        best_opp_vp = max(opp_vps, default=0)
        diversion_boost = StrategyWeights.DIVERSION_BOOST if our_vp >= best_opp_vp else 1.0

        opponent_importance: Dict[PlayerNumber, Dict[Resource, float]] = {}
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

        for hex_tile in valid_hexes:
            players_on_h = [p for p in game.get_players_on_hex(hex_tile) if p != player]
            if not players_on_h:
                continue

            score = 0.0
            for opponent in players_on_h:
                score += score_hex_for_opponent(
                    opponent_number=opponent.player_number,
                    sim_game=sim_game_for_robber,
                    hex_tile=hex_tile,
                    importance=opponent_importance.get(opponent.player_number, {}),
                ) * (opponent.calc_victory_points()[0] * diversion_boost)

            if hex_tile in our_resource_tiles:
                score *= StrategyWeights.ROBBER_OWN_HEX_PENALTY

            if score > best_score:
                best_score = score
                best_hex = hex_tile

        if best_hex is None:
            best_hex = self.rng.choice(valid_hexes)

        self_harm = 0.0
        if best_hex in our_resource_tiles:
            self_harm = sum(
                dice_probability(best_hex.production_number) * (2.0 if vertex in player.cities else 1.0)
                for vertex in (player.settlements + player.cities) if best_hex in vertex.hexes)

        players_on_best_hex = [p for p in game.get_players_on_hex(best_hex) if p != player]
        if not players_on_best_hex:
            explanation = self._build_robber_explanation(best_hex, None, best_score, best_hex in our_resource_tiles,
                                                         self_harm, 0.0)
            return best_hex, None, explanation

        best_player = max(players_on_best_hex, key=lambda pl: sum(pl.resources.values()) * pl.calc_victory_points()[0])
        leader_vp_ratio = 0.0
        if best_opp_vp > 0:
            leader_vp_ratio = best_player.calc_victory_points()[0] / best_opp_vp
        explanation = self._build_robber_explanation(
            best_hex,
            best_player,
            best_score,
            best_hex in our_resource_tiles,
            self_harm,
            leader_vp_ratio,
        )
        return best_hex, best_player, explanation

    def explain_robber_choice(self, player: Player, game: Game, _valid_hexes: List[HexTile], chosen_hex: HexTile,
                              chosen_player: Optional[Player]) -> ActionExplanation:
        """Handle explain robber choice."""
        our_resource_tiles = {h for v in (player.settlements + player.cities) for h in v.hexes}
        if not self.decision_config.use_opponent_interference:
            self_harm = 0.0
            if chosen_hex in our_resource_tiles:
                self_harm = sum(
                    dice_probability(chosen_hex.production_number) * (2.0 if vertex in player.cities else 1.0)
                    for vertex in (player.settlements + player.cities) if chosen_hex in vertex.hexes)
            return self._build_robber_explanation(chosen_hex, chosen_player, 0.0, chosen_hex in our_resource_tiles,
                                                  self_harm, 0.0)
        sim_game_for_robber = make_sim_game_for_player(game, player)
        our_vp = player.calc_victory_points()[0]
        opp_vps = [p.calc_victory_points()[0] for p in game.players if p != player]
        best_opp_vp = max(opp_vps, default=0)
        diversion_boost = StrategyWeights.DIVERSION_BOOST if our_vp >= best_opp_vp else 1.0

        opponent_importance: Dict[PlayerNumber, Dict[Resource, float]] = {}
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

        chosen_score = 0.0
        players_on_hex = [p for p in game.get_players_on_hex(chosen_hex) if p != player]
        for opponent in players_on_hex:
            chosen_score += score_hex_for_opponent(
                opponent_number=opponent.player_number,
                sim_game=sim_game_for_robber,
                hex_tile=chosen_hex,
                importance=opponent_importance.get(opponent.player_number, {}),
            ) * (opponent.calc_victory_points()[0] * diversion_boost)
        if chosen_hex in our_resource_tiles:
            chosen_score *= StrategyWeights.ROBBER_OWN_HEX_PENALTY

        self_harm = 0.0
        if chosen_hex in our_resource_tiles:
            self_harm = sum(
                dice_probability(chosen_hex.production_number) * (2.0 if vertex in player.cities else 1.0)
                for vertex in (player.settlements + player.cities) if chosen_hex in vertex.hexes)
        target_player = chosen_player
        if target_player is None and players_on_hex:
            target_player = max(players_on_hex, key=lambda pl: sum(pl.resources.values()) * pl.calc_victory_points()[0])
        leader_vp_ratio = 0.0
        if target_player is not None and best_opp_vp > 0:
            leader_vp_ratio = target_player.calc_victory_points()[0] / best_opp_vp
        return self._build_robber_explanation(
            chosen_hex,
            target_player,
            chosen_score,
            chosen_hex in our_resource_tiles,
            self_harm,
            leader_vp_ratio,
        )

    def _build_robber_explanation(self, hex_tile: HexTile, target_player: Optional[Player], best_score: float,
                                  blocks_own_hex: bool, self_harm: float, leader_vp_ratio: float) -> ActionExplanation:
        """Build the robber explanation."""
        reasons_for: List[Reason] = []
        if best_score > float("-inf"):
            reasons_for.append(
                Reason(
                    ReasonType.SLOWS_LEADING_OPPONENT,
                    ReasonLabel.ROBBER_BLOCKS_KEY_HEX,
                    max(0.0, best_score),
                ))
        if target_player is not None:
            reasons_for.append(
                Reason(
                    ReasonType.SLOWS_LEADING_OPPONENT,
                    ReasonLabel.ROBBER_TARGETS_THREAT,
                    float(target_player.calc_victory_points()[0]),
                ))
        if not blocks_own_hex:
            reasons_for.append(Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.ROBBER_AVOIDS_OWN_HEX, 1.0))

        action = Action(ActionType.PLAY_DEV_CARD, "robber")
        candidate = CandidateExplanation(
            action=action,
            full_plan=[action],
            reasons_for=reasons_for,
            metadata={
                "template": ExplanationTemplate.ROBBER_TARGET,
                "target_hex": hex_tile,
                "target_player_name": target_player.name if target_player is not None else None,
                "visual_plan": [("ROBBER_HEX", hex_tile)],
            },
        )
        return ActionExplanation(
            chosen_action=action,
            chosen_candidate=candidate,
            move_quality=robber_move_quality(
                opponent_production_blocked=max(0.0, best_score),
                steal_value=float(sum(target_player.resources.values())) if target_player is not None else 0.0,
                self_harm=self_harm if blocks_own_hex else 0.0,
                leader_vp_ratio=leader_vp_ratio,
            ),
            metadata={"template": ExplanationTemplate.ROBBER_TARGET},
        )
