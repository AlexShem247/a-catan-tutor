from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QEventLoop, QTimer, pyqtBoundSignal
from PyQt6.QtWidgets import QApplication

from ai.actions import Action
from ai.tutor.explanations import ActionExplanation
from ai.tutor.feedback import TutorFeedbackExplanation
from ai.tutor.tutor import TutorStage
from config.view_constants import (AI_DECISION_ANIMATION_DELAY, SECONDS_TO_MILLISECONDS, WINDOW_DEFAULT_X,
                                   WINDOW_DEFAULT_Y, WINDOW_HEIGHT, WINDOW_WIDTH)
from controllers.GameController import GameController
from game.Edge import Edge
from game.HexTile import HexTile
from game.Player import Player
from game.PlayerAssets import DevelopmentCardType
from game.Resources import ResourceCount
from game.Vertex import Vertex
from view.MainWindow import MainWindow
from view.View import GameMode, View


class QtView(View):

    def __init__(self, window: MainWindow, controller: GameController):
        self.window = window
        self.canvas = window.canvas
        self.controller = controller
        self.ai_decision_animation_delay = AI_DECISION_ANIMATION_DELAY
        self.window.setGeometry(WINDOW_DEFAULT_X, WINDOW_DEFAULT_Y, WINDOW_WIDTH, WINDOW_HEIGHT)
        self.window.show()

    def set_debug_tutor_shortcut_handler(self, handler: Optional[Callable[[], Any]]) -> None:
        """Store the debug tutor shortcut handler."""
        self.window.set_debug_tutor_shortcut_handler(handler)

    def consume_return_home_request(self) -> bool:
        """Consume and clear any pending return-home request."""
        return self.window.consume_return_home_request()

    def display_board(self, player: Optional[Player] = None, msg: Optional[str] = None):
        """Render the current board state on the canvas."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        if msg is not None and player is not None:
            self.window.display_generic_info(player, msg)

    def display_board_ai(self, player: Player, msg: str):
        """Display the board while an AI status message is shown."""
        self.window.display_resources(self.controller)
        self.window.display_generic_info(player, msg)
        ai_time_delay(self.ai_decision_animation_delay * 1)

    def display_board_turn(self, player: Player, dice_info: Tuple[int, int, int], played_dev_card: bool = False) \
            -> Action:
        """Display the board and wait for the player turn action."""
        return select_blocking(self, self.window.turnMade, self.window.display_round_info, self.controller, player,
                               dice_info, played_dev_card)

    def display_board_turn_ai(self, player: Player, dice_info: Tuple[int, int, int], msg: str, increase_delay=False):
        """Display the board during an AI turn."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.window.display_round_info_ai_start(player, dice_info, msg)
        delay = AI_DECISION_ANIMATION_DELAY if increase_delay else self.ai_decision_animation_delay
        delay *= 3 if "\n" in msg else 1
        ai_time_delay(self.ai_decision_animation_delay)

    def draw_selectable_vertices(self, vertices: List[Vertex], disable_interactivity: bool = False) -> Optional[Vertex]:
        """Draw selectable vertices on the board."""
        self.canvas.disable_interactivity = disable_interactivity
        self.canvas.draw_selectable_vertices(vertices)
        if not disable_interactivity:
            self.window.set_restore_board_state_callback(lambda: self._restore_selectable_vertices(vertices))
            selected = select_blocking(self, self.canvas.selectionMade, self.canvas.draw_selectable_vertices, vertices)
            self.window.set_restore_board_state_callback(None)
            return selected

    def draw_selectable_edges(self, edges: List[Edge], disable_interactivity: bool = False) -> Optional[Edge]:
        """Draw selectable edges on the board."""
        self.canvas.disable_interactivity = disable_interactivity
        self.canvas.draw_selectable_edges(edges)
        if not disable_interactivity:
            self.window.set_restore_board_state_callback(lambda: self._restore_selectable_edges(edges))
            selected = select_blocking(self, self.canvas.selectionMade, self.canvas.draw_selectable_edges, edges)
            self.window.set_restore_board_state_callback(None)
            return selected

    def draw_selectable_tiles(self, tiles: List[HexTile]) -> HexTile:
        """Draw selectable tiles on the board."""
        self.window.set_restore_board_state_callback(lambda: self._restore_selectable_tiles(tiles))
        selected = select_blocking(self, self.canvas.selectionMade, self.canvas.draw_selectable_tiles, tiles)
        self.window.set_restore_board_state_callback(None)
        return selected

    def draw_buildables(self, buildables: Dict):
        """Draw the currently buildable board options."""
        self.canvas.draw_buildables(buildables)

    def show_resource_chooser(self, player, num_resources: int, title: str,
                              resource_caps: ResourceCount | None = None) -> ResourceCount:
        """Display the resource chooser widget."""
        return select_blocking(self, self.window.resourcesPicked, self.window.show_resource_chooser, player,
                               num_resources, title, resource_caps)

    def display_trade_manager(self, player: Player, selling: ResourceCount, buying: ResourceCount,
                              selling_player: Player) -> Tuple[bool, Optional[ResourceCount]]:
        """Display the trade manager widget."""
        return select_blocking(self, self.window.tradeDecisionMade, self.window.display_trade_manager, player, selling,
                               buying, selling_player)

    def select_player_trade_offer(
        self,
        player: Player,
        selling: ResourceCount,
        buying: ResourceCount,
        willing_players: List[Tuple[Player, Optional[ResourceCount]]],
    ) -> Optional[Tuple[Player, Optional[ResourceCount]]]:
        """Handle select player trade offer."""
        return select_blocking(
            self,
            self.window.tradeSelected,
            self.window.select_player_to_trade,
            self.controller,
            player,
            selling,
            buying,
            willing_players,
        )

    def pre_roll(self, player: Player) -> DevelopmentCardType | bool:
        """Handle the pre-roll development card flow."""
        return select_blocking(
            self,
            self.window.turnMade,
            self.window.development_panel.show_development_menu,
            self.controller,
            player,
            False,
            lambda card: self.window.turnMade.emit(card),
            pre_roll_mode=True,
        )

    def display_results(self):
        """Display the game results view."""
        self.window.display_results(self.controller)

    def display_start_screen(self) -> GameMode:
        """Render the start screen artwork on the canvas."""
        return select_blocking(self, self.window.startGame, self.window.display_start_screen)

    def display_board_turn_explanations(self, player: Player, dice_info: Optional[Tuple[int, int, int]],
                                        explanation: ActionExplanation):
        """Display the board with tutor move explanations."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        return select_blocking(self, self.window.turnMade, self.window.display_explanation, player, dice_info,
                               explanation)

    def display_tutor_init(self, player: Player, stage: TutorStage, explanation: ActionExplanation) -> None:
        """Display the tutor introduction for the current stage."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.window.display_tutor_init(player, stage, explanation)

    def display_tutor_action_feedback(self, feedback: TutorFeedbackExplanation):
        """Display tutor feedback for the player action."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.window.set_debug_tutor_shortcut_handler(lambda: True)
        try:
            return select_blocking(self, self.window.turnMade, self.window.display_tutor_action_feedback, feedback)
        finally:
            self.window.set_debug_tutor_shortcut_handler(None)

    def open_tutor_menu(self, open_menu: bool):
        """Toggle the tutor menu visibility."""
        self.window.configure_tutor_panel(self.controller.game_mode)
        self.window.open_tutor_menu(open_menu)

    def _restore_selectable_vertices(self, vertices: List[Vertex]):
        """Restore the selectable vertex overlay."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.canvas.disable_interactivity = False
        self.canvas.draw_selectable_vertices(vertices)

    def _restore_selectable_edges(self, edges: List[Edge]):
        """Restore the selectable edge overlay."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.canvas.disable_interactivity = False
        self.canvas.draw_selectable_edges(edges)

    def _restore_selectable_tiles(self, tiles: List[HexTile]):
        """Restore the selectable tile overlay."""
        self.canvas.display_board(self.controller)
        self.window.display_resources(self.controller)
        self.canvas.disable_interactivity = False
        self.canvas.draw_selectable_tiles(tiles)


def select_blocking(view: QtView, signal: pyqtBoundSignal, draw_fn, *args, **kwargs) -> Any:
    """Block execution until the signal emits a value, then return that value."""
    loop = QEventLoop()
    selected = None
    app = QApplication.instance()

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
    if app is not None:
        app.aboutToQuit.connect(loop.quit)

    draw_fn(*args, **kwargs)

    loop.exec()

    if getattr(view.window, "app_closing", False):
        raise SystemExit

    # Clean up
    try:
        signal.disconnect(on_selected)
    except TypeError:
        pass
    try:
        view.window.debugShortcutResult.disconnect(on_selected)
    except TypeError:
        pass
    if app is not None:
        try:
            app.aboutToQuit.disconnect(loop.quit)
        except TypeError:
            pass

    view.canvas.clear_interactives()

    return selected


def ai_time_delay(seconds: float):
    if seconds > 0:
        loop = QEventLoop()
        app = QApplication.instance()

        QTimer.singleShot(int(seconds * SECONDS_TO_MILLISECONDS), loop.quit)
        if app is not None:
            app.aboutToQuit.connect(loop.quit)

        loop.exec()
        if app is not None:
            try:
                app.aboutToQuit.disconnect(loop.quit)
            except TypeError:
                pass
