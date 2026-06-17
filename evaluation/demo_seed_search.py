import argparse
import csv
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from random import SystemRandom
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ai.actions import Action, ActionType, Phase
from ai.rule_based_ai.RuleBasedAI import RuleBasedAI
from ai.tutor.explanations import ActionExplanation
from ai.tutor.tutor import TutorStage
from config.player_policies import EVO_VS_RULE_BASED, STANDARD_SINGLEPLAYER
from controllers.GameController import GameController
from game.Edge import Edge
from game.Game import Game
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import Buildable, DevelopmentCardType
from game.Resources import Resource, ResourceCount
from game.Vertex import Vertex
from view.HeadlessView import HeadlessView
from view.View import GameMode

RESOURCE_ORDER = [
    Resource.WOOD,
    Resource.BRICK,
    Resource.SHEEP,
    Resource.WHEAT,
    Resource.ORE,
]


def resource_dict_to_plain_dict(resources: Optional[ResourceCount]) -> Dict[str, int]:
    resources = resources or {}
    return {resource.name.lower(): int(resources.get(resource, 0)) for resource in RESOURCE_ORDER}


def resource_dict_to_text(resources: Optional[ResourceCount]) -> str:
    resources = resources or {}
    parts = []
    for resource in RESOURCE_ORDER:
        amount = int(resources.get(resource, 0))
        if amount > 0:
            parts.append(f"{amount} {resource.name.lower()}")
    return ", ".join(parts) if parts else "none"


def vertex_to_id(vertex: Optional[Vertex]) -> Optional[str]:
    if vertex is None:
        return None
    q, r, direction = vertex.pos
    return f"vertex:q{q}:r{r}:{direction.name}"


def edge_to_id(edge: Optional[Edge]) -> Optional[str]:
    if edge is None:
        return None
    q, r, direction = edge.pos
    return f"edge:q{q}:r{r}:{direction.name}"


def hex_to_id(hex_tile: Optional[HexTile]) -> Optional[str]:
    if hex_tile is None:
        return None
    return (
        f"hex:q{hex_tile.q}:r{hex_tile.r}:"
        f"{getattr(hex_tile.resource, 'name', 'desert').lower()}:{hex_tile.production_number}"
    )


def serialise_choice(choice: Any) -> Any:
    if isinstance(choice, Action):
        return {
            "type": choice.type.name,
            "payload": serialise_choice(choice.payload),
        }
    if isinstance(choice, Buildable):
        return choice.name
    if isinstance(choice, DevelopmentCardType):
        return choice.name
    if isinstance(choice, Resource):
        return choice.name.lower()
    if isinstance(choice, Vertex):
        return vertex_to_id(choice)
    if isinstance(choice, Edge):
        return edge_to_id(choice)
    if isinstance(choice, HexTile):
        return hex_to_id(choice)
    if isinstance(choice, Player):
        return choice.player_number.name
    if isinstance(choice, tuple):
        return [serialise_choice(item) for item in choice]
    if isinstance(choice, list):
        return [serialise_choice(item) for item in choice]
    if isinstance(choice, dict):
        if choice and all(isinstance(key, Resource) for key in choice):
            return resource_dict_to_plain_dict(choice)
        return {str(key): serialise_choice(value) for key, value in choice.items()}
    return choice


def action_to_text(action: Action, explanation: Optional[ActionExplanation] = None) -> str:
    if explanation is not None:
        return strip_html(explanation.describe_action(action, short=False))

    if action.type == ActionType.END_TURN:
        return "End turn"
    if action.type == ActionType.BUY_DEV_CARD:
        return "Buy development card"
    if action.type == ActionType.PLAY_DEV_CARD:
        return f"Play dev card: {getattr(action.payload, 'name', action.payload)}"
    if action.type == ActionType.TRADE_WITH_BANK:
        selling, buying = action.payload
        return f"Trade with bank: {resource_dict_to_text(selling)} -> {resource_dict_to_text(buying)}"
    if action.type == ActionType.TRADE_WITH_PLAYER:
        selling, buying = action.payload
        return f"Offer player trade: {resource_dict_to_text(selling)} -> {resource_dict_to_text(buying)}"
    if action.type == ActionType.BUILD and isinstance(action.payload, tuple):
        buildable, location = action.payload
        location_id = serialise_choice(location)
        return f"Build {buildable.name.lower()} at {location_id}"
    return action.type.name


def explanation_text(explanation: Optional[ActionExplanation]) -> Tuple[str, bool]:
    if explanation is None:
        return "", False
    concise, _ = explanation.generate_text_concise()
    detail = explanation.generate_text_detail()
    detail_exists = bool(detail and detail.strip())
    return concise.strip(), detail_exists


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


class DemoRecorder:
    def __init__(self, seed: int, output_dir: Path):
        self.seed = seed
        self.output_dir = output_dir
        self.rows: List[Dict[str, Any]] = []
        self.summary_lines: List[str] = []
        self._decision_index = 0

    def record_decision(
            self,
            controller: "DemoSeedController",
            player: Player,
            game_phase: str,
            legal_actions: Any,
            recommended_action: Any,
            explanation: Optional[ActionExplanation],
            dice_roll: Optional[int] = None,
    ) -> None:
        self._decision_index += 1
        concise_text, has_detail = explanation_text(explanation)
        legal_actions_json = json.dumps(serialise_choice(legal_actions), sort_keys=True)
        recommended_action_json = json.dumps(serialise_choice(recommended_action), sort_keys=True)
        row = {
            "seed": self.seed,
            "turn_number": controller.get_game_state().round_num,
            "player_id": player.player_number.name,
            "game_phase": game_phase,
            "dice_roll": dice_roll if dice_roll is not None else "",
            "wood": player.resources.get(Resource.WOOD, 0),
            "brick": player.resources.get(Resource.BRICK, 0),
            "sheep": player.resources.get(Resource.SHEEP, 0),
            "wheat": player.resources.get(Resource.WHEAT, 0),
            "ore": player.resources.get(Resource.ORE, 0),
            "victory_points": player.calc_victory_points()[1],
            "legal_actions": legal_actions_json,
            "tutor_recommended_action": recommended_action_json,
            "tutor_explanation_text": concise_text,
        }
        self.rows.append(row)

        tags = self._interesting_tags(game_phase, recommended_action, explanation)
        if tags:
            self.summary_lines.append(self._summary_line(controller, tags[0], recommended_action, explanation))

    def _interesting_tags(
            self,
            game_phase: str,
            recommended_action: Any,
            explanation: Optional[ActionExplanation],
    ) -> List[str]:
        tags: List[str] = []
        if game_phase in {"INITIAL_SETTLEMENT", "INITIAL_ROAD"}:
            tags.append("OPENING_PLACEMENT")
        if game_phase == "DISCARD":
            tags.append("DISCARD")
        if isinstance(recommended_action, Action):
            if recommended_action.type in {ActionType.TRADE_WITH_BANK, ActionType.TRADE_WITH_PLAYER}:
                tags.append("TRADE")
            if recommended_action.type == ActionType.BUY_DEV_CARD:
                tags.append("BUY_DEV_CARD")
            if recommended_action.type == ActionType.BUILD and isinstance(recommended_action.payload, tuple):
                buildable = recommended_action.payload[0]
                if buildable == Buildable.CITY:
                    tags.append("BUILD_CITY")
            if recommended_action.type == ActionType.END_TURN and explanation is not None:
                detail = explanation.generate_text_detail().lower()
                if "save" in detail and "city" in detail:
                    tags.append("END_TURN_SAVE_FOR_CITY")
        return tags

    def _summary_line(
            self,
            controller: "DemoSeedController",
            tag: str,
            recommended_action: Any,
            explanation: Optional[ActionExplanation],
    ) -> str:
        turn_number = controller.get_game_state().round_num
        if tag == "DISCARD":
            action_text = resource_dict_to_text(recommended_action if isinstance(recommended_action, dict) else {})
            return f"- Turn {turn_number}: DISCARD {action_text}"
        if isinstance(recommended_action, Action):
            return f"- Turn {turn_number}: {tag} {action_to_text(recommended_action, explanation)}"
        return f"- Turn {turn_number}: {tag}"

    def write_outputs(self) -> Path:
        csv_path = self.output_dir / f"demo_seed_{self.seed}_log.csv"

        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(self.rows[0].keys()) if self.rows else [
                "seed",
                "turn_number",
                "player_id",
                "game_phase",
                "dice_roll",
                "wood",
                "brick",
                "sheep",
                "wheat",
                "ore",
                "victory_points",
                "legal_actions",
                "tutor_recommended_action",
                "tutor_explanation_text",
            ])
            writer.writeheader()
            writer.writerows(self.rows)

        return csv_path

    def print_summary(self) -> None:
        print(f"Seed {self.seed}:")
        if self.summary_lines:
            for line in self.summary_lines:
                print(line)
        else:
            print("- No tagged demo candidates found.")


class AutoTutorDemoView(HeadlessView):
    def __init__(self, recorder: DemoRecorder):
        self.recorder = recorder
        self.controller: Optional["DemoSeedController"] = None
        self._debug_tutor_shortcut_handler: Optional[Callable[[], Any]] = None
        self._latest_stage: Optional[TutorStage] = None
        self._latest_explanation: Optional[ActionExplanation] = None
        self._latest_player: Optional[Player] = None

    def set_debug_tutor_shortcut_handler(self, handler):
        self._debug_tutor_shortcut_handler = handler

    def display_start_screen(self) -> GameMode:
        return GameMode.TUTOR

    def display_tutor_init(self, player: Player, stage: TutorStage, explanation: ActionExplanation) -> None:
        self._latest_stage = stage
        self._latest_explanation = explanation
        self._latest_player = player

    def display_board_turn(self, player: Player, dice_info: Tuple[int, int, int],
                           played_dev_card: bool = False) -> Action:
        assert self.controller is not None
        preview_action, explanation = self.controller.preview_tutor_action(player, Phase.MAIN, played_dev_card)
        chosen_action = self._call_debug_handler(preview_action)
        self.recorder.record_decision(
            controller=self.controller,
            player=player,
            game_phase="MAIN_TURN",
            legal_actions=self.controller.describe_main_turn_legal_actions(player, explanation),
            recommended_action=chosen_action,
            explanation=explanation,
            dice_roll=dice_info[2],
        )
        self._clear_latest()
        return chosen_action

    def pre_roll(self, player: Player) -> DevelopmentCardType | bool:
        assert self.controller is not None
        preview_action, explanation = self.controller.preview_tutor_action(player, Phase.PRE_ROLL, False)
        recommended = False if preview_action.type != ActionType.PLAY_DEV_CARD else preview_action.payload
        chosen = self._call_debug_handler(recommended)
        legal_actions = ["skip_dev_card"] + [card.card_type.name for card in player.development_cards if card.playable]
        self.recorder.record_decision(
            controller=self.controller,
            player=player,
            game_phase="PRE_ROLL",
            legal_actions=legal_actions,
            recommended_action=preview_action if chosen else Action(ActionType.ROLL),
            explanation=explanation,
            dice_roll=None,
        )
        self._clear_latest()
        return chosen

    def draw_selectable_vertices(self, vertices: List[Vertex], disable_interactivity: bool = False) -> Vertex:
        assert self.controller is not None
        if disable_interactivity:
            return vertices[0]
        choice = self._call_debug_handler(vertices[0])
        stage_name = self._stage_name_for_vertex_choice()
        self.recorder.record_decision(
            controller=self.controller,
            player=self._latest_player or self.controller.current_human_player,
            game_phase=stage_name,
            legal_actions=[vertex_to_id(vertex) for vertex in vertices],
            recommended_action=choice,
            explanation=self._latest_explanation,
            dice_roll=self.controller.current_dice_total_for_logging(stage_name),
        )
        self._clear_latest()
        return choice

    def draw_selectable_edges(self, edges: List[Edge], disable_interactivity: bool = False) -> Edge:
        assert self.controller is not None
        if disable_interactivity:
            return edges[0]
        choice = self._call_debug_handler(edges[0])
        if self._latest_stage == TutorStage.INITIAL_ROAD:
            stage_name = "INITIAL_ROAD"
        elif self._latest_stage == TutorStage.ROAD_BUILDING:
            stage_name = "ROAD_BUILDING"
        else:
            stage_name = "EDGE_CHOICE"
        self.recorder.record_decision(
            controller=self.controller,
            player=self._latest_player or self.controller.current_human_player,
            game_phase=stage_name,
            legal_actions=[edge_to_id(edge) for edge in edges],
            recommended_action=choice,
            explanation=self._latest_explanation,
            dice_roll=self.controller.current_dice_total_for_logging(stage_name),
        )
        self._clear_latest()
        return choice

    def draw_selectable_tiles(self, tiles: List[HexTile]) -> HexTile:
        assert self.controller is not None
        choice = self._call_debug_handler(tiles[0])
        self.recorder.record_decision(
            controller=self.controller,
            player=self._latest_player or self.controller.current_human_player,
            game_phase="ROBBER_PLACEMENT",
            legal_actions=[hex_to_id(tile) for tile in tiles],
            recommended_action=choice,
            explanation=self._latest_explanation,
            dice_roll=self.controller.current_dice_total_for_logging("ROBBER_PLACEMENT"),
        )
        self._clear_latest()
        return choice

    def show_resource_chooser(self, player: Player, num_resources: int, title: str,
                              resource_caps: Optional[ResourceCount] = None) -> ResourceCount:
        assert self.controller is not None
        choice = self._call_debug_handler({})
        stage_name = self._stage_name_for_resource_choice()
        legal_actions = {
            "summary": f"choose {num_resources} resource(s)",
            "resource_caps": resource_dict_to_plain_dict(resource_caps),
        }
        self.recorder.record_decision(
            controller=self.controller,
            player=player,
            game_phase=stage_name,
            legal_actions=legal_actions,
            recommended_action=choice,
            explanation=self._latest_explanation,
            dice_roll=self.controller.current_dice_total_for_logging(stage_name),
        )
        self._clear_latest()
        return choice

    def display_trade_manager(self, player: Player, selling: ResourceCount, buying: ResourceCount,
                              selling_player: Player):
        assert self.controller is not None
        choice = self._call_debug_handler((False, None))
        legal_actions = {
            "summary": ["reject", "accept", "counteroffer"],
            "selling_player": selling_player.player_number.name,
            "offer_to_you": {
                "you_receive": resource_dict_to_plain_dict(selling),
                "you_give": resource_dict_to_plain_dict(buying),
            },
        }
        self.recorder.record_decision(
            controller=self.controller,
            player=player,
            game_phase="TRADE_RESPONSE",
            legal_actions=legal_actions,
            recommended_action=choice,
            explanation=self._latest_explanation,
            dice_roll=self.controller.current_dice_total_for_logging("TRADE_RESPONSE"),
        )
        self._clear_latest()
        return choice

    def select_player_trade_offer(
            self,
            player: Player,
            selling: ResourceCount,
            buying: ResourceCount,
            willing_players: List[Tuple[Player, Optional[ResourceCount]]],
    ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        assert self.controller is not None
        default = willing_players[0] if willing_players else None
        choice = self._call_debug_handler(default)
        legal_actions = [
            {
                "trade_partner": candidate_player.player_number.name,
                "counteroffer": resource_dict_to_plain_dict(counter),
            }
            for candidate_player, counter in willing_players
        ]
        self.recorder.record_decision(
            controller=self.controller,
            player=player,
            game_phase="TRADE_PARTNER",
            legal_actions=legal_actions,
            recommended_action=choice,
            explanation=self._latest_explanation,
            dice_roll=self.controller.current_dice_total_for_logging("TRADE_PARTNER"),
        )
        self._clear_latest()
        return choice

    def _call_debug_handler(self, fallback: Any) -> Any:
        if self._debug_tutor_shortcut_handler is None:
            return fallback
        result = self._debug_tutor_shortcut_handler()
        return fallback if result is None else result

    def _stage_name_for_vertex_choice(self) -> str:
        if self._latest_stage == TutorStage.INITIAL_SETTLEMENT:
            return "INITIAL_SETTLEMENT"
        if self._latest_stage == TutorStage.ROBBER_STEAL_TARGET:
            return "ROBBER_STEAL_TARGET"
        return "VERTEX_CHOICE"

    def _stage_name_for_resource_choice(self) -> str:
        if self._latest_stage == TutorStage.DISCARD_RESOURCES:
            return "DISCARD"
        if self._latest_stage == TutorStage.YEAR_OF_PLENTY:
            return "YEAR_OF_PLENTY"
        if self._latest_stage == TutorStage.MONOPOLY:
            return "MONOPOLY"
        return "RESOURCE_CHOICE"

    def _clear_latest(self) -> None:
        self._latest_stage = None
        self._latest_explanation = None
        self._latest_player = None


class DemoSeedController(GameController):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_human_player: Optional[Player] = None
        self.current_dice_info: Optional[Tuple[int, int, int]] = None

    def preview_tutor_action(
            self,
            player: Player,
            phase: Phase,
            dev_played: bool,
    ) -> Tuple[Action, ActionExplanation]:
        return self._run_tutor_preview(lambda: self.tutor_ai.next_action_with_explanation(
            player,
            self._game,
            phase=phase,
            dev_played=dev_played,
        ))

    def describe_main_turn_legal_actions(
            self,
            player: Player,
            explanation: Optional[ActionExplanation],
    ) -> List[str]:
        if explanation is not None:
            candidates = [explanation.chosen_action] + [candidate.action for candidate in explanation.alternatives]
            deduped: List[str] = []
            seen = set()
            for action in candidates:
                label = action_to_text(action, explanation)
                if label in seen:
                    continue
                seen.add(label)
                deduped.append(label)
            if deduped:
                return deduped

        legal_actions = ["End turn"]
        buildable_options = self.get_buildable_options(player)
        for buildable, options in buildable_options.items():
            if buildable == Buildable.DEVELOPMENT_CARD and options:
                legal_actions.append("Buy development card")
            elif buildable in {Buildable.ROAD, Buildable.SETTLEMENT, Buildable.CITY}:
                for option in options:
                    legal_actions.append(f"Build {buildable.name.lower()} at {serialise_choice(option)}")
        if player.development_cards:
            legal_actions.extend(
                [f"Play dev card: {card.card_type.name}" for card in player.development_cards if card.playable])
        legal_actions.append("Trade options available via tutor candidate set")
        return legal_actions

    def current_dice_total_for_logging(self, game_phase: str) -> Optional[int]:
        if game_phase in {"INITIAL_SETTLEMENT", "INITIAL_ROAD", "PRE_ROLL"}:
            return None
        if game_phase in {"DISCARD", "ROBBER_PLACEMENT", "ROBBER_STEAL_TARGET"}:
            return 7
        if self.current_dice_info is None:
            return None
        return self.current_dice_info[2]

    def make_round_move(self, player: Player):
        self.current_human_player = player
        try:
            return super().make_round_move(player)
        finally:
            self.current_human_player = None
            self.current_dice_info = None

    def roll_dice(self, player: Player) -> Tuple[int, int, int, Optional[str]]:
        self.view.display_board()
        d1, d2, total = self._game.roll_dice()
        self.current_dice_info = (d1, d2, total)
        msg = None

        if total == Game.ROBBER_DICE_NUM:
            for p in self._game.players:
                discard_count = p.calculate_discard_count()
                if discard_count <= 0:
                    continue

                resources_to_discard = {}
                discard_feedback = None
                if p.is_human:
                    if self.game_mode == self.GameMode.TUTOR:
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
                        resources_to_discard = self.view.show_resource_chooser(
                            p,
                            discard_count,
                            "The robber has been rolled!",
                            p.resources,
                        )
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
                    if self.game_mode == self.GameMode.GUIDED and isinstance(p.policy, RuleBasedAI):
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


def run_demo_seed(seed: int, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    recorder = DemoRecorder(seed=seed, output_dir=output_dir)
    controller = DemoSeedController(
        game_players=STANDARD_SINGLEPLAYER,
        simulation_players=EVO_VS_RULE_BASED,
        game_seed=seed,
    )
    view = AutoTutorDemoView(recorder)
    view.controller = controller
    controller.view = view
    controller.start_game()
    csv_path = recorder.write_outputs()
    recorder.print_summary()
    print(f"CSV written to {csv_path}")
    return csv_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a reproducible tutor demo game for a single seed and log decision points.",
    )
    parser.add_argument("seed", nargs="?", type=int, help="Random seed for the reproducible game.")
    parser.add_argument(
        "--output-dir",
        default="evaluation/logs",
        help="Directory for demo_seed_<seed>_log.csv.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed = args.seed if args.seed is not None else SystemRandom().randint(0, 2 ** 31 - 1)
    run_demo_seed(seed=seed, output_dir=Path(args.output_dir))


if __name__ == "__main__":
    main()
