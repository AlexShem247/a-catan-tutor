from enum import Enum, auto
from typing import List, Tuple, Dict, Optional, Protocol

from ai.ai_utils.explanations import ActionExplanation
from game.Edge import Edge
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import DevelopmentCardType
from game.Resources import ResourceCount
from game.Vertex import Vertex


class GameMode(Enum):
    PLAY = auto()
    SIMULATION = auto()
    GUIDED = auto()


class View(Protocol):

    def display_board(self, player: Optional[Player] = None, msg: Optional[str] = None) -> None:
        ...

    def display_board_ai(self, player: Player, msg: str) -> None:
        ...

    def display_board_turn(self, player: Player, dice_info: Tuple[int, int, int],
                           played_dev_card: bool = False) -> None:
        ...

    def display_board_turn_ai(self, player: Player, dice_info: Tuple[int, int, int], msg: str, increase_delay=False,
                              ) -> None:
        ...

    def display_board_turn_explanations(self, player: Player, dice_info: Optional[Tuple[int, int, int]],
                                        explanation: ActionExplanation) -> None:
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

    def pre_roll(self, player: Player) -> DevelopmentCardType | bool:
        ...

    def display_results(self) -> None:
        ...

    def display_start_screen(self) -> GameMode:
        ...

    def open_tutor_menu(self, open_menu: bool):
        ...
