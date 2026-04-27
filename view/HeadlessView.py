from typing import List, Tuple, Dict, Optional

from ai.actions import Action, ActionType
from ai.tutor.explanations import ActionExplanation
from ai.tutor.feedback import TutorFeedbackExplanation
from ai.tutor.tutor import TutorStage
from view.View import GameMode, View
from game.Edge import Edge
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import DevelopmentCardType
from game.Resources import ResourceCount
from game.Vertex import Vertex


class HeadlessView(View):
    def set_debug_tutor_shortcut_handler(self, handler):
        pass

    def set_debug_tutor_shortcut_finaliser(self, finaliser):
        pass

    def display_board(self, player: Optional[Player] = None, msg: Optional[str] = None) -> None:
        pass

    def display_board_ai(self, player: Player, msg: str) -> None:
        pass

    def display_board_turn(self, player: Player,
                           dice_info: Tuple[int, int, int],
                           played_dev_card: bool = False) -> Action:
        return Action(ActionType.END_TURN)

    def display_board_turn_ai(self, player: Player,
                              dice_info: Tuple[int, int, int],
                              msg: str,
                              increase_delay=False) -> None:
        pass

    def display_board_turn_explanations(self, player: Player, dice_info: Optional[Tuple[int, int, int]],
                                        explanation: ActionExplanation):
        return None

    def display_tutor_init(self, player: Player, stage: TutorStage, explanation: ActionExplanation) -> None:
        pass

    def display_tutor_action_feedback(self, feedback: TutorFeedbackExplanation):
        return None

    def draw_selectable_vertices(self, vertices: List[Vertex], disable_interactivity: bool = False) -> Vertex:
        return vertices[0]

    def draw_selectable_edges(self, edges: List[Edge], disable_interactivity: bool = False) -> Edge:
        return edges[0]

    def draw_selectable_tiles(self, tiles: List[HexTile]) -> HexTile:
        return tiles[0]

    def draw_buildables(self, buildables: Dict) -> None:
        pass

    def show_resource_chooser(self, player: Player, num_resources: int,
                              title: str, resource_caps: Optional[ResourceCount] = None) -> ResourceCount:
        return {}

    def display_trade_manager(self, player: Player, selling: ResourceCount,
                              buying: ResourceCount, selling_player: Player):
        return False, None

    def select_player_trade_offer(
            self,
            player: Player,
            selling: ResourceCount,
            buying: ResourceCount,
            willing_players: List[Tuple[Player, Optional[ResourceCount]]],
    ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        return willing_players[0] if willing_players else None

    def pre_roll(self, player: Player) -> DevelopmentCardType | bool:
        return False

    def display_results(self) -> None:
        pass

    def display_start_screen(self) -> GameMode:
        return GameMode.SIMULATION

    def open_tutor_menu(self, open_menu: bool):
        pass
