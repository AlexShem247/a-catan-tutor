from typing import List, Dict, Optional, Tuple, Any
from typing import Optional, List, Tuple, Dict, Any, Callable
from PyQt6.QtCore import QEventLoop, QTimer, pyqtBoundSignal

from GameController import GameController
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
from view.MainWindow import MainWindow
from view.View import View, GameMode
from config.view_constants import AI_DECISION_ANIMATION_DELAY, WINDOW_WIDTH, WINDOW_HEIGHT


class QtView(View):
    def __init__(self, window: MainWindow, controller: GameController):
        self.window = window
        self.canvas = window.canvas
        self.controller = controller
        self.ai_decision_animation_delay = AI_DECISION_ANIMATION_DELAY
        self.window.setGeometry(80, 50, WINDOW_WIDTH, WINDOW_HEIGHT)
        self.window.show()

    def set_debug_tutor_shortcut_handler(self, handler: Optional[Callable[[], Any]]) -> None:
        self.window.set_debug_tutor_shortcut_handler(handler)

    def consume_return_home_request(self) -> bool:
        return self.window.consume_return_home_request()

    def display_board(self, player: Optional[Player] = None, msg: Optional[str] = None):
        """Hook to display the board in the Qt window."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        if msg is not None and player is not None:
            self.window.display_generic_info(player, msg)

    def display_board_ai(self, player: Player, msg: str):
        """Hook to display the board in the Qt window."""
        self.window.display_resources(self.controller)
        self.window.display_generic_info(player, msg)
        ai_time_delay(self.ai_decision_animation_delay * 1)

    def display_board_turn(self, player: Player, dice_info: Tuple[int, int, int], played_dev_card: bool = False) \
            -> Action:
        """Hook to display the board in the Qt window."""
        return select_blocking(self, self.window.turnMade, self.window.display_round_info, self.controller,
                               player, dice_info, played_dev_card)

    def display_board_turn_ai(self, player: Player, dice_info: Tuple[int, int, int], msg: str, increase_delay=False):
        """Hook to display the board in the Qt window."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.window.display_round_info_ai_start(player, dice_info, msg)
        # delay = AI_DECISION_ANIMATION_DELAY if increase_delay else self.ai_decision_animation_delay
        # delay *= 3 if "\n" in msg else 1
        ai_time_delay(self.ai_decision_animation_delay)

    def draw_selectable_vertices(self, vertices: List[Vertex], disable_interactivity: bool = False) -> Optional[Vertex]:
        """Draws which vertices are selectable"""
        self.canvas.disable_interactivity = disable_interactivity
        self.canvas.draw_selectable_vertices(vertices)
        if not disable_interactivity:
            self.window.set_restore_board_state_callback(
                lambda: self._restore_selectable_vertices(vertices)
            )
            selected = select_blocking(self, self.canvas.selectionMade, self.canvas.draw_selectable_vertices, vertices)
            self.window.set_restore_board_state_callback(None)
            return selected

    def draw_selectable_edges(self, edges: List[Edge], disable_interactivity: bool = False) -> Optional[Edge]:
        """Draws which edges are selectable"""
        self.canvas.disable_interactivity = disable_interactivity
        self.canvas.draw_selectable_edges(edges)
        if not disable_interactivity:
            self.window.set_restore_board_state_callback(
                lambda: self._restore_selectable_edges(edges)
            )
            selected = select_blocking(self, self.canvas.selectionMade, self.canvas.draw_selectable_edges, edges)
            self.window.set_restore_board_state_callback(None)
            return selected

    def draw_selectable_tiles(self, tiles: List[HexTile]) -> HexTile:
        """Draws which tiles are selectable"""
        self.window.set_restore_board_state_callback(
            lambda: self._restore_selectable_tiles(tiles)
        )
        selected = select_blocking(self, self.canvas.selectionMade, self.canvas.draw_selectable_tiles, tiles)
        self.window.set_restore_board_state_callback(None)
        return selected

    def draw_buildables(self, buildables: Dict):
        """Draws which tiles are selectable"""
        self.canvas.draw_buildables(buildables)

    def show_resource_chooser(self, player, num_resources: int, title: str,
                              resource_caps: ResourceCount | None = None) -> ResourceCount:
        return select_blocking(self, self.window.resourcesPicked, self.window.show_resource_chooser,
                               player, num_resources, title, resource_caps)

    def display_trade_manager(self, player: Player, selling: ResourceCount,
                              buying: ResourceCount, selling_player: Player) -> Tuple[bool, Optional[ResourceCount]]:
        """Displays trade and allows the option to accept, cancel or propose counter-offer"""
        return select_blocking(
            self, self.window.tradeDecisionMade, self.window.display_trade_manager, player, selling,
            buying, selling_player
        )

    def select_player_trade_offer(
            self,
            player: Player,
            selling: ResourceCount,
            buying: ResourceCount,
            willing_players: List[Tuple[Player, Optional[ResourceCount]]],
    ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        return select_blocking(
            self, self.window.tradeSelected, self.window.select_player_to_trade,
            self.controller, player, selling, buying, willing_players,
        )

    def pre_roll(self, player: Player) -> DevelopmentCardType | bool:
        """Allows user to play development card before rolling dice"""
        return select_blocking(self, self.window.turnMade, self.window.show_development_menu, self.controller,
                               player, False, lambda card: self.window.turnMade.emit(card), pre_roll_mode=True)

    def display_results(self):
        """Display game results"""
        self.window.display_results(self.controller)

    def display_start_screen(self) -> GameMode:
        return select_blocking(self, self.window.startGame, self.window.display_start_screen)

    def display_board_turn_explanations(self, player: Player, dice_info: Optional[Tuple[int, int, int]],
                                        explanation: ActionExplanation):
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        return select_blocking(self, self.window.turnMade, self.window.display_explanation,
                               player, dice_info, explanation)

    def display_tutor_init(self, player: Player, stage: TutorStage, explanation: ActionExplanation) -> None:
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.window.display_tutor_init(player, stage, explanation)

    def display_tutor_action_feedback(self, feedback: TutorFeedbackExplanation):
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.window.set_debug_tutor_shortcut_handler(lambda: True)
        try:
            return select_blocking(self, self.window.turnMade, self.window.display_tutor_action_feedback, feedback)
        finally:
            self.window.set_debug_tutor_shortcut_handler(None)

    def open_tutor_menu(self, open_menu: bool):
        self.window.configure_tutor_panel(self.controller.game_mode)
        self.window.open_tutor_menu(open_menu)

    def _restore_selectable_vertices(self, vertices: List[Vertex]):
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.canvas.disable_interactivity = False
        self.canvas.draw_selectable_vertices(vertices)

    def _restore_selectable_edges(self, edges: List[Edge]):
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.canvas.disable_interactivity = False
        self.canvas.draw_selectable_edges(edges)

    def _restore_selectable_tiles(self, tiles: List[HexTile]):
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.canvas.disable_interactivity = False
        self.canvas.draw_selectable_tiles(tiles)


def select_blocking(view: QtView, signal: pyqtBoundSignal, draw_fn, *args, **kwargs) -> Any:
    """Block execution until the signal emits a value, then return that value."""
    loop = QEventLoop()
    selected = None

    def on_selected(obj):
        nonlocal selected
        selected = obj
        loop.quit()

    # Disconnect all previous handlers safely
    try:
        signal.disconnect()
    except TypeError:
        pass

    # Connect the new handler
    signal.connect(on_selected)
    view.window.debugShortcutResult.connect(on_selected)

    draw_fn(*args, **kwargs)

    loop.exec()

    # Clean up
    try:
        signal.disconnect(on_selected)
    except TypeError:
        pass
    try:
        view.window.debugShortcutResult.disconnect(on_selected)
    except TypeError:
        pass

    view.canvas.clear_interactives()

    return selected


def ai_time_delay(seconds: float):
    if seconds > 0:
        loop = QEventLoop()

        QTimer.singleShot(int(seconds * 1000), loop.quit)

        loop.exec()
