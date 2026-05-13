from dataclasses import dataclass
from random import Random
from typing import List, Tuple, Optional, Dict, Callable, Any, TypeVar

from ai.RuleBasedAI import RuleBasedAI
from ai.actions import Action, ActionType, Phase
from ai.tutor.explanations import ActionExplanation
from ai.tutor.evaluator import TutorEvaluator
from ai.tutor.feedback import TutorFeedbackExplanation
from ai.tutor.tutor import TutorStage
from config.view_constants import AI_DECISION_ANIMATION_DELAY, AI_DECISION_ANIMATION_DELAY_SIMULATION_MODE, \
    SHOW_AI_BUILT_LOCATIONS
from game.Edge import Edge, EdgeDirection
from game.Game import Game, PlayerConfig
from game.HexTile import HexTile
from game.Player import Player, PlayerNumber
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import ResourceCount, Resource
from game.Vertex import Vertex, Port, VertexDirection
from view.board_display_source import BoardDisplaySource
from view.View import View, GameMode
from view.display_utils import resource_dict_to_str

START_LAST = False
MAX_AI_ACTION_REQUESTS_PER_TURN = 200


class ReturnToStart(Exception):
    pass


T = TypeVar("T")


class AITurnActionLimitExceeded(Exception):
    def __init__(self, player_name: str, request_count: int, phase: Phase):
        self.player_name = player_name
        self.request_count = request_count
        self.phase = phase
        super().__init__(
            f"AI action request limit exceeded for {player_name} after {request_count} requests in {phase.name}."
        )


@dataclass(frozen=True)
class PlayerScoreSnapshot:
    total_vp: int
    visible_vp: int
    settlements: int
    cities: int
    hidden_vp_cards: int
    longest_road_length: int
    army_size: int
    has_longest_road: bool
    has_largest_army: bool


class GameController(BoardDisplaySource):
    """Controls the flow of a Catan game using a pure Game model."""
    _game: Game
    game_mode = GameMode.PLAY

    def __init__(self, game_players: PlayerConfig, simulation_players: PlayerConfig, game_seed: Optional[int] = None):
        self.view: View | None = None
        self.game_players = game_players
        self.simulation_players = simulation_players
        self.game_seed = game_seed
        self.game_rng = Random(game_seed)
        self.victory_point_history: List[Tuple[int, Dict[PlayerNumber, int]]] = []
        self.endgame_review_history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]] = []
        self.tutor_feedback_history: List[TutorFeedbackExplanation] = []
        self.round_limit_reached = False
        self.ai_action_limit_reached = False
        self._tutor_dev_played = False
        self._pending_tutor_robber_choice: Optional[Tuple[HexTile, Optional[Player]]] = None
        self.tutor_ai = self._new_tutor_ai()
        self.tutor_evaluator = TutorEvaluator(self.tutor_ai, lambda: self.game_rng.getstate())
        self.reset_game()

    def _new_tutor_rng(self) -> Random:
        """Use a dedicated RNG so tutor previews do not perturb live game randomness."""
        return Random(self.game_seed)

    def _new_tutor_ai(self) -> RuleBasedAI:
        tutor_rng = self._new_tutor_rng()
        human_player_numbers = [
            player_number
            for player_number, policy_cls in self.game_players.items()
            if policy_cls is None
        ]
        for player_number in human_player_numbers:
            policy_factory = self.simulation_players.get(player_number)
            if policy_factory is None:
                continue
            tutor_policy = policy_factory(tutor_rng)
            if isinstance(tutor_policy, RuleBasedAI):
                return tutor_policy
        return RuleBasedAI(tutor_rng)

    def _sync_tutor_ai_rng_to_game_state(self) -> None:
        self.tutor_ai.rng.setstate(self.game_rng.getstate())

    def _commit_tutor_ai_rng_to_game_state(self) -> None:
        self.game_rng.setstate(self.tutor_ai.rng.getstate())

    def _run_tutor_decision(self, callback: Callable[[], T]) -> T:
        self._sync_tutor_ai_rng_to_game_state()
        result = callback()
        self._commit_tutor_ai_rng_to_game_state()
        return result

    def _run_tutor_preview(self, callback: Callable[[], T]) -> T:
        snapshot = self.tutor_ai.snapshot_state()
        try:
            self._sync_tutor_ai_rng_to_game_state()
            return callback()
        finally:
            self.tutor_ai.restore_state(snapshot)

    def _resolve_player_config(self) -> PlayerConfig:
        """Choose the active player config for the current game mode."""
        if self.game_mode == GameMode.PLAY:
            return self.game_players

        if self.game_mode == GameMode.TUTOR:
            players = dict(self.simulation_players)
            for player_number, policy_cls in self.game_players.items():
                if policy_cls is None:
                    players[player_number] = None
            return players

        if self.game_mode in {GameMode.SIMULATION, GameMode.GUIDED}:
            return self.simulation_players

        return self.game_players

    def _raise_if_view_requested_home(self) -> None:
        if self.view is None:
            return

        if self.view.consume_return_home_request():
            raise ReturnToStart

    def reset_game(self):
        """Reset the game to a fresh state and reset round counter."""
        uses_interactive_delay = self.game_mode in {GameMode.PLAY, GameMode.TUTOR}
        is_tutor_mode = self.game_mode in {GameMode.GUIDED, GameMode.TUTOR}

        self.game_rng = Random(self.game_seed)
        self.victory_point_history = []
        self.endgame_review_history = []
        self.tutor_feedback_history = []
        self.round_limit_reached = False
        self.ai_action_limit_reached = False
        self._tutor_dev_played = False
        self._pending_tutor_robber_choice = None
        self.tutor_ai = self._new_tutor_ai()
        self.tutor_evaluator = TutorEvaluator(self.tutor_ai, lambda: self.game_rng.getstate())
        self._game = Game(self._resolve_player_config(), self.game_rng)

        if self.view:
            self.view.ai_decision_animation_delay = (
                AI_DECISION_ANIMATION_DELAY if uses_interactive_delay
                else AI_DECISION_ANIMATION_DELAY_SIMULATION_MODE
            )
            self.view.open_tutor_menu(is_tutor_mode)

    def _show_tutor_init(
            self,
            player: Player,
            stage: TutorStage,
            explanation: Optional[ActionExplanation],
    ) -> None:
        if self.game_mode == GameMode.TUTOR and player.is_human and explanation is not None:
            self.view.display_tutor_init(player, stage, explanation)

    def _should_collect_tutor_feedback(self, player: Player) -> bool:
        return player.is_human and self.game_mode in {GameMode.PLAY, GameMode.TUTOR}

    def _should_show_tutor_feedback(self, player: Player) -> bool:
        return self.view is not None and player.is_human and self.game_mode == GameMode.TUTOR

    def get_tutor_turn_explanation(
            self,
            player: Player,
            played_dev_card: Optional[bool] = None,
    ) -> Optional[ActionExplanation]:
        if self.game_mode != GameMode.TUTOR or not player.is_human:
            return None
        if played_dev_card is None:
            played_dev_card = self._tutor_dev_played
        _, explanation = self._run_tutor_preview(lambda: self.tutor_ai.next_action_with_explanation(
            player,
            self._game,
            phase=Phase.MAIN,
            dev_played=played_dev_card,
        ))
        return explanation

    def _preview_tutor_explanation(
            self,
            callback: Callable[[], tuple[Any, ...]],
    ) -> Optional[ActionExplanation]:
        preview_result = self._run_tutor_preview(callback)
        if not isinstance(preview_result, tuple) or len(preview_result) < 2:
            return None
        explanation = preview_result[-1]
        return explanation if isinstance(explanation, ActionExplanation) else None

    def _refresh_tutor_turn_explanation(self, player: Player) -> None:
        if self.game_mode != GameMode.TUTOR or not player.is_human or self.view is None:
            return

        explanation = self.get_tutor_turn_explanation(player)
        if explanation is not None:
            self.view.display_tutor_init(player, TutorStage.TURN_ACTION, explanation)

    def get_tutor_recommended_main_action(self, player: Player, played_dev_card: bool) -> Action:
        action, _ = self._run_tutor_decision(lambda: self.tutor_ai.next_action_with_explanation(
            player,
            self._game,
            phase=Phase.MAIN,
            dev_played=played_dev_card,
        ))
        return action

    def _set_tutor_shortcut_handlers(
            self,
            recommended_handler: Optional[Callable[[], Any]],
    ) -> None:
        if self.view is None:
            return
        if self.game_mode in {GameMode.PLAY, GameMode.TUTOR}:
            self.view.set_debug_tutor_shortcut_handler(recommended_handler)
        else:
            self.view.set_debug_tutor_shortcut_handler(None)

    def _prepare_tutor_main_action_comparison(
            self, player: Player, action: Action, played_dev_card: bool) -> Optional[TutorFeedbackExplanation]:
        if not self._should_collect_tutor_feedback(player):
            return None
        return self._run_tutor_preview(lambda: self.tutor_evaluator.evaluate_main_turn_action(
            player,
            self._game,
            Phase.MAIN,
            played_dev_card,
            action,
            title="Main Turn",
        ))

    def _show_tutor_action_feedback(self, player: Player, feedback: Optional[TutorFeedbackExplanation]) -> None:
        if feedback is None or not self._should_collect_tutor_feedback(player):
            return
        self.tutor_feedback_history.append(feedback)
        if self._should_show_tutor_feedback(player):
            self.view.display_tutor_action_feedback(feedback)

    def _get_tutor_recommended_robber_choice(
            self,
            player: Player,
            valid_hexes: List[HexTile],
    ) -> Tuple[HexTile, Optional[Player]]:
        cached_choice = self._pending_tutor_robber_choice
        if cached_choice is not None and cached_choice[0] in valid_hexes:
            return cached_choice

        choice = self._run_tutor_decision(
            lambda: self.tutor_ai.select_robber_target(player, self._game, valid_hexes)
        )
        self._pending_tutor_robber_choice = choice
        return choice

    @staticmethod
    def _raise_if_return_home(value: object) -> None:
        if isinstance(value, Action) and value.type == ActionType.RETURN_HOME:
            raise ReturnToStart

    def start_game(self, max_rounds: Optional[int] = None):
        """Run initial placement, then loop turns until game over."""
        while True:
            self.game_mode = self.view.display_start_screen()
            self.reset_game()

            try:
                self.run_initial_placement()
                while not self._game.game_over:
                    for player in self._game.players:
                        if player.is_human:
                            self.make_round_move(player)
                        else:
                            self.make_round_move_ai(player)

                        # Set development cards to playable
                        for card in player.development_cards:
                            card.playable = card.card_type != DevelopmentCardType.VICTORY_POINT

                        if self._game.game_over:
                            break

                    self._record_victory_point_snapshot()

                    if self._game.game_over:
                        break

                    if max_rounds is not None and self._game.round_num >= max_rounds:
                        self.round_limit_reached = True
                        return

                    self._game.round_num += 1
            except AITurnActionLimitExceeded:
                self.ai_action_limit_reached = True
                return
            except ReturnToStart:
                continue

            self._record_victory_point_snapshot()
            self.view.display_results()
            return

    def _record_victory_point_snapshot(self) -> None:
        review_snapshot = {
            player.player_number: self._build_player_score_snapshot(player)
            for player in self._game.players
        }
        snapshot = {
            player_number: player_snapshot.total_vp
            for player_number, player_snapshot in review_snapshot.items()
        }
        round_num = self._game.round_num
        if self.victory_point_history and self.victory_point_history[-1] == (round_num, snapshot):
            return
        self.victory_point_history.append((round_num, snapshot))
        self.endgame_review_history.append((round_num, review_snapshot))

    @staticmethod
    def _build_player_score_snapshot(player: Player) -> PlayerScoreSnapshot:
        visible_vp, total_vp = player.calc_victory_points()
        return PlayerScoreSnapshot(
            total_vp=total_vp,
            visible_vp=visible_vp,
            settlements=len(player.settlements),
            cities=len(player.cities),
            hidden_vp_cards=total_vp - visible_vp,
            longest_road_length=player.longest_road_length,
            army_size=player.army_size,
            has_longest_road=player.has_longest_road,
            has_largest_army=player.has_largest_army,
        )

    def run_initial_placement(self):
        """
        Each player places two settlements and two roads in order:
        forward + reverse order for second placement.
        """
        players = self._game.players
        first, second = (reversed(players), players) if START_LAST else (players, reversed(players))
        players_order = ([(p, False) for p in first] + [(p, True) for p in second])

        for player, gain_resource in players_order:
            # Settlement
            vertices = self._game.get_available_vertices(player, Buildable.SETTLEMENT, road_restriction=False)
            if player.is_human:
                # Let human select position
                if self.game_mode == GameMode.TUTOR:
                    explanation = self._preview_tutor_explanation(
                        lambda: self.tutor_ai.select_initial_settlement_location_with_explanation(
                            player,
                            self._game,
                            vertices,
                        )
                    )
                    self.view.display_tutor_init(player, TutorStage.INITIAL_SETTLEMENT, explanation)
                self.view.display_board(player, "Select a position to build your settlement")

                def select_tutor_initial_settlement() -> Optional[Vertex]:
                    return self._run_tutor_decision(
                        lambda: self.tutor_ai.select_initial_settlement_location(player, self._game, vertices)
                    )

                self._set_tutor_shortcut_handlers(select_tutor_initial_settlement)
                try:
                    vertex: Vertex = self.view.draw_selectable_vertices(vertices)
                finally:
                    self._set_tutor_shortcut_handlers(None)
                self._raise_if_return_home(vertex)
                self.view.display_board()
            else:
                if self.game_mode == GameMode.GUIDED and isinstance(player.policy, RuleBasedAI):
                    vertex, explanation = player.policy.select_initial_settlement_location_with_explanation(
                        player,
                        self._game,
                        vertices,
                    )
                    if explanation is not None:
                        self._raise_if_return_home(self.view.display_board_turn_explanations(player, None, explanation))
                else:
                    self.view.display_board()
                    self.view.draw_selectable_vertices(vertices, disable_interactivity=True)
                    self.view.display_board_ai(player, "Select a position to build your settlement")
                    self._raise_if_view_requested_home()
                    vertex = player.policy.select_initial_settlement_location(player, self._game, vertices)
            opening_settlement_feedback = None
            if self._should_collect_tutor_feedback(player) and vertex is not None:
                opening_settlement_feedback = self.tutor_evaluator.evaluate_opening_settlement_choice(
                    player,
                    self._game,
                    vertices,
                    vertex,
                    title="Opening Settlement",
                )
            self._game.try_build_settlement(player, vertex, use_resources=False,
                                            road_restriction=False, gain_resources=gain_resource)
            self._show_tutor_action_feedback(player, opening_settlement_feedback)

            # Road
            available_edges = self._game.get_available_edges(player)
            if vertex is not None:
                available_edges = [edge for edge in available_edges if vertex in edge.vertices]
            if player.is_human:
                if self.game_mode == GameMode.TUTOR:
                    explanation = self._preview_tutor_explanation(
                        lambda: self.tutor_ai.select_initial_road_location_with_explanation(
                            player,
                            self._game,
                            available_edges,
                        )
                    )
                    self.view.display_tutor_init(player, TutorStage.INITIAL_ROAD, explanation)
                edge = self.get_road_choice(
                    player,
                    vertex,
                    selector=lambda candidate_edges: self.tutor_ai.select_initial_road_location(
                        player, self._game, candidate_edges
                    ),
                )
            else:
                edge = self.get_road_choice_ai(player, vertex)
            opening_road_feedback = None
            if self._should_collect_tutor_feedback(player) and edge is not None:
                opening_road_feedback = self.tutor_evaluator.evaluate_opening_road_choice(
                    player,
                    self._game,
                    available_edges,
                    edge,
                    title="Opening Road",
                )
            self._game.try_build_road(player, edge, use_resources=False)
            self._show_tutor_action_feedback(player, opening_road_feedback)

    def get_road_choice(
            self,
            player: Player,
            settlement: Optional[Vertex] = None,
            selector: Optional[Callable[[List[Edge]], Optional[Edge]]] = None,
    ) -> Edge:
        """Human selects an edge for initial road placement."""
        edges = self._game.get_available_edges(player)
        if settlement is not None:
            # Restrict edges to be directly connected to settlement
            edges = [edge for edge in edges if settlement in edge.vertices]

        self.view.display_board(player, "Select a position to build your road")
        if selector is None:
            selector = lambda candidate_edges: self.tutor_ai.select_initial_road_location(
                player, self._game, candidate_edges
            )

        def select_tutor_initial_road() -> Optional[Edge]:
            return self._run_tutor_decision(lambda: selector(edges))

        self._set_tutor_shortcut_handlers(select_tutor_initial_road)
        try:
            edge: Edge = self.view.draw_selectable_edges(edges)
        finally:
            self._set_tutor_shortcut_handlers(None)
        self._raise_if_return_home(edge)

        return edge

    def get_road_choice_ai(self, player: Player, settlement: Optional[Vertex] = None) -> Optional[Edge]:
        if settlement is None:
            available_edges = self._game.get_available_edges(player)
        else:
            available_edges = self._game.get_buildable_edges_for_vertex(settlement)

        if not available_edges:
            return None

        if self.game_mode == GameMode.GUIDED and isinstance(player.policy, RuleBasedAI):
            edge, explanation = player.policy.select_initial_road_location_with_explanation(
                player,
                self._game,
                available_edges,
            )
            if explanation is not None:
                self._raise_if_return_home(self.view.display_board_turn_explanations(player, None, explanation))
            return edge

        self.view.display_board()
        self.view.draw_selectable_edges(available_edges, disable_interactivity=True)
        self.view.display_board_ai(player, "Select a position to build your road")
        self._raise_if_view_requested_home()

        return player.policy.select_initial_road_location(player, self._game, available_edges)

    def trade_with_players(self, selling_player, selling, buying) -> List[Tuple[Player, Optional[ResourceCount]]]:
        """Sees which players are willing to trade"""
        results = []
        for player in self._game.players:
            if player != selling_player:
                if player.is_human:
                    if player.can_afford(buying):
                        if self.game_mode == GameMode.TUTOR:
                            explanation = self._preview_tutor_explanation(
                                lambda: self.tutor_ai.respond_to_trade_with_explanation(
                                    player,
                                    self._game,
                                    selling_player,
                                    selling,
                                    buying,
                                )
                            )
                            self._show_tutor_init(player, TutorStage.TRADE_RESPONSE, explanation)

                        def respond_to_trade_for_player() -> Tuple[bool, Optional[ResourceCount]]:
                            return self._run_tutor_decision(
                                lambda: self.tutor_ai.respond_to_trade(
                                    player,
                                    self._game,
                                    selling_player,
                                    selling,
                                    buying,
                                )
                            )

                        self._set_tutor_shortcut_handlers(respond_to_trade_for_player)
                        try:
                            trade_decision = self.view.display_trade_manager(player, selling, buying, selling_player)
                        finally:
                            self._set_tutor_shortcut_handlers(None)
                        self._raise_if_return_home(trade_decision)
                        interested, counter = trade_decision
                        if self._should_collect_tutor_feedback(player):
                            trade_response_feedback = self.tutor_evaluator.evaluate_trade_response_choice(
                                player,
                                self._game,
                                selling_player,
                                selling,
                                buying,
                                interested,
                                counter,
                                title="Trade Response",
                            )
                            self._show_tutor_action_feedback(player, trade_response_feedback)
                    else:
                        interested, counter = False, None
                else:
                    # AI can only respond if it has enough resources to give
                    if player.can_afford(buying):
                        if self.game_mode == GameMode.GUIDED and isinstance(player.policy, RuleBasedAI):
                            interested, counter, explanation = player.policy.respond_to_trade_with_explanation(
                                player, self._game, selling_player, selling, buying)
                            if explanation is not None:
                                self._raise_if_return_home(
                                    self.view.display_board_turn_explanations(player, None, explanation)
                                )
                        else:
                            interested, counter = player.policy.respond_to_trade(
                                player, self._game, selling_player, selling, buying)
                    else:
                        interested, counter = False, None

                if interested:
                    results.append((player, counter))

        if self.game_mode == GameMode.TUTOR and selling_player.is_human and results:
            explanation = self._preview_tutor_explanation(lambda: self.tutor_ai.choose_trade_partner_with_explanation(
                selling_player, self._game, selling, buying, results)
            )
            self._show_tutor_init(selling_player, TutorStage.TRADE_DECISION, explanation)

        return results

    def get_game_state(self):
        """Returns the internal game state"""
        return self._game

    def roll_dice(self, player: Player) -> Tuple[int, int, int, Optional[str]]:
        """Roll two dice and distribute resources to players."""
        self.view.display_board()
        d1, d2, total = self._game.roll_dice()
        msg = None
        if total == Game.ROBBER_DICE_NUM:
            # Perform robber actions
            # 1. All players must discard half of their resources
            for p in self._game.players:
                discard_count = p.calculate_discard_count()
                if discard_count > 0:
                    resources_to_discard = {}
                    discard_feedback = None
                    if p.is_human:
                        if self.game_mode == GameMode.TUTOR:
                            explanation = self._preview_tutor_explanation(
                                lambda: self.tutor_ai.select_discard_resources_with_explanation(
                                    p,
                                    self._game,
                                    discard_count,
                                )
                            )
                            self._show_tutor_init(p, TutorStage.DISCARD_RESOURCES, explanation)

                        def select_tutor_discard_resources() -> ResourceCount:
                            return self._run_tutor_decision(
                                lambda: self.tutor_ai.select_discard_resources(p, self._game, discard_count)
                            )

                        self._set_tutor_shortcut_handlers(select_tutor_discard_resources)
                        try:
                            resources_to_discard = self.view.show_resource_chooser(
                                p, discard_count, "The robber has been rolled!", p.resources)
                        finally:
                            self._set_tutor_shortcut_handlers(None)
                        self._raise_if_return_home(resources_to_discard)
                        if self._should_collect_tutor_feedback(p):
                            discard_feedback = self.tutor_evaluator.evaluate_discard_choice(
                                p,
                                self._game,
                                resources_to_discard,
                                discard_count,
                                title="Discard",
                            )
                    elif p.policy is not None:
                        if self.game_mode == GameMode.GUIDED and isinstance(p.policy, RuleBasedAI):
                            resources_to_discard, explanation = p.policy.select_discard_resources_with_explanation(
                                p, self._game, discard_count)
                            if explanation is not None:
                                self._raise_if_return_home(
                                    self.view.display_board_turn_explanations(p, None, explanation)
                                )
                        else:
                            resources_to_discard = p.policy.select_discard_resources(p, self._game, discard_count)
                    p.remove_resources(resources_to_discard)
                    self._show_tutor_action_feedback(p, discard_feedback if p.is_human else None)

            # 2. Player who rolled dice can move robber and collect resources
            result = self.handle_robber_action(player)
            if result is not None:
                stolen_player, stolen_resource = result
                msg = f"Stole 1 {stolen_resource.name.replace('_', ' ').title()} from {stolen_player.name}."
        return d1, d2, total, msg

    def handle_robber_action(self, player) -> Optional[Tuple[Player, Resource]]:
        """
        Handles moving the robber and stealing a resource for a given player,
        supporting both human and AI players.
        """
        self._pending_tutor_robber_choice = None

        # Choose the robber placement and target player
        if player.is_human:
            # Get available hex tiles (exclude current robber tile)
            available_hexes = [tile for tile in self._game.get_all_hexes() if not tile.robber]
            if self.game_mode == GameMode.TUTOR:
                robber_explanation = self._preview_tutor_explanation(
                    lambda: self.tutor_ai.select_robber_target_with_explanation(
                        player,
                        self._game,
                        available_hexes,
                    )
                )
                self._show_tutor_init(player, TutorStage.ROBBER_PLACEMENT, robber_explanation)
            self.view.display_board(player, "Select a hex to move the robber")

            def select_tutor_robber_hex() -> HexTile:
                return self._get_tutor_recommended_robber_choice(player, available_hexes)[0]

            self._set_tutor_shortcut_handlers(select_tutor_robber_hex)
            try:
                selected_hex: HexTile = self.view.draw_selectable_tiles(available_hexes)
            finally:
                self._set_tutor_shortcut_handlers(None)
            self._raise_if_return_home(selected_hex)
            if self._should_collect_tutor_feedback(player):
                robber_placement_feedback = self.tutor_evaluator.evaluate_robber_choice(
                    player,
                    self._game,
                    available_hexes,
                    selected_hex,
                    None,
                    title="Robber",
                )
            else:
                robber_placement_feedback = None

            # Check for stealable players on adjacent vertices
            adjacent_player_buildings: List[Vertex] = [
                v for v in selected_hex.vertices
                if v.owner is not None and v.owner != player and any(v.owner.resources.values())
            ]

            self._game.set_robber(selected_hex)
            self._show_tutor_action_feedback(player, robber_placement_feedback)

            if not adjacent_player_buildings:
                tile, steal_from = selected_hex, None
            else:
                if self.game_mode == GameMode.TUTOR:
                    robber_explanation = self._preview_tutor_explanation(
                        lambda: self.tutor_ai.select_robber_target_with_explanation(
                            player,
                            self._game,
                            [selected_hex],
                        )
                    )
                    self._show_tutor_init(player, TutorStage.ROBBER_STEAL_TARGET, robber_explanation)
                self.view.display_board(player, "Select a player to steal from")

                def select_tutor_robber_target_building() -> Vertex:
                    selected_owner = self._get_tutor_recommended_robber_choice(player, [selected_hex])[1]
                    return next(
                        (
                            building for building in adjacent_player_buildings
                            if building.owner == selected_owner
                        ),
                        adjacent_player_buildings[0],
                    )

                self._set_tutor_shortcut_handlers(select_tutor_robber_target_building)
                try:
                    selected_player_building: Vertex = self.view.draw_selectable_vertices(adjacent_player_buildings)
                finally:
                    self._set_tutor_shortcut_handlers(None)
                self._raise_if_return_home(selected_player_building)
                selected_player = selected_player_building.owner
                if self._should_collect_tutor_feedback(player):
                    robber_target_feedback = self.tutor_evaluator.evaluate_robber_choice(
                        player,
                        self._game,
                        [selected_hex],
                        selected_hex,
                        selected_player,
                        title="Robber",
                    )
                    self._show_tutor_action_feedback(player, robber_target_feedback)

                tile, steal_from = selected_hex, selected_player
            self._pending_tutor_robber_choice = None

        else:
            valid_hexes = [
                hex_tile for hex_tile in self._game.get_all_hexes()
                if not hex_tile.robber
            ]
            if self.game_mode == GameMode.GUIDED and isinstance(player.policy, RuleBasedAI):
                tile, steal_from, explanation = player.policy.select_robber_target_with_explanation(
                    player, self._game, valid_hexes)
                if explanation is not None:
                    self._raise_if_return_home(self.view.display_board_turn_explanations(player, None, explanation))
            else:
                tile, steal_from = player.policy.select_robber_target(player, self._game, valid_hexes)

        # Move the robber
        if tile is not None and not tile.robber:
            self._game.set_robber(tile)

        # If there is a player to steal from, handle the discard
        if steal_from is not None:
            resource = steal_from.random_resource()
            if not resource:
                return None

            self._game.trade_between_players(player, {}, steal_from, resource)

            return steal_from, next(iter(resource.keys()))

    def play_development_card(self, player: Player, card_type: DevelopmentCardType) -> str:
        """Plays the development card for a player and returns a descriptive message."""
        msg = f"{player.name} played {card_type.name.replace('_', ' ').title()}."
        self._game.development_deck.play(card_type)

        if card_type == DevelopmentCardType.KNIGHT:
            # KNIGHT: Move the robber and steal one resource from a player adjacent to the new robber location
            stolen_player, stolen_resource = self.handle_robber_action(player) or (None, None)
            player.army_size += 1

            # If player has at least 3 knights and largest army is bigger than others, assign Largest Army
            if player.army_size >= 3:
                other_holder = next(
                    (p for p in self._game.players if p.has_largest_army and p != player),
                    None
                )
                if other_holder is None or player.army_size > other_holder.army_size:
                    if other_holder is not None:
                        other_holder.has_largest_army = False
                    player.has_largest_army = True
                    msg += " They now have the Largest Army!"

            if stolen_player and stolen_resource:
                msg += f" Stole 1 {stolen_resource.name.replace('_', ' ').title()} from {stolen_player.name}."

        elif card_type == DevelopmentCardType.ROAD_BUILDING:
            # ROAD BUILDING: Allows player to place two roads for free
            built_edges = []
            for idx in range(2):
                available_edges = self._game.get_available_edges(player)
                if available_edges:
                    road_building_feedback = None
                    if player.is_human:
                        if self.game_mode == GameMode.TUTOR:
                            explanation = self._preview_tutor_explanation(
                                lambda: self.tutor_ai.select_initial_road_location_with_explanation(
                                    player,
                                    self._game,
                                    available_edges,
                                )
                            )
                            self._show_tutor_init(player, TutorStage.ROAD_BUILDING, explanation)
                        edge = self.get_road_choice(
                            player,
                            None,
                            selector=lambda candidate_edges: self.tutor_ai.road_building_placement(
                                player, self._game, candidate_edges
                            ),
                        )
                        if self._should_collect_tutor_feedback(player):
                            road_building_feedback = self.tutor_evaluator.evaluate_opening_road_choice(
                                player,
                                self._game,
                                available_edges,
                                edge,
                                title=f"Road Building Road {idx + 1}",
                            )
                    else:
                        edge = self.get_road_choice_ai(player, None)
                    if edge is None:
                        continue
                    self._game.try_build_road(player, edge, use_resources=False)
                    built_edges.append(edge)
                    if player.is_human:
                        self._show_tutor_action_feedback(player, road_building_feedback)
            msg += f" Built {len(built_edges)} road(s)."

        elif card_type == DevelopmentCardType.YEAR_OF_PLENTY:
            # YEAR OF PLENTY: Player chooses two resources from the bank to add to their hand
            year_of_plenty_feedback = None
            if player.is_human:
                if self.game_mode == GameMode.TUTOR:
                    explanation = self._preview_tutor_explanation(
                        lambda: self.tutor_ai.select_year_of_plenty_resources_with_explanation(
                            player,
                            self._game,
                        )
                    )
                    self._show_tutor_init(player, TutorStage.YEAR_OF_PLENTY, explanation)

                def select_tutor_year_of_plenty_resources() -> ResourceCount:
                    return self._run_tutor_decision(
                        lambda: self.tutor_ai.select_year_of_plenty_resources(player, self._game)
                    )

                self._set_tutor_shortcut_handlers(select_tutor_year_of_plenty_resources)
                try:
                    resources = self.view.show_resource_chooser(
                        player, 2, "Year of Plenty: choose any two resources from the bank.", self._game.bank_resources)
                finally:
                    self._set_tutor_shortcut_handlers(None)
                self._raise_if_return_home(resources)
                if self._should_collect_tutor_feedback(player):
                    year_of_plenty_feedback = self.tutor_evaluator.evaluate_year_of_plenty_choice(
                        player,
                        self._game,
                        resources,
                        title="Year Of Plenty",
                    )
            else:
                if self.game_mode == GameMode.GUIDED and isinstance(player.policy, RuleBasedAI):
                    resources, explanation = player.policy.select_year_of_plenty_resources_with_explanation(
                        player, self._game)
                    if explanation is not None:
                        self._raise_if_return_home(self.view.display_board_turn_explanations(player, None, explanation))
                else:
                    resources = player.policy.select_year_of_plenty_resources(player, self._game)
            player.add_resources(resources)
            if player.is_human:
                self._show_tutor_action_feedback(player, year_of_plenty_feedback)
            resource_list = ", ".join(
                f"{amt} {res.name.replace('_', ' ').title()}" for res, amt in resources.items() if amt > 0)
            msg += f" Took {resource_list} from the bank."

        elif card_type == DevelopmentCardType.MONOPOLY:
            # MONOPOLY: Player chooses a single resource type - other players give all of that resource to the player
            monopoly_feedback = None
            if player.is_human:
                if self.game_mode == GameMode.TUTOR:
                    explanation = self._preview_tutor_explanation(
                        lambda: self.tutor_ai.select_monopoly_resource_with_explanation(
                            player,
                            self._game,
                        )
                    )
                    self._show_tutor_init(player, TutorStage.MONOPOLY, explanation)

                def select_tutor_monopoly_choice() -> ResourceCount:
                    chosen_resource = self._run_tutor_decision(
                        lambda: self.tutor_ai.select_monopoly_resource(player, self._game)
                    )
                    return {chosen_resource: 1}

                self._set_tutor_shortcut_handlers(select_tutor_monopoly_choice)
                try:
                    chosen = self.view.show_resource_chooser(
                        player, 1, "Monopoly: choose a resource to get from the other players.",
                        {res: 1 for res in Resource})
                finally:
                    self._set_tutor_shortcut_handlers(None)
                self._raise_if_return_home(chosen)
                # Extract the single Resource enum
                resource = next(iter(chosen.keys()))
                if self._should_collect_tutor_feedback(player):
                    monopoly_feedback = self.tutor_evaluator.evaluate_monopoly_choice(
                        player,
                        self._game,
                        resource,
                        title="Monopoly",
                    )
            else:
                if self.game_mode == GameMode.GUIDED and isinstance(player.policy, RuleBasedAI):
                    resource, explanation = player.policy.select_monopoly_resource_with_explanation(
                        player, self._game)
                    if explanation is not None:
                        self._raise_if_return_home(self.view.display_board_turn_explanations(player, None, explanation))
                else:
                    resource = player.policy.select_monopoly_resource(player, self._game)
            total_taken = 0
            for p in self._game.players:
                if p == player:
                    continue
                amount = p.resources[resource]
                self._game.trade_between_players(player, {}, p, {resource: amount})
                total_taken += amount
            if player.is_human:
                self._show_tutor_action_feedback(player, monopoly_feedback)
            msg += f" Monopolised {total_taken} {resource.name.replace('_', ' ').title()} from other players."

        # Remove one card of this type from player's hand
        for card in player.development_cards:
            if card.card_type == card_type:
                player.development_cards.remove(card)
                break

        self._game.update_best_opponent_victory_points()

        if player.is_human:
            self._tutor_dev_played = True
            self._refresh_tutor_turn_explanation(player)

        return msg

    def make_round_move(self, player: Player):
        if self.game_mode in {GameMode.PLAY, GameMode.TUTOR}:
            self.tutor_ai.new_turn()
        if self.game_mode == GameMode.TUTOR:
            self._tutor_dev_played = False

        playable_cards = [card for card in player.development_cards if card.playable]
        played_dev_card = False
        if not playable_cards:
            # Guided simulation always consumes the pre-roll policy query, even when the
            # only legal outcome is "roll". Mirror that here so tutor-followed games stay
            # on the same RNG path.
            if self.game_mode == GameMode.TUTOR:
                self._run_tutor_decision(lambda: self.tutor_ai.next_action(player, self._game, Phase.PRE_ROLL, False))
        else:
            # Player can play card before rolling dice
            def select_tutor_pre_roll_card() -> DevelopmentCardType | bool:
                recommended_action = self._run_tutor_decision(
                    lambda: self.tutor_ai.next_action(player, self._game, Phase.PRE_ROLL, False)
                )
                if recommended_action.type == ActionType.PLAY_DEV_CARD:
                    return recommended_action.payload
                return False

            self._set_tutor_shortcut_handlers(select_tutor_pre_roll_card)
            try:
                played_card = self.view.pre_roll(player)
            finally:
                self._set_tutor_shortcut_handlers(None)
            self._raise_if_return_home(played_card)
            if isinstance(played_card, DevelopmentCardType):
                pre_roll_feedback = None
                if self._should_collect_tutor_feedback(player):
                    pre_roll_feedback = self.tutor_evaluator.evaluate_main_turn_action(
                        player,
                        self._game,
                        Phase.PRE_ROLL,
                        False,
                        Action(ActionType.PLAY_DEV_CARD, played_card),
                        title="Pre-Roll Choice",
                    )
                self.play_development_card(player, played_card)
                self._show_tutor_action_feedback(player, pre_roll_feedback)
                played_dev_card = True

        d1, d2, total, _ = self.roll_dice(player)

        while True:
            def select_tutor_main_action() -> Action:
                return self.get_tutor_recommended_main_action(player, played_dev_card)

            self._set_tutor_shortcut_handlers(select_tutor_main_action)
            try:
                action = self.view.display_board_turn(player, (d1, d2, total), played_dev_card)
            finally:
                self._set_tutor_shortcut_handlers(None)
            self._raise_if_return_home(action)
            action_feedback = self._prepare_tutor_main_action_comparison(player, action, played_dev_card)
            if action.type == ActionType.END_TURN:
                self._show_tutor_action_feedback(player, action_feedback)
                break

            match action.type:
                case ActionType.BUILD:
                    buildable, location = action.payload
                    if buildable == Buildable.ROAD:
                        success, _ = self.try_build_road(player, location)
                    elif buildable == Buildable.SETTLEMENT:
                        success, _ = self.try_build_settlement(player, location)
                    elif buildable == Buildable.CITY:
                        success, _ = self.try_build_city(player, location)
                    else:
                        success = False
                    if success:
                        self._show_tutor_action_feedback(player, action_feedback)

                case ActionType.TRADE_WITH_BANK:
                    selling, buying = action.payload
                    success = self.try_trade_with_bank(player, selling, buying)
                    if success:
                        self._show_tutor_action_feedback(player, action_feedback)

                case ActionType.TRADE_WITH_PLAYER:
                    selling, buying = action.payload
                    willing_players = self.trade_with_players(player, selling, buying)
                    affordable_offers = [
                        (p, counter) for (p, counter) in willing_players
                        if counter is None or player.can_afford(counter)
                    ]
                    if affordable_offers:
                        def select_tutor_trade_partner() -> Optional[Tuple[Player, Optional[ResourceCount]]]:
                            return self._run_tutor_decision(lambda: self.tutor_ai.choose_trade_partner(
                                player,
                                self._game,
                                selling,
                                buying,
                                affordable_offers,
                            ))

                        self._set_tutor_shortcut_handlers(select_tutor_trade_partner)
                        try:
                            deal = self.view.select_player_trade_offer(player, selling, buying, affordable_offers)
                        finally:
                            self._set_tutor_shortcut_handlers(None)
                        self._raise_if_return_home(deal)
                        if deal is not None:
                            buying_player, counter = deal
                            partner_feedback = None
                            if self._should_collect_tutor_feedback(player):
                                partner_feedback = self.tutor_evaluator.evaluate_trade_partner_choice(
                                    player,
                                    self._game,
                                    selling,
                                    buying,
                                    affordable_offers,
                                    buying_player,
                                    counter,
                                    title="Trade Partner",
                                )
                            final_selling = counter if counter is not None else selling
                            self.trade_between_players(player, final_selling, buying_player, buying)
                            self._show_tutor_action_feedback(player, partner_feedback)
                            self._show_tutor_action_feedback(player, action_feedback)

                case ActionType.BUY_DEV_CARD:
                    success, _ = self.try_buy_development_card(player)
                    if success:
                        self._show_tutor_action_feedback(player, action_feedback)

                case ActionType.PLAY_DEV_CARD:
                    if not played_dev_card:
                        self.play_development_card(player, action.payload)
                        played_dev_card = True
                        self._show_tutor_action_feedback(player, action_feedback)

    def _is_guided_turn(self, player: Player):
        return (self.game_mode == GameMode.GUIDED and player.player_number == PlayerNumber.P1
                and isinstance(player.policy, RuleBasedAI))

    def _get_ai_action(
            self,
            player: Player,
            phase: Phase,
            dev_played: bool,
            dice_info: Optional[Tuple[int, int, int]] = None,
    ) -> Action:
        """Return the next AI action, optionally with explanation printing in guided mode."""
        if self._is_guided_turn(player) and isinstance(player.policy, RuleBasedAI):
            action, explanation = player.policy.next_action_with_explanation(
                player,
                self._game,
                phase=phase,
                dev_played=dev_played,
            )
            if not (phase == Phase.PRE_ROLL and action.type == ActionType.ROLL):
                self._raise_if_return_home(self.view.display_board_turn_explanations(player, dice_info, explanation))
            return action

        return player.policy.next_action(
            player,
            self._game,
            phase=phase,
            dev_played=dev_played,
        )

    def make_round_move_ai(self, player: Player):
        """AI turn driven by policy-selected actions."""
        player.policy.new_turn()
        ai_action_requests = 0

        def next_ai_action(phase: Phase, dev_played: bool, dice_info: Optional[Tuple[int, int, int]] = None) -> Action:
            nonlocal ai_action_requests
            ai_action_requests += 1
            if ai_action_requests > MAX_AI_ACTION_REQUESTS_PER_TURN:
                raise AITurnActionLimitExceeded(player.name, ai_action_requests, phase)
            return self._get_ai_action(player, phase=phase, dev_played=dev_played, dice_info=dice_info)

        used_dev_card = False
        messages = []

        # Pre-roll phase: maybe play a dev card
        action = next_ai_action(phase=Phase.PRE_ROLL, dev_played=used_dev_card)
        if action and action.type == ActionType.PLAY_DEV_CARD:
            messages.append(self.play_development_card(player, action.payload))
            used_dev_card = True

        # Roll dice
        d1, d2, total, roll_msg = self.roll_dice(player)

        # Main decision loop
        while True:
            action = next_ai_action(phase=Phase.MAIN, dev_played=used_dev_card, dice_info=(d1, d2, total))
            if action.type == ActionType.END_TURN:
                break

            match action.type:
                case ActionType.BUILD:
                    buildable, location = action.payload
                    msg = self.ai_attempt_build(player, buildable, location)
                    if msg:
                        messages.append(msg)

                case ActionType.TRADE_WITH_BANK:
                    selling, buying = action.payload
                    success = self._game.try_trade_with_bank(player, selling, buying)
                    if success:
                        messages.append(
                            f"{player.name} trades {resource_dict_to_str(selling)} with the bank "
                            f"for {resource_dict_to_str(buying)}."
                        )

                case ActionType.TRADE_WITH_PLAYER:
                    selling, buying = action.payload
                    willing_players = self.trade_with_players(player, selling, buying)

                    # Only keep offers the AI can afford
                    affordable_offers = [
                        (p, counter) for (p, counter) in willing_players
                        if counter is None or player.can_afford(counter)
                    ]

                    if affordable_offers:
                        if self.game_mode == GameMode.GUIDED and isinstance(player.policy, RuleBasedAI):
                            deal, explanation = player.policy.choose_trade_partner_with_explanation(
                                player, self._game, selling, buying, affordable_offers)
                            if explanation is not None:
                                self._raise_if_return_home(
                                    self.view.display_board_turn_explanations(player, (d1, d2, total), explanation)
                                )
                        else:
                            deal = player.policy.choose_trade_partner(player, self._game, selling, buying,
                                                                      affordable_offers)
                        if deal is not None:
                            buying_player, counter = deal
                            if counter is not None:
                                selling = counter
                            self._game.trade_between_players(player, selling, buying_player, buying)
                            messages.append(
                                f"{player.name} trades {resource_dict_to_str(selling)} with "
                                f"{buying_player.name} for {resource_dict_to_str(buying)}."
                            )

                case ActionType.BUY_DEV_CARD:
                    success, _ = self._game.try_buy_development_card(player)
                    if success:
                        messages.append(f"{player.name} bought a development card.")

                case ActionType.PLAY_DEV_CARD:
                    if not used_dev_card:
                        messages.append(self.play_development_card(player, action.payload))
                        used_dev_card = True

        # Display turn results
        if roll_msg:
            messages.append(roll_msg)

        self.view.display_board_turn_ai(player, (d1, d2, total), "\n".join(messages),
                                        increase_delay=self._is_guided_turn(player))
        self._raise_if_view_requested_home()

    def ai_attempt_build(self, player: Player, action: Buildable, location):
        """Attempt a build action and return the resulting message."""
        buildable = self._game.get_buildable_options(player)

        # Special handling for development card
        if action == Buildable.DEVELOPMENT_CARD:
            if buildable.get(Buildable.DEVELOPMENT_CARD, False):
                success, _ = self._game.try_buy_development_card(player)
                msg = f"{player.name} bought a development card."
                return msg
            else:
                return f"{player.name} chooses to do nothing."

        if action not in buildable or location is None:
            return f"{player.name} chooses to do nothing."

        if action == Buildable.ROAD:
            success, msg = self._game.try_build_road(player, location)
        elif action == Buildable.SETTLEMENT:
            success, msg = self._game.try_build_settlement(player, location)
        elif action == Buildable.CITY:
            success, msg = self._game.try_build_city(player, location)
        else:
            msg = "AI attempted unknown action"

        if not SHOW_AI_BUILT_LOCATIONS:
            msg = msg.partition("built")[0] + f"built by {player.name}"

        return msg

    # <editor-fold desc="Controller wrapper methods for model">

    def get_ports(self) -> List[Tuple[Port, Vertex, Vertex]]:
        """Returns the list of ports and their position"""
        return self._game.get_ports()

    def get_vertex(self, q: int, r: int, corner_index: VertexDirection) -> Optional[Vertex]:
        """Return the Vertex object for hex (q,r) at corner_index 0-5."""
        return self._game.get_vertex(q, r, corner_index)

    def try_build_settlement(
            self,
            player: Player,
            vertex: Vertex,
            build: bool = True,
            use_resources: bool = True,
            road_restriction: bool = True
    ) -> tuple[bool, str]:
        """Attempt to build a settlement with rules enforced."""
        result = self._game.try_build_settlement(player, vertex, build, use_resources, road_restriction)
        success, _ = result
        if success and build:
            self._refresh_tutor_turn_explanation(player)
        return result

    def get_edge(self, q: int, r: int, edge_index: EdgeDirection) -> Optional[Edge]:
        """Return the Edge object for hex (q,r) at edge_index 0-5."""
        return self._game.get_edge(q, r, edge_index)

    def try_build_road(
            self,
            player: Player,
            edge: Edge,
            on_vertex: Optional[Vertex] = None,
            build: bool = True,
            use_resources: bool = True
    ) -> tuple[bool, str]:
        """Attempt to build a road with rules enforced."""
        result = self._game.try_build_road(player, edge, on_vertex, build, use_resources)
        success, _ = result
        if success and build:
            self._refresh_tutor_turn_explanation(player)
        return result

    def get_buildable_options(self, player: Player) -> Dict:
        """
        Returns dict of possible Buildable actions and valid board locations.
        Empty list if player cannot afford or no legal space.
        """
        return self._game.get_buildable_options(player)

    def try_build_city(
            self,
            player: Player,
            vertex: Vertex,
            build: bool = True,
            use_resources: bool = True
    ) -> tuple[bool, str]:
        """Attempt to upgrade a settlement to a city."""
        result = self._game.try_build_city(player, vertex, build, use_resources)
        success, _ = result
        if success and build:
            self._refresh_tutor_turn_explanation(player)
        return result

    def try_trade_with_bank(
            self, player: Player, selling: ResourceCount,
            buying: ResourceCount, use_resources: bool = True
    ) -> bool:
        """Attempt a bank trade using correct port discounts (2:1, 3:1, 4:1)."""
        success = self._game.try_trade_with_bank(player, selling, buying, use_resources)
        if success and use_resources:
            self._refresh_tutor_turn_explanation(player)
        return success

    def trade_between_players(self, player: Player, selling: ResourceCount,
                              buying_player: Player, buying: ResourceCount):
        """Execute a trade of resources between two players."""
        result = self._game.trade_between_players(player, selling, buying_player, buying)
        self._refresh_tutor_turn_explanation(player)
        return result

    def get_available_vertices(self, player: Player, building_type: Buildable, road_restriction: bool = True) -> \
            List[Vertex]:
        """Return a list of vertices where the player can build a settlement or city."""
        return self._game.get_available_vertices(player, building_type, road_restriction)

    def get_buildable_edges_for_vertex(self, vertex: Vertex) -> List[Edge]:
        """Return edges adjacent to a vertex where the player can build a road."""
        return self._game.get_buildable_edges_for_vertex(vertex)

    def get_trade_rate(self, player: Player, resource: Resource) -> int:
        """Return the best trade rate for 'player' when selling 'resource'."""
        return self._game.get_trade_rate(player, resource)

    def get_hex_tile(self, q: int, r: int) -> Optional[HexTile]:
        """Return the HexTile object for hex (q,r)."""
        return self._game.get_hex_tile(q, r)

    def get_players_on_hex(self, hex_tile):
        """Return a list of players who own a settlement or city on the given hex tile."""
        return self._game.get_players_on_hex(hex_tile)

    def get_all_hexes(self) -> List[HexTile]:
        """Return a list of all hex tiles on the board."""
        return self._game.get_all_hexes()

    def get_hex_tiles_with_players(self):
        """Return a list of hex tiles that have at least one player on them."""
        return self._game.get_hex_tiles_with_players()

    def try_buy_development_card(self, player) -> Tuple[bool, str]:
        """Attempt to buy a development card for a player."""
        result = self._game.try_buy_development_card(player)
        success, _ = result
        if success:
            self._refresh_tutor_turn_explanation(player)
        return result

    def get_available_edges(self, player: Player) -> List[Edge]:
        """Return a list of edges where the player can build a road."""
        return self._game.get_available_edges(player)

    def get_bank_resources(self) -> ResourceCount:
        """Returns the bank's resources"""
        return self._game.bank_resources

    def get_all_edges(self):
        """Return a list of all edges on the board."""
        return self._game.get_all_edges()

    def get_all_vertices(self):
        """Return a list of all vertices on the board."""
        return self._game.get_all_vertices()

    def get_development_deck(self):
        return self._game.development_deck

    def get_all_players(self):
        return self._game.players

    def get_victory_point_history(self) -> List[Tuple[int, Dict[PlayerNumber, int]]]:
        return list(self.victory_point_history)

    def get_endgame_review_history(self) -> List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]]:
        return list(self.endgame_review_history)

    def get_tutor_feedback_history(self) -> List[TutorFeedbackExplanation]:
        return list(self.tutor_feedback_history)

    # </editor-fold>
