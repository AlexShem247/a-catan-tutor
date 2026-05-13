from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import List, Tuple, Dict, Optional, Callable, Any

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


class View(ABC):
    ai_decision_animation_delay: float

    @abstractmethod
    def set_debug_tutor_shortcut_handler(self, handler: Optional[Callable[[], Any]]) -> None:
        ...

    @abstractmethod
    def consume_return_home_request(self) -> bool:
        ...

    @abstractmethod
    def display_board(self, player: Optional[Player] = None, msg: Optional[str] = None) -> None:
        ...

    @abstractmethod
    def display_board_ai(self, player: Player, msg: str) -> None:
        ...

    @abstractmethod
    def display_board_turn(self, player: Player, dice_info: Tuple[int, int, int],
                           played_dev_card: bool = False) -> Action:
        ...

    @abstractmethod
    def display_board_turn_ai(self, player: Player, dice_info: Tuple[int, int, int], msg: str, increase_delay=False,
                              ) -> None:
        ...

    @abstractmethod
    def display_board_turn_explanations(self, player: Player, dice_info: Optional[Tuple[int, int, int]],
                                        explanation: ActionExplanation):
        ...

    @abstractmethod
    def display_tutor_init(self, player: Player, stage: TutorStage, explanation: ActionExplanation) -> None:
        ...

    @abstractmethod
    def display_tutor_action_feedback(self, feedback: TutorFeedbackExplanation):
        ...

    @abstractmethod
    def draw_selectable_vertices(self, vertices: List[Vertex], disable_interactivity: bool = False) -> Vertex:
        ...

    @abstractmethod
    def draw_selectable_edges(self, edges: List[Edge], disable_interactivity: bool = False) -> Edge:
        ...

    @abstractmethod
    def draw_selectable_tiles(self, tiles: List[HexTile]) -> HexTile:
        ...

    @abstractmethod
    def draw_buildables(self, buildables: Dict) -> None:
        ...

    @abstractmethod
    def show_resource_chooser(self, player: Player, num_resources: int, title: str,
                              resource_caps: Optional[ResourceCount] = None) -> ResourceCount:
        ...

    @abstractmethod
    def display_trade_manager(self, player: Player, selling: ResourceCount,
                              buying: ResourceCount, selling_player: Player) -> Tuple[bool, Optional[ResourceCount]]:
        ...

    @abstractmethod
    def select_player_trade_offer(
            self,
            player: Player,
            selling: ResourceCount,
            buying: ResourceCount,
            willing_players: List[Tuple[Player, Optional[ResourceCount]]],
    ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        ...

    @abstractmethod
    def pre_roll(self, player: Player) -> DevelopmentCardType | bool:
        ...

    @abstractmethod
    def display_results(self) -> None:
        ...

    @abstractmethod
    def display_start_screen(self) -> GameMode:
        ...

    @abstractmethod
    def open_tutor_menu(self, open_menu: bool):
        ...
