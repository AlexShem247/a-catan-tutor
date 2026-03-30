import random
from typing import Dict, List, Optional, Tuple

from ai.AI import AI
from ai.ai_utils.EtwEstimator import EtwEstimator
from ai.ai_utils.SimGame import make_sim_game_for_player
from ai.ai_utils.SimPlayerState import SimPlayerState, dice_probability
from ai.ai_utils.action_utils import play_development_card_action
from ai.ai_utils.actions import Phase, ActionType, Action
from ai.ai_utils.board_sim_utils import (
    find_edge_toward_vertex, find_edge_toward_vertex_from_any, find_gap_connection,
    get_legal_settlement_vertices, get_opponents, get_reachable_vertices, moves_toward_vertex,
    score_hex_for_opponent,
)
from ai.ai_utils.explanations import (
    ActionExplanation, AssumptionCode, CandidateExplanation, ExplanationTemplate,
    RoadExplanationKind, Reason, ReasonLabel, ReasonType, confidence_label,
)
from ai.ai_utils.resource_utils import calc_step_resources
from ai.ai_utils.trade_utils import respond_to_trade_batna, select_best_trade_partner
from config.StrategyWeights import StrategyWeights
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.PlayerAssets import Buildable
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex


class RuleBasedAI(AI):
    def __init__(self):
        self.etw_estimator = EtwEstimator()

    def new_turn(self):
        self.etw_estimator.new_turn()

    def select_initial_settlement_location(
            self, player: Player, game: Game, available_vertices: List[Vertex]) -> Optional[Vertex]:
        """Return the best initial settlement vertex based on utility evaluation."""
        vertex, _ = self.select_initial_settlement_location_with_explanation(player, game, available_vertices)
        return vertex

    def select_initial_road_location(
            self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
        """Return the best initial road edge connecting settlements or toward high-utility vertices."""
        edge, _ = self.select_initial_road_location_with_explanation(player, game, available_edges)
        return edge

    def select_initial_settlement_location_with_explanation(
            self, player: Player, game: Game,
            available_vertices: List[Vertex]) -> Tuple[Optional[Vertex], Optional[ActionExplanation]]:
        """Return the best initial settlement vertex together with an explanation."""
        if not available_vertices:
            return None, None

        first_settlement = len(player.settlements) == 0
        ranked_vertices = sorted(
            available_vertices,
            key=lambda vertex: self.vertex_utility(vertex, player, game, available_vertices, first_settlement),
            reverse=True,
        )
        best_vertex = ranked_vertices[0]
        best_score = self.vertex_utility(best_vertex, player, game, available_vertices, first_settlement)
        second_score = (
            self.vertex_utility(ranked_vertices[1], player, game, available_vertices, first_settlement)
            if len(ranked_vertices) > 1 else best_score
        )

        explanation = self._build_initial_settlement_explanation(player, best_vertex, best_score, second_score)
        return best_vertex, explanation

    def select_initial_road_location_with_explanation(
            self, player: Player, game: Game,
            available_edges: List[Edge]) -> Tuple[Optional[Edge], Optional[ActionExplanation]]:
        """Return the best initial road edge together with an explanation."""
        if not available_edges:
            return None, None

        if len(player.settlements) + len(player.cities) >= 2:
            edge = self.road_building_placement(player, game, available_edges)
            if edge is None:
                return None, None
            explanation = self._build_initial_road_explanation(
                edge, target_vertex=None, explanation_kind=RoadExplanationKind.FLEXIBLE)
            return edge, explanation

        current_settlement = player.settlements[-1]
        legal_vertices = get_legal_settlement_vertices(make_sim_game_for_player(game, player))

        if len(player.settlements) == 1:
            best_vertex = max(
                legal_vertices,
                key=lambda vertex: self.vertex_utility(vertex, player, game, legal_vertices, first_settlement=False),
                default=None,
            )
            if best_vertex is not None:
                edge = find_edge_toward_vertex(current_settlement, best_vertex, available_edges)
                if edge is not None:
                    explanation = self._build_initial_road_explanation(
                        edge, target_vertex=best_vertex, explanation_kind=RoadExplanationKind.EXPANSION)
                    return edge, explanation
        else:
            for edge in available_edges:
                other_vertex = edge.get_other_vertex(current_settlement)
                if moves_toward_vertex(other_vertex, player.settlements[0]):
                    explanation = self._build_initial_road_explanation(
                        edge, target_vertex=player.settlements[0], explanation_kind=RoadExplanationKind.CONNECTION)
                    return edge, explanation

            best_vertex = max(
                legal_vertices,
                key=lambda vertex: self.vertex_utility(vertex, player, game, legal_vertices, first_settlement=False),
                default=None,
            )
            if best_vertex is not None:
                edge = find_edge_toward_vertex(current_settlement, best_vertex, available_edges)
                if edge is not None:
                    explanation = self._build_initial_road_explanation(
                        edge, target_vertex=best_vertex, explanation_kind=RoadExplanationKind.EXPANSION)
                    return edge, explanation

        edge = random.choice(available_edges)
        explanation = self._build_initial_road_explanation(
            edge, target_vertex=None, explanation_kind=RoadExplanationKind.FLEXIBLE)
        return edge, explanation

    @staticmethod
    def vertex_utility(
            vertex: Vertex, player: Player, game: Game, available_vertices: List[Vertex],
            first_settlement: bool = True) -> float:
        """Compute utility score for a vertex as a potential settlement location."""
        if not vertex.hexes:
            return float("-inf")

        # Expected resource yield from adjacent hexes (dice probability weighted).
        dice_sum = sum(dice_probability(h.production_number) for h in vertex.hexes)

        # Count distinct resource types for early-game flexibility.
        resources = {h.resource for h in vertex.hexes if h.resource is not None}
        diversity = len(resources)

        # Estimate how much this vertex blocks opponent expansion.
        sim_game = make_sim_game_for_player(game, player)
        blocking_penalty = 1.0

        for opp in game.players:
            if opp == player:
                continue

            for opp_v in opp.settlements:
                reachable = get_reachable_vertices(
                    start_vertex=opp_v, player_number=opp.player_number, sim_game=sim_game,
                    available_vertices=available_vertices)
                # If an opponent could reasonably reach this spot, blocking value is low.
                if vertex in reachable:
                    blocking_penalty = 0.0
                    break

            if blocking_penalty == 0.0:
                break

        # Base utility: yield + diversity, with an optional blocking component.
        utility = (StrategyWeights.INIT_PLACE_YIELD * dice_sum + StrategyWeights.INIT_PLACE_DIVERSITY * diversity
                   - StrategyWeights.INIT_PLACE_BLOCK * blocking_penalty)

        # For the second settlement, reward complementary resources across both placements.
        if not first_settlement:
            first_resources = {h.resource for s in player.settlements for h in s.hexes if h.resource is not None}
            combined_diversity = len(resources | first_resources)
            utility += StrategyWeights.INIT_PLACE_DIVERSITY * (combined_diversity - diversity)

        return utility

    def _build_initial_settlement_explanation(
            self, player: Player, vertex: Vertex, best_score: float, second_score: float) -> ActionExplanation:
        first_settlement = len(player.settlements) == 0
        reasons_for = self._initial_settlement_reasons(player, vertex, first_settlement)

        action = Action(ActionType.BUILD, (Buildable.SETTLEMENT, vertex))
        candidate = CandidateExplanation(
            action=action, full_plan=[action], reasons_for=reasons_for,
            metadata={"template": ExplanationTemplate.INITIAL_SETTLEMENT, "target_vertex": vertex, "port": vertex.port})
        return ActionExplanation(
            chosen_action=action, chosen_candidate=candidate, confidence=max(0.0, best_score - second_score),
            confidence_label=confidence_label(max(0.0, best_score - second_score)))

    def _build_initial_road_explanation(
            self, edge: Edge, target_vertex: Optional[Vertex],
            explanation_kind: RoadExplanationKind) -> ActionExplanation:
        reasons_for = self._initial_road_reasons(target_vertex, explanation_kind)
        visual_plan: List[Tuple[Buildable, object]] = [(Buildable.ROAD, edge)]
        if target_vertex is not None and explanation_kind == RoadExplanationKind.EXPANSION:
            visual_plan.append((Buildable.SETTLEMENT, target_vertex))

        action = Action(ActionType.BUILD, (Buildable.ROAD, edge))
        candidate = CandidateExplanation(
            action=action, full_plan=[action], reasons_for=reasons_for,
            metadata={"template": ExplanationTemplate.INITIAL_ROAD, "target_vertex": target_vertex,
                      "road_explanation_kind": explanation_kind, "visual_plan": visual_plan})
        return ActionExplanation(
            chosen_action=action, chosen_candidate=candidate, confidence=1.0,
            confidence_label=(
                "high" if target_vertex is not None or explanation_kind == RoadExplanationKind.CONNECTION else "medium"
            ))

    def _initial_settlement_reasons(
            self, player: Player, vertex: Vertex, first_settlement: bool) -> List[Reason]:
        reasons: List[Reason] = []
        resources = {hex_tile.resource for hex_tile in vertex.hexes if hex_tile.resource is not None}
        total_yield = sum(dice_probability(hex_tile.production_number) for hex_tile in vertex.hexes)
        high_yield_count = sum(1 for hex_tile in vertex.hexes if hex_tile.production_number in (6, 8))

        if total_yield > 0:
            reasons.append(Reason(ReasonType.IMPROVES_PRODUCTION, ReasonLabel.INIT_EARLY_PRODUCTION, total_yield))

        if len(resources) >= 2:
            reasons.append(
                Reason(ReasonType.IMPROVES_RESOURCE_DIVERSITY, ReasonLabel.INIT_RESOURCE_DIVERSITY,
                       float(len(resources))))

        if high_yield_count > 0:
            reasons.append(
                Reason(ReasonType.FASTEST_PROGRESS, ReasonLabel.INIT_HIGH_FREQUENCY, float(high_yield_count)))

        if vertex.port is not None:
            reasons.append(
                Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.INIT_PORT_ACCESS, 1.0, {"port": vertex.port}))

        if not first_settlement:
            first_resources = {
                hex_tile.resource for settlement in player.settlements for hex_tile in settlement.hexes
                if hex_tile.resource is not None
            }
            combined_resources = resources | first_resources
            if len(combined_resources) > len(first_resources):
                reasons.append(
                    Reason(ReasonType.IMPROVES_RESOURCE_DIVERSITY, ReasonLabel.INIT_COMPLEMENTS_FIRST,
                           float(len(combined_resources))))

        reasons.sort(key=lambda reason: reason.value, reverse=True)
        return reasons

    def _initial_road_reasons(
            self, target_vertex: Optional[Vertex], explanation_kind: RoadExplanationKind) -> List[Reason]:
        reasons: List[Reason] = []

        if explanation_kind == RoadExplanationKind.CONNECTION:
            reasons.append(Reason(ReasonType.ENABLES_EXPANSION, ReasonLabel.INIT_ROAD_CONNECTION, 2.0))
        elif target_vertex is not None:
            reasons.append(Reason(ReasonType.ENABLES_EXPANSION, ReasonLabel.INIT_ROAD_TO_SETTLEMENT, 2.0))
            reasons.append(Reason(ReasonType.IMPROVES_RESOURCE_DIVERSITY, ReasonLabel.INIT_ROAD_TO_BALANCE, 1.0))
        else:
            reasons.append(Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.INIT_ROAD_FLEXIBLE, 1.0))

        return reasons

    def choose_trade_partner(
            self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount,
            available_players: List[Tuple[Player, Optional[ResourceCount]]]) -> Optional[
            Tuple[Player, Optional[ResourceCount]]]:
        """Return the chosen trade partner using ETW-based selection."""
        selection, _ = self.choose_trade_partner_with_explanation(player, game, selling, buying, available_players)
        return selection

    def choose_trade_partner_with_explanation(
            self, player: Player, game: Game, selling: ResourceCount, buying: ResourceCount,
            available_players: List[Tuple[Player, Optional[ResourceCount]]]) -> Tuple[
            Optional[Tuple[Player, Optional[ResourceCount]]], Optional[ActionExplanation]]:
        """Return the chosen trade partner and a structured explanation."""

        # Build a lightweight simulated view of the game (we know our own hand, opponents are hidden-info).
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)
        available_sim_players = [(SimPlayerState(p, opponent=True), offer) for (p, offer) in available_players]

        # Pick the partner (and optional counter-offer) that improves our ETW without helping the leader too much.
        selection = select_best_trade_partner(
            player_sim=sim_us, sim_game=sim_game, etw_estimator=self.etw_estimator, selling_orig=selling,
            buying=buying, available_players=available_sim_players)

        if selection is None:
            return None, None

        # Map back from SimPlayerState to the real Player object for the engine.
        chosen_sim_player, counter = selection
        chosen_player = next(p for p in game.players if p.player_number == chosen_sim_player.player_number)
        explanation = self._build_trade_partner_explanation(
            player, sim_us, sim_game, selling, buying, available_players, chosen_player, counter)
        return (chosen_player, counter), explanation

    def select_robber_target(
            self, player: Player, game: Game, valid_hexes: List[HexTile]) -> Tuple[HexTile, Optional[Player]]:
        """Select which hex tile to place the robber on, prioritising opponents' resources."""
        best_score = float("-inf")
        best_hex: Optional[HexTile] = None

        # Used to avoid blocking ourselves unless it's clearly worth it.
        our_resource_tiles = {h for v in (player.settlements + player.cities) for h in v.hexes}

        sim_game_for_robber = make_sim_game_for_player(game, player)

        # Diversion: if we're (at least) tied for the VP lead, lean into blocking whoever looks strongest.
        our_vp = player.calc_victory_points()[0]
        opp_vps = [p.calc_victory_points()[0] for p in game.players if p != player]
        best_opp_vp = max(opp_vps, default=0)
        diversion_boost = StrategyWeights.DIVERSION_BOOST if our_vp >= best_opp_vp else 1.0

        # For each opponent, estimate which resources matter most to their next "best" action.
        opponent_importance: Dict[PlayerNumber, Dict[Resource, float]] = {}
        for opponent in game.players:
            if opponent == player:
                continue

            sim_game_opp = make_sim_game_for_player(game, opponent)
            best_action = self.etw_estimator.calculate_best_game_action(
                sim_game=sim_game_opp, player_number=opponent.player_number, dev_played=False,
                ignore_affordability=True, ignore_opponents=True)

            required = calc_step_resources(best_action)
            total = sum(required.values())
            opponent_importance[opponent.player_number] = (
                {res: amt / total for res, amt in required.items() if amt > 0} if total > 0 else {}
            )

        # Score each candidate robber hex by (production probability * how important the resource is * opponent VP).
        for h in valid_hexes:
            players_on_h = [p for p in game.get_players_on_hex(h) if p != player]
            if not players_on_h:
                continue

            score = 0.0
            for p in players_on_h:
                score += score_hex_for_opponent(
                    opponent_number=p.player_number, sim_game=sim_game_for_robber, hex_tile=h,
                    importance=opponent_importance.get(p.player_number, {})) * (
                                 p.calc_victory_points()[0] * diversion_boost)

            # Prefer not to rob our own production unless the blocking value is high.
            if h in our_resource_tiles:
                score *= StrategyWeights.ROBBER_OWN_HEX_PENALTY

            if score > best_score:
                best_score = score
                best_hex = h

        # Fallback if no hex has opponents on it.
        if best_hex is None:
            best_hex = random.choice(valid_hexes)

        # Choose who to steal from on the chosen hex (more resources + more VP = better target).
        players_on_best_hex = [p for p in game.get_players_on_hex(best_hex) if p != player]
        if not players_on_best_hex:
            return best_hex, None

        best_player = max(players_on_best_hex, key=lambda pl: sum(pl.resources.values()) * pl.calc_victory_points()[0])
        return best_hex, best_player

    def select_discard_resources(self, player: Player, game: Game, num_resources: int) -> ResourceCount:
        """Select resources to discard, keeping critical ones for best next action."""
        have = player.resources.copy()

        # Estimate what we are trying to build next and protect those resources.
        sim_game = make_sim_game_for_player(game, player)
        best_action = self.etw_estimator.calculate_best_game_action(
            sim_game=sim_game, player_number=player.player_number, dev_played=False)

        needed = calc_step_resources(best_action)

        # Surplus = resources beyond what is needed for the next action.
        surplus = {r: max(0, have[r] - needed.get(r, 0)) for r in have}
        discard = {r: 0 for r in have}
        remaining = num_resources

        while remaining > 0:
            # Prefer discarding true surplus first, otherwise discard low-impact resources.
            # Ore and wheat are implicitly protected since they enable cities and dev cards.
            r = min(have.keys(), key=lambda x: (surplus[x] <= 0, have[x], x in (Resource.ORE, Resource.WHEAT)))
            discard[r] += 1
            have[r] -= 1

            if surplus[r] > 0:
                surplus[r] -= 1

            remaining -= 1

        return discard

    def select_year_of_plenty_resources(self, player: Player, game: Game) -> ResourceCount:
        """Select the most-needed resources for the player's next action."""
        # Look ahead to what we want to build next.
        sim_game = make_sim_game_for_player(game, player)
        best_action = self.etw_estimator.calculate_best_game_action(
            sim_game=sim_game, player_number=player.player_number, dev_played=False)

        needed = calc_step_resources(best_action)

        # Rank resources by how short we are relative to the next action's cost.
        sorted_needed = sorted(needed, key=lambda r: max(0, needed[r] - player.resources[r]), reverse=True)

        # Take the two most constraining resources, fall back to anything if fewer are needed.
        picked = sorted_needed[:2] + [r for r in Resource if r not in sorted_needed][: max(0, 2 - len(sorted_needed))]

        return {r: 1 for r in picked[:2]}

    def select_monopoly_resource(self, player: Player, game: Game) -> Resource:
        """Select the resource that will most hurt opponents based on their likely next actions."""

        # Count how often each resource appears in opponents' next planned actions.
        need_counts: Dict[Resource, int] = {r: 0 for r in Resource}

        for opponent in game.players:
            if opponent == player:
                continue

            # Estimate what the opponent is trying to do next.
            sim_game_opp = make_sim_game_for_player(game, opponent)
            best_action = self.etw_estimator.calculate_best_game_action(
                sim_game=sim_game_opp, player_number=opponent.player_number, dev_played=False,
                ignore_affordability=True, ignore_opponents=True)

            # Tally required resources for that action.
            required = calc_step_resources(best_action)
            for r, amt in required.items():
                if amt > 0:
                    need_counts[r] += 1

        # Pick the resource most commonly needed across opponents.
        max_count = max(need_counts.values())
        candidates = [r for r, c in need_counts.items() if c == max_count]
        return random.choice(candidates)

    def respond_to_trade(
            self, player: Player, game: Game, opponent: Player, selling: ResourceCount,
            buying: ResourceCount) -> Tuple[bool, Optional[ResourceCount]]:
        """Respond to a proposed trade using BATNA + risk constraints."""
        accepted, counter, _ = self.respond_to_trade_with_explanation(player, game, opponent, selling, buying)
        return accepted, counter

    def respond_to_trade_with_explanation(
            self, player: Player, game: Game, opponent: Player, selling: ResourceCount,
            buying: ResourceCount) -> Tuple[bool, Optional[ResourceCount], Optional[ActionExplanation]]:
        """Respond to a proposed trade and return a structured explanation."""

        # Evaluate the offer in a simulated state.
        sim_game = make_sim_game_for_player(game, player)
        sim_us = sim_game.overlay.get_sim_player(player.player_number)

        # Represent the proposer as a hidden-information opponent for conservative scoring.
        opponent_sim = SimPlayerState(opponent, opponent=True)
        opponents = get_opponents(sim_game, player.player_number)

        # Accept if it improves our ETW versus waiting/bank trades, but avoid helping a close/leading opponent.
        accepted, counter = respond_to_trade_batna(
            player_sim=sim_us, opponent_sim=opponent_sim, sim_game=sim_game, etw_estimator=self.etw_estimator,
            selling_to_us=selling, buying_from_us=buying, opponents=opponents)
        explanation = self._build_trade_response_explanation(
            player, opponent, sim_us, opponent_sim, sim_game, selling, buying, opponents, accepted, counter)
        return accepted, counter, explanation

    def _build_trade_partner_explanation(
            self, player: Player, sim_us: SimPlayerState, sim_game, selling: ResourceCount, buying: ResourceCount,
            available_players: List[Tuple[Player, Optional[ResourceCount]]], chosen_player: Player,
            counter: Optional[ResourceCount]) -> ActionExplanation:
        batna_etw = self.etw_estimator.estimated_time_to_win(
            sim_us, sim_game, False, include_player_trades=False)
        candidate_explanations: List[CandidateExplanation] = []

        all_sims = [sim_us] + [SimPlayerState(opp, opponent=True) for opp, _ in available_players]
        etw_by_player = {
            sim_player: self.etw_estimator.estimated_time_to_win(
                sim_player.copy(), sim_game, False, include_player_trades=False)
            for sim_player in all_sims
        }
        leading_sim = min(etw_by_player, key=etw_by_player.get)

        for opponent, offered_counter in available_players:
            opp_sim = SimPlayerState(opponent, opponent=True)
            payment = offered_counter if offered_counter is not None else selling
            if any(sim_us.resources.get(resource, 0) < amount for resource, amount in payment.items()):
                continue

            sim_after = sim_us.copy()
            sim_after.remove_resources(payment)
            sim_after.add_resources(buying)
            sim_game_after = make_sim_game_for_player(sim_game.game, player)
            sim_game_after.overlay.set_sim_player(sim_after)
            etw_after = self.etw_estimator.estimated_time_to_win(
                sim_after, sim_game_after, False, include_player_trades=False)
            delta_ai = batna_etw - etw_after
            if delta_ai <= 0:
                continue

            etw_opp_before = self.etw_estimator.estimated_time_to_win(
                opp_sim, sim_game, False, include_player_trades=False)
            sim_opp_after = opp_sim.copy()
            sim_opp_after.add_resources(payment)
            sim_opp_after.remove_resources(buying)
            sim_game_opp_after = make_sim_game_for_player(sim_game.game, player)
            sim_game_opp_after.overlay.set_sim_player(sim_opp_after)
            etw_opp_after = self.etw_estimator.estimated_time_to_win(
                sim_opp_after, sim_game_opp_after, False, include_player_trades=False)
            delta_opp = max(0.0, etw_opp_before - etw_opp_after)

            is_leader = opp_sim == leading_sim
            vp_gap = opp_sim.victory_points() - sim_us.victory_points()
            is_close = vp_gap >= -StrategyWeights.CLOSE_OPPONENT_VP_GAP
            lambda_risk = StrategyWeights.LAMBDA_RISK_LEADER if is_leader else StrategyWeights.LAMBDA_RISK_BASE
            if (is_close or is_leader) and delta_opp >= lambda_risk * delta_ai:
                continue

            reasons_for = [
                Reason(ReasonType.FASTEST_PROGRESS, ReasonLabel.TRADE_PARTNER_BEST_ETW, delta_ai),
            ]
            if offered_counter is not None:
                saved_resources = max(0.0, float(sum(selling.values()) - sum(payment.values())))
                reasons_for.append(
                    Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.TRADE_PARTNER_COUNTER_VALUE, saved_resources))
            if is_close or is_leader:
                safety_margin = max(0.0, lambda_risk * delta_ai - delta_opp)
                reasons_for.append(
                    Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.TRADE_PARTNER_SAFE_OPPONENT, safety_margin))

            action = Action(ActionType.TRADE_WITH_PLAYER, (payment, buying))
            candidate_explanations.append(CandidateExplanation(
                action=action,
                full_plan=[action],
                etw_before=batna_etw,
                etw_after=etw_after,
                etw_delta=delta_ai,
                utility_total=batna_etw - etw_after - (StrategyWeights.TRADE_LEADER_PENALTY if is_leader else 0.0),
                reasons_for=reasons_for,
                metadata={
                    "template": ExplanationTemplate.TRADE_PARTNER,
                    "partner_name": opponent.name,
                    "partner_player_number": opponent.player_number,
                    "payment": payment,
                    "buying": buying,
                },
            ))

        candidate_explanations.sort(key=lambda candidate: candidate.utility_total, reverse=True)
        chosen_candidate = next((
            candidate for candidate in candidate_explanations
            if candidate.metadata.get("partner_player_number") == chosen_player.player_number
            and candidate.metadata.get("payment") == (counter if counter is not None else selling)
        ), None)
        if chosen_candidate is None:
            action = Action(ActionType.TRADE_WITH_PLAYER, ((counter if counter is not None else selling), buying))
            chosen_candidate = CandidateExplanation(
                action=action,
                full_plan=[action],
                reasons_for=[Reason(
                    ReasonType.HEURISTIC_CHOICE, ReasonLabel.TRADE_PARTNER_BEST_ETW, 0.0)],
                metadata={
                    "template": ExplanationTemplate.TRADE_PARTNER,
                    "partner_name": chosen_player.name,
                    "partner_player_number": chosen_player.player_number,
                    "payment": counter if counter is not None else selling,
                    "buying": buying,
                },
            )
            candidate_explanations.insert(0, chosen_candidate)
        alternatives = [
            candidate for candidate in candidate_explanations
            if candidate is not chosen_candidate
        ][:3]
        confidence = chosen_candidate.utility_total - (
            alternatives[0].utility_total if alternatives else 0.0
        )
        return ActionExplanation(
            chosen_action=chosen_candidate.action,
            chosen_candidate=chosen_candidate,
            alternatives=alternatives,
            confidence=max(0.0, confidence),
            confidence_label=confidence_label(max(0.0, confidence)),
            metadata={"template": ExplanationTemplate.TRADE_PARTNER},
        )

    def _build_trade_response_explanation(
            self, player: Player, opponent: Player, sim_us: SimPlayerState, opponent_sim: SimPlayerState, sim_game,
            selling_to_us: ResourceCount, buying_from_us: ResourceCount, opponents: List[SimPlayerState],
            accepted: bool, counter: Optional[ResourceCount]) -> ActionExplanation:
        etw_before = self.etw_estimator.estimated_time_to_win(
            sim_us, sim_game, False, include_player_trades=False)

        offered_after = sim_us.copy()
        offered_after.add_resources(selling_to_us)
        offered_after.remove_resources(buying_from_us)
        offered_game = make_sim_game_for_player(sim_game.game, player)
        offered_game.overlay.set_sim_player(offered_after)
        etw_after_offer = self.etw_estimator.estimated_time_to_win(
            offered_after, offered_game, False, include_player_trades=False)
        delta_offer = etw_before - etw_after_offer

        all_players = [sim_us, *opponents]
        etw_by_player = {
            sim_player: self.etw_estimator.estimated_time_to_win(
                sim_player.copy(), sim_game, False, include_player_trades=False)
            for sim_player in all_players
        }
        leading = min(etw_by_player, key=etw_by_player.get)
        is_leader = opponent_sim == leading
        vp_gap = opponent_sim.victory_points() - sim_us.victory_points()
        is_close = vp_gap >= -StrategyWeights.CLOSE_OPPONENT_VP_GAP
        lambda_risk = StrategyWeights.LAMBDA_RISK_LEADER if is_leader else StrategyWeights.LAMBDA_RISK_BASE

        opp_before = self.etw_estimator.estimated_time_to_win(
            opponent_sim, sim_game, False, include_player_trades=False)
        opp_after_offer = opponent_sim.copy()
        opp_after_offer.remove_resources(selling_to_us)
        opp_after_offer.add_resources(buying_from_us)
        opp_game = make_sim_game_for_player(sim_game.game, player)
        opp_game.overlay.set_sim_player(opp_after_offer)
        opp_after = self.etw_estimator.estimated_time_to_win(
            opp_after_offer, opp_game, False, include_player_trades=False)
        delta_opp_offer = max(0.0, opp_before - opp_after)

        decision = "reject"
        payment = buying_from_us
        reasons_for: List[Reason] = []
        chosen_action = Action(ActionType.TRADE_WITH_PLAYER, (payment, selling_to_us))
        etw_after = etw_after_offer
        etw_delta = delta_offer

        if accepted and counter is None:
            decision = "accept"
            reasons_for.append(Reason(ReasonType.FASTEST_PROGRESS, ReasonLabel.TRADE_RESPONSE_ACCEPT_VALUE,
                                      delta_offer))
            if is_close or is_leader:
                reasons_for.append(Reason(
                    ReasonType.HEURISTIC_CHOICE, ReasonLabel.TRADE_PARTNER_SAFE_OPPONENT,
                    max(0.0, lambda_risk * delta_offer - delta_opp_offer)))
        elif accepted and counter is not None:
            decision = "counter"
            chosen_action = Action(ActionType.TRADE_WITH_PLAYER, (counter, selling_to_us))
            counter_after = sim_us.copy()
            counter_after.add_resources(selling_to_us)
            counter_after.remove_resources(counter)
            counter_game = make_sim_game_for_player(sim_game.game, player)
            counter_game.overlay.set_sim_player(counter_after)
            etw_after = self.etw_estimator.estimated_time_to_win(
                counter_after, counter_game, False, include_player_trades=False)
            etw_delta = etw_before - etw_after
            reasons_for.append(
                Reason(ReasonType.FASTEST_PROGRESS, ReasonLabel.TRADE_RESPONSE_COUNTER_VALUE, etw_delta))
        else:
            if delta_offer <= 0:
                reasons_for.append(
                    Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.TRADE_RESPONSE_REJECT_NO_GAIN, abs(delta_offer)))
            else:
                reasons_for.append(
                    Reason(ReasonType.HEURISTIC_CHOICE, ReasonLabel.TRADE_RESPONSE_REJECT_RISK, delta_opp_offer))

        candidate = CandidateExplanation(
            action=chosen_action,
            full_plan=[chosen_action],
            etw_before=etw_before,
            etw_after=etw_after,
            etw_delta=etw_delta,
            utility_total=max(0.0, etw_delta),
            reasons_for=reasons_for,
            metadata={
                "template": ExplanationTemplate.TRADE_RESPONSE,
                "decision": decision,
                "opponent_name": opponent.name,
                "selling_to_us": selling_to_us,
                "payment": buying_from_us,
                "counter_payment": counter,
            },
        )
        return ActionExplanation(
            chosen_action=chosen_action,
            chosen_candidate=candidate,
            confidence=max(0.0, etw_delta),
            confidence_label=confidence_label(max(0.0, etw_delta)),
            metadata={"template": ExplanationTemplate.TRADE_RESPONSE},
        )

    def road_building_placement(
            self, player: Player, game: Game, available_edges: List[Edge]) -> Optional[Edge]:
        """Select an edge for road building, prioritising network connections or high-utility settlements."""
        sim_game = make_sim_game_for_player(game, player)

        # First priority: connect isolated road segments or attach roads back to our structures.
        connecting_edge = find_gap_connection(player.player_number, sim_game, available_edges)
        if connecting_edge:
            return connecting_edge

        # Otherwise, push roads toward the best available settlement expansion spot.
        legal_vertices = get_legal_settlement_vertices(sim_game)
        if legal_vertices:
            best_vertex = max(
                legal_vertices,
                key=lambda v: self.vertex_utility(v, player, game, legal_vertices, first_settlement=False),
                default=None)
            if best_vertex:
                return find_edge_toward_vertex_from_any(player.player_number, sim_game, best_vertex, available_edges)

        # Fallback: keep the agent moving even if no clear preference exists.
        return random.choice(available_edges) if available_edges else None

    def next_action_with_explanation(
            self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Tuple[Action, ActionExplanation]:
        """Determine the next action and return a structured explanation."""
        if phase == Phase.PRE_ROLL:
            if not dev_played:
                sim_game = make_sim_game_for_player(game, player)
                sim_us = sim_game.overlay.get_sim_player(player.player_number)

                dev_candidates = play_development_card_action(sim_us, sim_game)

                if dev_candidates:
                    etw_before = self.etw_estimator.estimated_time_to_win(sim_us.copy(), sim_game, dev_played)

                    opponents_etw_before: Dict[PlayerNumber, float] = {
                        opp.player_number: self.etw_estimator.estimated_time_to_win(opp.copy(), sim_game, False)
                        for opp in get_opponents(sim_game, player.player_number)
                    }

                    explained_candidates = self.etw_estimator.evaluate_candidates_with_explanations(
                        sim_us, sim_game, dev_played, dev_candidates, etw_before, opponents_etw_before)

                    if explained_candidates:
                        best_candidate = explained_candidates[0]
                        if best_candidate.utility_total > 0.0:
                            confidence = best_candidate.utility_total - (
                                explained_candidates[1].utility_total if len(explained_candidates) > 1 else 0.0)
                            explanation = ActionExplanation(
                                chosen_action=best_candidate.action, chosen_candidate=best_candidate,
                                alternatives=explained_candidates[1:4], confidence=max(0.0, confidence),
                                confidence_label=confidence_label(max(0.0, confidence)),
                                assumptions=[AssumptionCode.PRE_ROLL_DEV_ONLY], metadata={"phase": "pre_roll"})
                            return best_candidate.action, explanation

            roll_action = Action(ActionType.ROLL)
            explanation = ActionExplanation(
                chosen_action=roll_action,
                chosen_candidate=CandidateExplanation(
                    action=roll_action, full_plan=[roll_action],
                    reasons_for=[Reason(type=ReasonType.HEURISTIC_CHOICE, label=ReasonLabel.PRE_ROLL_NO_DEV_PLAY,
                                        value=0.0)]),
                alternatives=[], confidence=0.0, confidence_label="medium", assumptions=[],
                metadata={"phase": "pre_roll"})
            return roll_action, explanation

        sim_game = make_sim_game_for_player(game, player)

        explanation = self.etw_estimator.calculate_best_game_action_with_explanation(
            sim_game=sim_game, player_number=player.player_number, dev_played=dev_played)

        best_action = explanation.chosen_action

        if best_action.type == ActionType.TRADE_WITH_PLAYER:
            self.etw_estimator._last_trade_proposed = True
            self.etw_estimator._last_trade_resources = player.resources.copy()
        else:
            self.etw_estimator._last_trade_proposed = False
            self.etw_estimator._last_trade_resources = None

        return best_action, explanation

    def next_action(self, player: Player, game: Game, phase: Phase, dev_played: bool) -> Action:
        """Determine the next action to take for the current phase of the game."""
        action, _ = self.next_action_with_explanation(player, game, phase, dev_played)
        return action
