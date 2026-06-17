from abc import ABC

from ai.rule_based_ai.RuleBasedAI import RuleBasedAI
from ai.tutor.tutor import TutorStage
from controllers.controller_support import ControllerSupport
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex


class ActionHandlers(ControllerSupport, ABC):

    def trade_with_players(self, selling_player, selling, buying) -> list[tuple[Player, ResourceCount | None]]:
        """Run the player-to-player trade flow."""
        results = []
        for player in self._game.players:
            if player != selling_player:
                if player.is_human:
                    if player.can_afford(buying):
                        if self.game_mode in {self.GameMode.TUTOR, self.GameMode.GUIDED}:
                            explanation = self._preview_tutor_explanation(
                                lambda: self.tutor_ai.respond_to_trade_with_explanation(
                                    player,
                                    self._game,
                                    selling_player,
                                    selling,
                                    buying,
                                ))
                            self._show_tutor_init(player, TutorStage.TRADE_RESPONSE, explanation)

                        def respond_to_trade_for_player() -> tuple[bool, ResourceCount | None]:
                            return self._run_tutor_decision(lambda: self.tutor_ai.respond_to_trade(
                                player,
                                self._game,
                                selling_player,
                                selling,
                                buying,
                            ))

                        self._set_tutor_shortcut_handlers(respond_to_trade_for_player)
                        try:
                            trade_decision = self.view.display_trade_manager(player, selling, buying, selling_player)
                        finally:
                            self._set_tutor_shortcut_handlers(None)
                        self._raise_if_return_home(trade_decision)
                        self._raise_if_next_demo_state(trade_decision)
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
                    if player.can_afford(buying):
                        if self._should_explain_ai_turns() and isinstance(player.policy, RuleBasedAI):
                            interested, counter, explanation = player.policy.respond_to_trade_with_explanation(
                                player, self._game, selling_player, selling, buying)
                            if explanation is not None:
                                self._raise_if_return_home(
                                    self.view.display_board_turn_explanations(player, None, explanation))
                        else:
                            interested, counter = player.policy.respond_to_trade(player, self._game, selling_player,
                                                                                 selling, buying)
                    else:
                        interested, counter = False, None

                if interested:
                    results.append((player, counter))

        if self.game_mode in {self.GameMode.TUTOR, self.GameMode.GUIDED} and selling_player.is_human and results:
            explanation = self._preview_tutor_explanation(lambda: self.tutor_ai.choose_trade_partner_with_explanation(
                selling_player, self._game, selling, buying, results))
            self._show_tutor_init(selling_player, TutorStage.TRADE_DECISION, explanation)

        return results

    def roll_dice(self, player: Player) -> tuple[int, int, int, str | None]:
        """Roll the dice and handle any resulting events."""
        self.view.display_board()
        d1, d2, total = self._game.roll_dice()
        dice_recorder = getattr(self, "_record_current_dice_info", None)
        if callable(dice_recorder):
            dice_recorder((d1, d2, total))
        msg = None
        if total == Game.ROBBER_DICE_NUM:
            for p in self._game.players:
                discard_count = p.calculate_discard_count()
                if discard_count > 0:
                    resources_to_discard = {}
                    discard_feedback = None
                    if p.is_human:
                        if self.game_mode in {self.GameMode.TUTOR, self.GameMode.GUIDED}:
                            explanation = self._preview_tutor_explanation(
                                lambda: self.tutor_ai.select_discard_resources_with_explanation(
                                    p,
                                    self._game,
                                    discard_count,
                                ))
                            self._show_tutor_init(p, TutorStage.DISCARD_RESOURCES, explanation)

                        def select_tutor_discard_resources() -> ResourceCount:
                            return self._run_tutor_decision(
                                lambda: self.tutor_ai.select_discard_resources(p, self._game, discard_count))

                        self._set_tutor_shortcut_handlers(select_tutor_discard_resources)
                        try:
                            resources_to_discard = self.view.show_resource_chooser(p, discard_count,
                                                                                   "The robber has been rolled!",
                                                                                   p.resources)
                        finally:
                            self._set_tutor_shortcut_handlers(None)
                        self._raise_if_return_home(resources_to_discard)
                        self._raise_if_next_demo_state(resources_to_discard)
                        if self._should_collect_tutor_feedback(p):
                            discard_feedback = self.tutor_evaluator.evaluate_discard_choice(
                                p,
                                self._game,
                                resources_to_discard,
                                discard_count,
                                title="Discard",
                            )
                    elif p.policy is not None:
                        if self._should_explain_ai_turns() and isinstance(p.policy, RuleBasedAI):
                            resources_to_discard, explanation = p.policy.select_discard_resources_with_explanation(
                                p, self._game, discard_count)
                            if explanation is not None:
                                self._raise_if_return_home(
                                    self.view.display_board_turn_explanations(p, None, explanation))
                        else:
                            resources_to_discard = p.policy.select_discard_resources(p, self._game, discard_count)
                    p.remove_resources(resources_to_discard)
                    self._show_tutor_action_feedback(p, discard_feedback if p.is_human else None)

            result = self.handle_robber_action(player)
            if result is not None:
                stolen_player, stolen_resource = result
                msg = f"Stole 1 {stolen_resource.name.replace('_', ' ').title()} from {stolen_player.name}."
        return d1, d2, total, msg

    def handle_robber_action(self, player) -> tuple[Player, Resource] | None:
        """Handle the robber placement and theft flow."""
        self._pending_tutor_robber_choice = None
        if player.is_human:
            available_hexes = [tile for tile in self._game.get_all_hexes() if not tile.robber]
            if self.game_mode in {self.GameMode.TUTOR, self.GameMode.GUIDED}:
                robber_explanation = self._preview_tutor_explanation(
                    lambda: self.tutor_ai.select_robber_target_with_explanation(
                        player,
                        self._game,
                        available_hexes,
                    ))
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
            self._raise_if_next_demo_state(selected_hex)
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

            adjacent_player_buildings: list[Vertex] = [
                vertex for vertex in selected_hex.vertices
                if vertex.owner is not None and vertex.owner != player and any(vertex.owner.resources.values())
            ]

            self._game.set_robber(selected_hex)
            self._show_tutor_action_feedback(player, robber_placement_feedback)

            if not adjacent_player_buildings:
                tile, steal_from = selected_hex, None
            else:
                if self.game_mode in {self.GameMode.TUTOR, self.GameMode.GUIDED}:
                    robber_explanation = self._preview_tutor_explanation(
                        lambda: self.tutor_ai.select_robber_target_with_explanation(
                            player,
                            self._game,
                            [selected_hex],
                        ))
                    self._show_tutor_init(player, TutorStage.ROBBER_STEAL_TARGET, robber_explanation)
                self.view.display_board(player, "Select a player to steal from")

                def select_tutor_robber_target_building() -> Vertex:
                    selected_owner = self._get_tutor_recommended_robber_choice(player, [selected_hex])[1]
                    return next(
                        (building for building in adjacent_player_buildings if building.owner == selected_owner),
                        adjacent_player_buildings[0],
                    )

                self._set_tutor_shortcut_handlers(select_tutor_robber_target_building)
                try:
                    selected_player_building: Vertex = self.view.draw_selectable_vertices(adjacent_player_buildings)
                finally:
                    self._set_tutor_shortcut_handlers(None)
                self._raise_if_return_home(selected_player_building)
                self._raise_if_next_demo_state(selected_player_building)
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
            valid_hexes = [hex_tile for hex_tile in self._game.get_all_hexes() if not hex_tile.robber]
            if self._should_explain_ai_turns() and isinstance(player.policy, RuleBasedAI):
                tile, steal_from, explanation = player.policy.select_robber_target_with_explanation(
                    player, self._game, valid_hexes)
                if explanation is not None:
                    self._raise_if_return_home(self.view.display_board_turn_explanations(player, None, explanation))
            else:
                tile, steal_from = player.policy.select_robber_target(player, self._game, valid_hexes)

        if tile is not None and not tile.robber:
            self._game.set_robber(tile)

        if steal_from is not None:
            resource = steal_from.random_resource()
            if not resource:
                return None
            self._game.trade_between_players(player, {}, steal_from, resource)
            return steal_from, next(iter(resource.keys()))

    def play_development_card(self, player: Player, card_type: DevelopmentCardType) -> str:
        """Play the selected development card action."""
        msg = f"{player.name} played {card_type.name.replace('_', ' ').title()}."
        self._game.development_deck.play(card_type)

        if card_type == DevelopmentCardType.KNIGHT:
            stolen_player, stolen_resource = self.handle_robber_action(player) or (None, None)
            player.army_size += 1
            if player.army_size >= 3:
                other_holder = next((p for p in self._game.players if p.has_largest_army and p != player), None)
                if other_holder is None or player.army_size > other_holder.army_size:
                    if other_holder is not None:
                        other_holder.has_largest_army = False
                    player.has_largest_army = True
                    msg += " They now have the Largest Army!"
            if stolen_player and stolen_resource:
                msg += f" Stole 1 {stolen_resource.name.replace('_', ' ').title()} from {stolen_player.name}."

        elif card_type == DevelopmentCardType.ROAD_BUILDING:
            built_edges = []
            for idx in range(2):
                available_edges = self._game.get_available_edges(player)
                if available_edges:
                    road_building_feedback = None
                    if player.is_human:
                        if self.game_mode in {self.GameMode.TUTOR, self.GameMode.GUIDED}:
                            explanation = self._preview_tutor_explanation(
                                lambda: self.tutor_ai.select_initial_road_location_with_explanation(
                                    player,
                                    self._game,
                                    available_edges,
                                ))
                            self._show_tutor_init(player, TutorStage.ROAD_BUILDING, explanation)
                        edge = self.get_road_choice(
                            player,
                            None,
                            selector=lambda candidate_edges: self.tutor_ai.road_building_placement(
                                player, self._game, candidate_edges),
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
            year_of_plenty_feedback = None
            if player.is_human:
                if self.game_mode in {self.GameMode.TUTOR, self.GameMode.GUIDED}:
                    explanation = self._preview_tutor_explanation(
                        lambda: self.tutor_ai.select_year_of_plenty_resources_with_explanation(
                            player,
                            self._game,
                        ))
                    self._show_tutor_init(player, TutorStage.YEAR_OF_PLENTY, explanation)

                def select_tutor_year_of_plenty_resources() -> ResourceCount:
                    return self._run_tutor_decision(
                        lambda: self.tutor_ai.select_year_of_plenty_resources(player, self._game))

                self._set_tutor_shortcut_handlers(select_tutor_year_of_plenty_resources)
                try:
                    resources = self.view.show_resource_chooser(
                        player, 2, "Year of Plenty: choose any two resources from the bank.", self._game.bank_resources)
                finally:
                    self._set_tutor_shortcut_handlers(None)
                self._raise_if_return_home(resources)
                self._raise_if_next_demo_state(resources)
                if self._should_collect_tutor_feedback(player):
                    year_of_plenty_feedback = self.tutor_evaluator.evaluate_year_of_plenty_choice(
                        player,
                        self._game,
                        resources,
                        title="Year Of Plenty",
                    )
            else:
                if self._should_explain_ai_turns() and isinstance(player.policy, RuleBasedAI):
                    resources, explanation = player.policy.select_year_of_plenty_resources_with_explanation(
                        player, self._game)
                    if explanation is not None:
                        self._raise_if_return_home(self.view.display_board_turn_explanations(player, None, explanation))
                else:
                    resources = player.policy.select_year_of_plenty_resources(player, self._game)
            player.add_resources(resources)
            if player.is_human:
                self._show_tutor_action_feedback(player, year_of_plenty_feedback)
            resource_list = ", ".join(f"{amt} {res.name.replace('_', ' ').title()}" for res, amt in resources.items()
                                      if amt > 0)
            msg += f" Took {resource_list} from the bank."

        elif card_type == DevelopmentCardType.MONOPOLY:
            monopoly_feedback = None
            if player.is_human:
                if self.game_mode in {self.GameMode.TUTOR, self.GameMode.GUIDED}:
                    explanation = self._preview_tutor_explanation(
                        lambda: self.tutor_ai.select_monopoly_resource_with_explanation(
                            player,
                            self._game,
                        ))
                    self._show_tutor_init(player, TutorStage.MONOPOLY, explanation)

                def select_tutor_monopoly_choice() -> ResourceCount:
                    chosen_resource = self._run_tutor_decision(
                        lambda: self.tutor_ai.select_monopoly_resource(player, self._game))
                    return {chosen_resource: 1}

                self._set_tutor_shortcut_handlers(select_tutor_monopoly_choice)
                try:
                    chosen = self.view.show_resource_chooser(
                        player,
                        1,
                        "Monopoly: choose a resource to get from the other players.",
                        {res: 1
                         for res in Resource},
                    )
                finally:
                    self._set_tutor_shortcut_handlers(None)
                self._raise_if_return_home(chosen)
                self._raise_if_next_demo_state(chosen)
                resource = next(iter(chosen.keys()))
                if self._should_collect_tutor_feedback(player):
                    monopoly_feedback = self.tutor_evaluator.evaluate_monopoly_choice(
                        player,
                        self._game,
                        resource,
                        title="Monopoly",
                    )
            else:
                if self._should_explain_ai_turns() and isinstance(player.policy, RuleBasedAI):
                    resource, explanation = player.policy.select_monopoly_resource_with_explanation(player, self._game)
                    if explanation is not None:
                        self._raise_if_return_home(self.view.display_board_turn_explanations(player, None, explanation))
                else:
                    resource = player.policy.select_monopoly_resource(player, self._game)
            total_taken = 0
            for other_player in self._game.players:
                if other_player == player:
                    continue
                amount = other_player.resources[resource]
                self._game.trade_between_players(player, {}, other_player, {resource: amount})
                total_taken += amount
            if player.is_human:
                self._show_tutor_action_feedback(player, monopoly_feedback)
            msg += f" Monopolised {total_taken} {resource.name.replace('_', ' ').title()} from other players."

        for card in player.development_cards:
            if card.card_type == card_type:
                player.development_cards.remove(card)
                break

        self._game.update_best_opponent_victory_points()
        if player.is_human:
            self._tutor_dev_played = True
            self._refresh_tutor_turn_explanation(player)
        return msg

    def ai_attempt_build(self, player: Player, action: Buildable, location):
        """Try to execute the requested AI build action."""
        buildable = self._game.get_buildable_options(player)
        if action == Buildable.DEVELOPMENT_CARD:
            if buildable.get(Buildable.DEVELOPMENT_CARD, False):
                self._game.try_buy_development_card(player)
                return f"{player.name} bought a development card."
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
            success, msg = False, "AI attempted unknown action"

        if not self.SHOW_AI_BUILT_LOCATIONS:
            msg = msg.partition("built")[0] + f"built by {player.name}"
        return msg
