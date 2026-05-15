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
        """Store the debug tutor shortcut handler."""
        ...

    @abstractmethod
    def consume_return_home_request(self) -> bool:
        """Consume and clear any pending return-home request."""
        ...

    @abstractmethod
    def display_board(self, player: Optional[Player] = None, msg: Optional[str] = None) -> None:
        """Render the current board state on the canvas."""
        ...

    @abstractmethod
    def display_board_ai(self, player: Player, msg: str) -> None:
        """Display the board while an AI status message is shown."""
        ...

    @abstractmethod
    def display_board_turn(self, player: Player, dice_info: Tuple[int, int, int],
                           played_dev_card: bool = False) -> Action:
        """Display the board and wait for the player turn action."""
        ...

    @abstractmethod
    def display_board_turn_ai(self, player: Player, dice_info: Tuple[int, int, int], msg: str, increase_delay=False,
                              ) -> None:
        """Display the board during an AI turn."""
        ...

    @abstractmethod
    def display_board_turn_explanations(self, player: Player, dice_info: Optional[Tuple[int, int, int]],
                                        explanation: ActionExplanation):
        """Display the board with tutor move explanations."""
        ...

    @abstractmethod
    def display_tutor_init(self, player: Player, stage: TutorStage, explanation: ActionExplanation) -> None:
        """Display the tutor introduction for the current stage."""
        ...

    @abstractmethod
    def display_tutor_action_feedback(self, feedback: TutorFeedbackExplanation):
        """Display tutor feedback for the player action."""
        ...

    @abstractmethod
    def draw_selectable_vertices(self, vertices: List[Vertex], disable_interactivity: bool = False) -> Vertex:
        """Draw selectable vertices on the board."""
        ...

    @abstractmethod
    def draw_selectable_edges(self, edges: List[Edge], disable_interactivity: bool = False) -> Edge:
        """Draw selectable edges on the board."""
        ...

    @abstractmethod
    def draw_selectable_tiles(self, tiles: List[HexTile]) -> HexTile:
        """Draw selectable tiles on the board."""
        ...

    @abstractmethod
    def draw_buildables(self, buildables: Dict) -> None:
        """Draw the currently buildable board options."""
        ...

    @abstractmethod
    def show_resource_chooser(self, player: Player, num_resources: int, title: str,
                              resource_caps: Optional[ResourceCount] = None) -> ResourceCount:
        """Display the resource chooser widget."""
        ...

    @abstractmethod
    def display_trade_manager(self, player: Player, selling: ResourceCount,
                              buying: ResourceCount, selling_player: Player) -> Tuple[bool, Optional[ResourceCount]]:
        """Display the trade manager widget."""
        ...

    @abstractmethod
    def select_player_trade_offer(
            self,
            player: Player,
            selling: ResourceCount,
            buying: ResourceCount,
            willing_players: List[Tuple[Player, Optional[ResourceCount]]],
    ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        """Handle select player trade offer."""
        ...

    @abstractmethod
    def pre_roll(self, player: Player) -> DevelopmentCardType | bool:
        """Handle the pre-roll development card flow."""
        ...

    @abstractmethod
    def display_results(self) -> None:
        """Display the game results view."""
        ...

    @abstractmethod
    def display_start_screen(self) -> GameMode:
        """Render the start screen artwork on the canvas."""
        ...

    @abstractmethod
    def open_tutor_menu(self, open_menu: bool):
        """Toggle the tutor menu visibility."""
        ...
