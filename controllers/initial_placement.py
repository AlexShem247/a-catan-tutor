from abc import ABC
from typing import Callable

from ai.actions import ActionType
from ai.rule_based_ai.RuleBasedAI import RuleBasedAI
from ai.tutor.tutor import TutorStage
from controllers.controller_support import ControllerSupport
from game.Edge import Edge
from game.Player import Player
from game.PlayerAssets import Buildable
from game.Vertex import Vertex


class InitialPlacementController(ControllerSupport, ABC):

    def run_initial_placement(self):
        """Run the initial settlement and road placement sequence."""
        import controllers.GameController as GameControllerModule

        players = self._game.players
        first, second = ((reversed(players), players) if GameControllerModule.START_LAST else
                         (players, reversed(players)))
        players_order = ([(p, False) for p in first] + [(p, True) for p in second])

        for player, gain_resource in players_order:
            vertices = self._game.get_available_vertices(player, Buildable.SETTLEMENT, road_restriction=False)
            if player.is_human:
                if self.game_mode in {self.GameMode.TUTOR, self.GameMode.GUIDED}:
                    explanation = self._preview_tutor_explanation(
                        lambda: self.tutor_ai.select_initial_settlement_location_with_explanation(
                            player,
                            self._game,
                            vertices,
                        ))
                    self.view.display_tutor_init(player, TutorStage.INITIAL_SETTLEMENT, explanation)
                self.view.display_board(player, "Select a position to build your settlement")

                def select_tutor_initial_settlement() -> Vertex | None:
                    return self._run_tutor_decision(
                        lambda: self.tutor_ai.select_initial_settlement_location(player, self._game, vertices))

                self._set_tutor_shortcut_handlers(select_tutor_initial_settlement)
                try:
                    vertex: Vertex = self.view.draw_selectable_vertices(vertices)
                finally:
                    self._set_tutor_shortcut_handlers(None)
                self._raise_if_return_home(vertex)
                self.view.display_board()
            else:
                if self._should_explain_ai_turns() and isinstance(player.policy, RuleBasedAI):
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
            self._game.try_build_settlement(
                player,
                vertex,
                use_resources=False,
                road_restriction=False,
                gain_resources=gain_resource,
            )
            self._show_tutor_action_feedback(player, opening_settlement_feedback)

            available_edges = self._game.get_available_edges(player)
            if vertex is not None:
                available_edges = [edge for edge in available_edges if vertex in edge.vertices]
            if player.is_human:
                if self.game_mode in {self.GameMode.TUTOR, self.GameMode.GUIDED}:
                    explanation = self._preview_tutor_explanation(
                        lambda: self.tutor_ai.select_initial_road_location_with_explanation(
                            player,
                            self._game,
                            available_edges,
                        ))
                    self.view.display_tutor_init(player, TutorStage.INITIAL_ROAD, explanation)
                edge = self.get_road_choice(
                    player,
                    vertex,
                    selector=lambda candidate_edges: self.tutor_ai.select_initial_road_location(
                        player, self._game, candidate_edges),
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
        settlement: Vertex | None = None,
        selector: Callable[[list[Edge]], Edge | None] | None = None,
    ) -> Edge:
        """Return the selected road choice for the current flow."""
        edges = self._game.get_available_edges(player)
        if settlement is not None:
            edges = [edge for edge in edges if settlement in edge.vertices]

        self.view.display_board(player, "Select a position to build your road")
        if selector is None:
            selector = lambda candidate_edges: self.tutor_ai.select_initial_road_location(
                player, self._game, candidate_edges)

        def select_tutor_initial_road() -> Edge | None:
            return self._run_tutor_decision(lambda: selector(edges))

        self._set_tutor_shortcut_handlers(select_tutor_initial_road)
        try:
            edge: Edge = self.view.draw_selectable_edges(edges)
        finally:
            self._set_tutor_shortcut_handlers(None)
        self._raise_if_return_home(edge)
        return edge

    def get_road_choice_ai(self, player: Player, settlement: Vertex | None = None) -> Edge | None:
        """Return the AI-selected road choice."""
        if settlement is None:
            available_edges = self._game.get_available_edges(player)
        else:
            available_edges = self._game.get_buildable_edges_for_vertex(settlement)

        if not available_edges:
            return None

        if self._should_explain_ai_turns() and isinstance(player.policy, RuleBasedAI):
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
