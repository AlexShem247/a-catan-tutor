from abc import ABC

from ai.actions import Action, ActionType, Phase
from ai.rule_based_ai.RuleBasedAI import RuleBasedAI
from controllers.controller_support import AITurnActionLimitExceeded, ControllerSupport
from game.Player import Player, PlayerNumber
from game.PlayerAssets import Buildable, DevelopmentCardType
from view.canvas.display_utils import resource_dict_to_str


class TurnController(ControllerSupport, ABC):

    def _run_main_turn_loop(self, player: Player, dice_info: tuple[int, int, int], played_dev_card: bool) -> None:
        """Run the main-turn action loop after dice resolution."""
        d1, d2, total = dice_info

        while True:
            def select_tutor_main_action() -> Action:
                return self.get_tutor_recommended_main_action(player, played_dev_card)

            self._set_tutor_shortcut_handlers(select_tutor_main_action)
            try:
                action = self.view.display_board_turn(player, (d1, d2, total), played_dev_card)
            finally:
                self._set_tutor_shortcut_handlers(None)
            self._raise_if_return_home(action)
            self._raise_if_next_demo_state(action)
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
                    elif buildable == Buildable.DEVELOPMENT_CARD:
                        success, _ = self.try_buy_development_card(player)
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
                    affordable_offers = [(p, counter) for (p, counter) in willing_players
                                         if counter is None or player.can_afford(counter)]
                    if affordable_offers:

                        def select_tutor_trade_partner():
                            return self._run_tutor_decision(lambda: self.tutor_ai.choose_trade_partner(
                                player,
                                self._game,
                                selling,
                                buying,
                                affordable_offers,
                            ))

                        self._set_tutor_shortcut_handlers(select_tutor_trade_partner)
                    else:
                        self._set_tutor_shortcut_handlers(lambda: None)
                    try:
                        deal = self.view.select_player_trade_offer(player, selling, buying, willing_players)
                    finally:
                        self._set_tutor_shortcut_handlers(None)
                    self._raise_if_return_home(deal)
                    self._raise_if_next_demo_state(deal)
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

    def make_round_move(self, player: Player):
        """Run a full turn for the given player."""
        if self.game_mode in {self.GameMode.PLAY, self.GameMode.TUTOR, self.GameMode.GUIDED}:
            self.tutor_ai.new_turn()
        if self.game_mode in {self.GameMode.TUTOR, self.GameMode.GUIDED}:
            self._tutor_dev_played = False

        playable_cards = [card for card in player.development_cards if card.playable]
        played_dev_card = False
        if not playable_cards:
            if self.game_mode in {self.GameMode.PLAY, self.GameMode.TUTOR, self.GameMode.GUIDED}:
                self._run_tutor_decision(lambda: self.tutor_ai.next_action(player, self._game, Phase.PRE_ROLL, False))
        else:

            def select_tutor_pre_roll_card() -> DevelopmentCardType | bool:
                recommended_action = self._run_tutor_decision(
                    lambda: self.tutor_ai.next_action(player, self._game, Phase.PRE_ROLL, False))
                if recommended_action.type == ActionType.PLAY_DEV_CARD:
                    return recommended_action.payload
                return False

            self._set_tutor_shortcut_handlers(select_tutor_pre_roll_card)
            try:
                played_card = self.view.pre_roll(player)
            finally:
                self._set_tutor_shortcut_handlers(None)
            self._raise_if_return_home(played_card)
            self._raise_if_next_demo_state(played_card)
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
        self._run_main_turn_loop(player, (d1, d2, total), played_dev_card)

    def _is_guided_turn(self, player: Player):
        """Check whether the current turn should use guided flow."""
        return (self._should_explain_ai_turns() and player.player_number == PlayerNumber.P1
                and isinstance(player.policy, RuleBasedAI))

    def _get_ai_action(
        self,
        player: Player,
        phase: Phase,
        dev_played: bool,
        dice_info: tuple[int, int, int] | None = None,
    ) -> Action:
        """Get the next AI action for the current phase."""
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
        """Run the AI turn wrapper for the given player."""
        player.policy.new_turn()
        ai_action_requests = 0

        def ai_action_request_limit() -> int:
            import controllers.GameController as GameControllerModule

            return GameControllerModule.MAX_AI_ACTION_REQUESTS_PER_TURN

        def next_ai_action(phase: Phase, dev_played: bool, dice_info: tuple[int, int, int] | None = None) -> Action:
            nonlocal ai_action_requests
            ai_action_requests += 1
            if ai_action_requests > ai_action_request_limit():
                raise AITurnActionLimitExceeded(player.name, ai_action_requests, phase)
            return self._get_ai_action(player, phase=phase, dev_played=dev_played, dice_info=dice_info)

        used_dev_card = False
        messages = []
        action = next_ai_action(phase=Phase.PRE_ROLL, dev_played=used_dev_card)
        if action and action.type == ActionType.PLAY_DEV_CARD:
            messages.append(self.play_development_card(player, action.payload))
            used_dev_card = True

        d1, d2, total, roll_msg = self.roll_dice(player)

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
                        messages.append(f"{player.name} trades {resource_dict_to_str(selling)} with the bank "
                                        f"for {resource_dict_to_str(buying)}.")
                case ActionType.TRADE_WITH_PLAYER:
                    selling, buying = action.payload
                    willing_players = self.trade_with_players(player, selling, buying)
                    affordable_offers = [(p, counter) for (p, counter) in willing_players
                                         if counter is None or player.can_afford(counter)]

                    if affordable_offers:
                        if self._should_explain_ai_turns() and isinstance(player.policy, RuleBasedAI):
                            deal, explanation = player.policy.choose_trade_partner_with_explanation(
                                player, self._game, selling, buying, affordable_offers)
                            if explanation is not None:
                                self._raise_if_return_home(
                                    self.view.display_board_turn_explanations(player, (d1, d2, total), explanation))
                        else:
                            deal = player.policy.choose_trade_partner(player, self._game, selling, buying,
                                                                      affordable_offers)
                        if deal is not None:
                            buying_player, counter = deal
                            if counter is not None:
                                selling = counter
                            self._game.trade_between_players(player, selling, buying_player, buying)
                            messages.append(f"{player.name} trades {resource_dict_to_str(selling)} with "
                                            f"{buying_player.name} for {resource_dict_to_str(buying)}.")
                case ActionType.BUY_DEV_CARD:
                    success, _ = self._game.try_buy_development_card(player)
                    if success:
                        messages.append(f"{player.name} bought a development card.")
                case ActionType.PLAY_DEV_CARD:
                    if not used_dev_card:
                        messages.append(self.play_development_card(player, action.payload))
                        used_dev_card = True

        if roll_msg:
            messages.append(roll_msg)

        self.view.display_board_turn_ai(
            player,
            (d1, d2, total),
            "\n".join(messages),
            increase_delay=self._is_guided_turn(player),
        )
        self._raise_if_view_requested_home()
