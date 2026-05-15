import math
from typing import Dict, List, Tuple

import pyqtgraph as pg
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QBrush, QCursor, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from config.view_constants import (ENDGAME_PLOT_BACKGROUND_COLOR, ENDGAME_PLOT_HOVER_DISTANCE_THRESHOLD_PX,
                                   ENDGAME_PLOT_LAYOUT_MARGINS, ENDGAME_PLOT_LEGEND_OFFSET,
                                   ENDGAME_PLOT_TARGET_TICK_PIXEL_SPACING, ENDGAME_PLOT_TARGET_VICTORY_POINTS,
                                   ENDGAME_PLOT_TOOLTIP_BORDER_RADIUS_PX, ENDGAME_PLOT_TOOLTIP_OFFSET_PX, PLAYER_COLORS,
                                   TOOLTIP_BACKGROUND_COLOR, TOOLTIP_BORDER_COLOR, TOOLTIP_TEXT_COLOR)
from controllers.GameController import GameController, PlayerScoreSnapshot
from game.Player import Player, PlayerNumber
from view.panels.endgame_summary import describe_round_vp_events, format_endgame_players


class IntegerAxisItem(pg.AxisItem):

    def tickSpacing(self, minVal: float, maxVal: float, size: float) -> List[Tuple[float, float]]:
        """Calculate sensible tick spacing for the integer axis."""
        value_range = abs(maxVal - minVal)
        if value_range <= 0 or size <= 0:
            return [(1.0, 0.0)]

        target_tick_count = max(2, int(size / ENDGAME_PLOT_TARGET_TICK_PIXEL_SPACING))
        raw_spacing = max(1.0, value_range / target_tick_count)
        magnitude = 10**math.floor(math.log10(raw_spacing))

        for multiplier in (1, 2, 5, 10):
            spacing = magnitude * multiplier
            if spacing >= raw_spacing:
                spacing = max(1.0, round(spacing))
                return [(float(spacing), 0.0)]

        spacing = max(1.0, round(magnitude * 10))
        return [(float(spacing), 0.0)]

    def tickStrings(self, values: List[float], scale: float, spacing: float) -> List[str]:
        """Format axis tick values as whole-number labels."""
        return [str(int(round(value))) for value in values]


class HoverTooltip(QFrame):
    BORDER_RADIUS = ENDGAME_PLOT_TOOLTIP_BORDER_RADIUS_PX

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        self.setObjectName("hoverTooltip")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*ENDGAME_PLOT_LAYOUT_MARGINS)
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(False)
        label_palette = self.label.palette()
        label_palette.setColor(self.label.foregroundRole(), TOOLTIP_TEXT_COLOR)
        self.label.setPalette(label_palette)
        layout.addWidget(self.label)
        self.hide()

    def paintEvent(self, event) -> None:
        """Paint the widget contents."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(TOOLTIP_BORDER_COLOR, 1))
        painter.setBrush(QBrush(TOOLTIP_BACKGROUND_COLOR))
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.drawRoundedRect(rect, self.BORDER_RADIUS, self.BORDER_RADIUS)
        super().paintEvent(event)

    def show_text(self, text: str, global_pos) -> None:
        """Show the hover tooltip near the given screen position."""
        self.label.setText(text)
        self.adjustSize()
        if not isinstance(global_pos, QPoint):
            global_pos = QPoint(int(global_pos.x()), int(global_pos.y()))

        x_pos = global_pos.x() + ENDGAME_PLOT_TOOLTIP_OFFSET_PX
        y_pos = global_pos.y() + ENDGAME_PLOT_TOOLTIP_OFFSET_PX

        screen = self.parentWidget().screen() if self.parentWidget() is not None else self.screen()
        if screen is not None:
            screen_rect = screen.availableGeometry()
            if x_pos + self.width() > screen_rect.right():
                x_pos = max(screen_rect.left(), global_pos.x() - self.width() - ENDGAME_PLOT_TOOLTIP_OFFSET_PX)
            if y_pos + self.height() > screen_rect.bottom():
                y_pos = max(screen_rect.top(), global_pos.y() - self.height() - ENDGAME_PLOT_TOOLTIP_OFFSET_PX)

        self.move(x_pos, y_pos)
        self.show()
        self.raise_()


def create_victory_points_plot() -> pg.PlotWidget:
    plot = pg.PlotWidget(axisItems={
        "bottom": IntegerAxisItem(orientation="bottom"),
        "left": IntegerAxisItem(orientation="left"),
    })
    plot.setObjectName("victoryPointsPlot")
    plot.setBackground(ENDGAME_PLOT_BACKGROUND_COLOR)
    plot.setMinimumSize(0, 0)
    return plot


def reset_hover_state(owner) -> None:
    owner.active_tooltip_round = None
    owner.last_tooltip_text = None
    owner.hover_tooltip.hide()


def handle_plot_hover(owner, scene_pos: QPointF) -> None:
    if not owner.plot_points or owner.window.fullscreen_panel is not owner.widget:
        reset_hover_state(owner)
        return

    plot_item = owner.victory_points_plot.getPlotItem()
    view_box = plot_item.vb
    if not owner.victory_points_plot.sceneBoundingRect().contains(scene_pos):
        reset_hover_state(owner)
        return

    nearest_round: int | None = None
    nearest_distance: float | None = None
    for round_num, x_value, y_value in owner.plot_points:
        point_scene = view_box.mapViewToScene(QPointF(x_value, y_value))
        distance = (point_scene.x() - scene_pos.x())**2 + (point_scene.y() - scene_pos.y())**2
        if nearest_distance is None or distance < nearest_distance:
            nearest_round = round_num
            nearest_distance = distance

    if (nearest_round is None or nearest_distance is None
            or nearest_distance > ENDGAME_PLOT_HOVER_DISTANCE_THRESHOLD_PX):
        reset_hover_state(owner)
        return

    tooltip = owner.plot_tooltips.get(nearest_round)
    if not tooltip:
        reset_hover_state(owner)
        return

    global_pos = QCursor.pos()
    if owner.active_tooltip_round == nearest_round and owner.last_tooltip_text == tooltip:
        owner.hover_tooltip.show_text(tooltip, global_pos)
        return

    owner.active_tooltip_round = nearest_round
    owner.last_tooltip_text = tooltip
    owner.hover_tooltip.show_text(tooltip, global_pos)


def build_endgame_plot_tooltips(
    history: List[Tuple[int, Dict[PlayerNumber, PlayerScoreSnapshot]]],
    players: List[Player],
) -> Dict[int, str]:
    player_names = {player.player_number: player.name for player in players}
    tooltips: Dict[int, str] = {}
    previous_snapshot: Dict[PlayerNumber, PlayerScoreSnapshot] | None = None
    for round_num, snapshot in history:
        ranked_players = sorted(snapshot.items(), key=lambda item: item[0].value)
        top_score = max(player_snapshot.total_vp for player_snapshot in snapshot.values())
        leaders = [
            player_names[player_number] for player_number, player_snapshot in ranked_players
            if player_snapshot.total_vp == top_score
        ]
        leader_text = format_endgame_players(leaders)
        if len(leaders) > 1:
            leader_text += " (tied)"
        events = describe_round_vp_events(previous_snapshot, snapshot, player_names)
        lines = [f"Turn {round_num}", ""]
        for player_number, player_snapshot in ranked_players:
            lines.append(f"{player_names[player_number]}: {player_snapshot.total_vp} VP")
        lines.extend(["", f"Leader: {leader_text}"])
        if events:
            lines.append("Event:")
            lines.extend(events)
        else:
            lines.append("Event: None")
        tooltips[round_num] = "\n".join(lines)
        previous_snapshot = snapshot
    return tooltips


def populate_tutor_endgame_performance(owner, controller: GameController) -> None:
    plot_item = owner.victory_points_plot.getPlotItem()
    plot_item.clear()
    owner.plot_points = []
    owner.plot_tooltips = {}
    if plot_item.legend is None:
        plot_item.addLegend(offset=ENDGAME_PLOT_LEGEND_OFFSET)
    else:
        plot_item.legend.clear()

    history = controller.get_victory_point_history()
    review_history = controller.get_endgame_review_history()
    if not history:
        return

    round_values = [round_num for round_num, _ in history]
    max_round = max(round_values)
    max_victory_points = 0

    plot_item.setTitle("Victory Points Over Time")
    plot_item.setLabel("bottom", "Round Number")
    plot_item.setLabel("left", "Victory Points")
    plot_item.showGrid(x=True, y=True, alpha=0.2)
    target_line = pg.InfiniteLine(
        pos=ENDGAME_PLOT_TARGET_VICTORY_POINTS,
        angle=0,
        pen=pg.mkPen(color=(156, 163, 175), width=2, style=Qt.PenStyle.DashLine),
    )
    target_line.setZValue(-10)
    plot_item.addItem(target_line)

    owner.plot_tooltips = build_endgame_plot_tooltips(review_history, controller.get_all_players())

    for player in controller.get_all_players():
        player_rounds: List[int] = []
        player_points: List[int] = []
        for round_num, snapshot in history:
            player_rounds.append(round_num)
            y_value = snapshot.get(player.player_number, 0) + 0.075 - 0.05 * player.player_number.value
            player_points.append(y_value)
            owner.plot_points.append((round_num, float(round_num), float(y_value)))

        max_victory_points = max(max_victory_points, max(player_points, default=0))
        colour = PLAYER_COLORS[player.player_number]
        pen = pg.mkPen((colour.red(), colour.green(), colour.blue()), width=3)
        curve = plot_item.plot(
            player_rounds,
            player_points,
            pen=pen,
            name=player.name,
            symbol="o",
            symbolSize=5,
            symbolBrush=(colour.red(), colour.green(), colour.blue()),
            symbolPen=pen,
        )
        curve.setZValue(100 - player.player_number.value)

    owner.victory_points_plot.setXRange(1, max_round)
    owner.victory_points_plot.setYRange(2, max(ENDGAME_PLOT_TARGET_VICTORY_POINTS, max_victory_points))
