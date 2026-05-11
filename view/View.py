from enum import Enum, auto
from typing import List, Tuple, Dict, Optional, Protocol, Callable, Any

from ai.actions import Action
from ai.tutor.explanations import ActionExplanation
from ai.tutor.feedback import TutorFeedbackExplanation
from ai.tutor.tutor import TutorStage
from game.Edge import Edge
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import DevelopmentCardType
from game.Resources import ResourceCount
from game.Vertex import Vertex


class GameMode(Enum):
    PLAY = auto()
    TUTOR = auto()
    SIMULATION = auto()
    GUIDED = auto()


class View(Protocol):
    ai_decision_animation_delay: float

    def set_debug_tutor_shortcut_handler(self, handler: Optional[Callable[[], Any]]) -> None:
        ...

    def consume_return_home_request(self) -> bool:
        ...

    def display_board(self, player: Optional[Player] = None, msg: Optional[str] = None) -> None:
        ...

    def display_board_ai(self, player: Player, msg: str) -> None:
        ...

    def display_board_turn(self, player: Player, dice_info: Tuple[int, int, int],
                           played_dev_card: bool = False) -> Action:
        ...

    def display_board_turn_ai(self, player: Player, dice_info: Tuple[int, int, int], msg: str, increase_delay=False,
                              ) -> None:
        ...

    def display_board_turn_explanations(self, player: Player, dice_info: Optional[Tuple[int, int, int]],
                                        explanation: ActionExplanation):
        ...

    def display_tutor_init(self, player: Player, stage: TutorStage, explanation: ActionExplanation) -> None:
        ...

    def display_tutor_action_feedback(self, feedback: TutorFeedbackExplanation):
        ...

    def draw_selectable_vertices(self, vertices: List[Vertex], disable_interactivity: bool = False) -> Vertex:
        ...

    def draw_selectable_edges(self, edges: List[Edge], disable_interactivity: bool = False) -> Edge:
        ...

    def draw_selectable_tiles(self, tiles: List[HexTile]) -> HexTile:
        ...

    def draw_buildables(self, buildables: Dict) -> None:
        ...

    def show_resource_chooser(self, player: Player, num_resources: int, title: str,
                              resource_caps: Optional[ResourceCount] = None) -> ResourceCount:
        ...

    def display_trade_manager(self, player: Player, selling: ResourceCount,
                              buying: ResourceCount, selling_player: Player) -> Tuple[bool, Optional[ResourceCount]]:
        ...

    def select_player_trade_offer(
            self,
            player: Player,
            selling: ResourceCount,
            buying: ResourceCount,
            willing_players: List[Tuple[Player, Optional[ResourceCount]]],
    ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        ...

    def pre_roll(self, player: Player) -> DevelopmentCardType | bool:
        ...

    def display_results(self) -> None:
        ...

    def display_start_screen(self) -> GameMode:
        ...

    def open_tutor_menu(self, open_menu: bool):
        ...
