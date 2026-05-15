import math
from typing import Dict, List, Tuple

from PyQt6.QtCore import QPointF, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QFontMetrics, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

from config.view_constants import (BOARD_BG_COLOR, CANVAS_ANIMATION_INTERVAL_MS, CANVAS_ZOOM_HINT_FONT_SIZE_PX,
                                   CANVAS_ZOOM_HINT_PADDING_PX, CITY_OUTLINE, EDGE_COLOR, HEX_TILE_RADIUS,
                                   HIGHLIGHT_COLOR, OUTLINE_COLOR, PLAN_OUTLINE_COLOR, PLAYER_COLORS, PORT_EDGE_COLOR,
                                   PORT_ICONS, ROAD_THICKNESS, ROBBER_ICON, SEA_BACKGROUND, SETTLEMENT_ICONS,
                                   SETTLEMENT_OUTLINE, SETTLEMENT_OUTLINE_SOLID, TITLE_COLOR, VERTEX_SIZE,
                                   WINDOW_HEIGHT, hex_to_filepath)
from game.Edge import Edge
from game.HexTile import HexTile
from game.PlayerAssets import Buildable, Building
from game.Resources import HexType
from view.canvas.board_display_source import BoardDisplaySource
from view.canvas.board_geometry import hex_center, vertex_xy
from view.canvas.shapes import (HexTileShape, InteractiveCircle, InteractivePixmap, InteractiveRoadOverlay,
                                InteractiveRoadVertexOverlay, InteractiveShape, LineShape, PixmapShape,
                                PulsingLineShape, PulsingPixmapShape, TextShape, VertexShape)


class SquareCanvas(QWidget):
    selectionMade = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.square_rect = None
        self.base_scale = None
        self.setMinimumSize(WINDOW_HEIGHT // 2, WINDOW_HEIGHT // 2)
        self.world_size = 1000
        self.background_image = None

        self.zoom = 1.0
        self.min_zoom = 1.0
        self.max_zoom = 20.0

        self.offset = QPointF(0, 0)
        self.last_mouse_pos = None
        self.dragging = False

        self.setMouseTracking(True)

        # List of shapes
        self.shapes = []
        self.interactive_shapes: List[InteractiveShape] = []
        self.planned_builds: List[Tuple] = []
        self.planned_overlay_shapes: List[InteractiveShape] = []
        self.feedback_builds: List[Tuple] = []
        self.feedback_overlay_shapes: List = []
        self.hovered_shape: InteractiveShape | None = None
        self.disable_interactivity = True

        # Timer for animation
        self.anim_timer = QTimer()
        self.anim_timer.timeout.connect(self.update)
        self.anim_timer.start(CANVAS_ANIMATION_INTERVAL_MS)

        # Load icons
        self.icons: Dict[str, QPixmap] = {}
        for hex_type in HexType:
            filepath = hex_to_filepath(hex_type)
            self.icons[filepath] = QPixmap(filepath)

        for key, path in SETTLEMENT_ICONS.items():
            self.icons[path] = QPixmap(path)

        self.icons[ROBBER_ICON] = QPixmap(ROBBER_ICON)
        self.icons[SEA_BACKGROUND] = QPixmap(SEA_BACKGROUND)
        self.icons[SETTLEMENT_OUTLINE] = QPixmap(SETTLEMENT_OUTLINE)
        self.icons[SETTLEMENT_OUTLINE_SOLID] = QPixmap(SETTLEMENT_OUTLINE_SOLID)
        self.icons[CITY_OUTLINE] = QPixmap(CITY_OUTLINE)

        for key, path in PORT_ICONS.items():
            self.icons[path] = QPixmap(path)

    def sizeHint(self):
        """Return the preferred canvas size."""
        return QSize(WINDOW_HEIGHT, WINDOW_HEIGHT)

    def add_shape(self, shape):
        """Add a shape to the canvas."""
        self.shapes.append(shape)
        self.update()

    def clear_shapes(self):
        """Clear all shapes from the canvas."""
        self.shapes = []
        self.update()

    def clamp_offset(self):
        """Clamp the canvas pan offset to the visible bounds."""
        scale = self.base_scale * self.zoom
        world_px = self.world_size * scale
        view_px = self.square_rect.width()

        if world_px <= view_px:
            self.offset = QPointF(self.square_rect.x(), self.square_rect.y())
        else:
            min_x = self.square_rect.x() + view_px - world_px
            max_x = self.square_rect.x()
            min_y = self.square_rect.y() + view_px - world_px
            max_y = self.square_rect.y()
            self.offset.setX(min(max(self.offset.x(), min_x), max_x))
            self.offset.setY(min(max(self.offset.y(), min_y), max_y))

    def mousePressEvent(self, event):
        """Handle mouse press interactions on the canvas."""
        if event.button() == Qt.MouseButton.LeftButton:

            # Manage object selection
            if not self.disable_interactivity:
                wx, wy = self.screen_to_world(event.position())
                for shape in self.interactive_shapes:
                    if shape.contains(wx, wy):
                        self.selectionMade.emit(shape.payload)
                        return

            # Manage zoom-in
            if self.zoom > self.min_zoom and self.square_rect.contains(event.position().toPoint()):
                self.dragging = True
                self.last_mouse_pos = event.position()
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))

    def mouseMoveEvent(self, event):
        """Handle mouse movement for dragging and hover state."""
        # Handle dragging
        if self.dragging:
            delta = event.position() - self.last_mouse_pos
            self.offset += delta
            self.last_mouse_pos = event.position()
            self.clamp_offset()
            self.update()
            return

        # Hover detection (only when not dragging)
        if not self.disable_interactivity:
            wx, wy = self.screen_to_world(event.position())

            new_hover = None
            for shape in self.interactive_shapes:
                if shape.contains(wx, wy):
                    new_hover = shape
                    break

            if new_hover != self.hovered_shape:
                # Remove previous hover
                if self.hovered_shape:
                    self.hovered_shape.set_hover(False)
                # Apply new hover
                if new_hover:
                    new_hover.set_hover(True)

                self.hovered_shape = new_hover
                self.update()

            # Change cursor depending on hover
            if self.hovered_shape:
                self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, event):
        """Handle mouse release interactions on the canvas."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.last_mouse_pos = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def wheelEvent(self, event):
        """Handle mouse-wheel zooming on the canvas."""
        if not self.square_rect.contains(event.position().toPoint()):
            return

        old_zoom = self.zoom
        zoom_factor = 1.15

        if event.angleDelta().y() > 0:
            self.zoom *= zoom_factor
        else:
            self.zoom /= zoom_factor

        self.zoom = max(self.min_zoom, min(self.zoom, self.max_zoom))

        base_scale = self.base_scale
        old_scale = base_scale * old_zoom
        new_scale = base_scale * self.zoom

        mouse_pos = event.position()
        world_before = (mouse_pos - self.offset) / old_scale
        world_after = (mouse_pos - self.offset) / new_scale

        self.offset += (world_after - world_before) * new_scale

        self.clamp_offset()
        self.update()

    def paintEvent(self, event):
        """Paint the widget contents."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        if self.background_image:
            painter.drawPixmap(self.rect(), self.background_image)
        else:
            painter.fillRect(self.rect(), BOARD_BG_COLOR)

            font = painter.font()
            font.setPointSize(CANVAS_ZOOM_HINT_FONT_SIZE_PX)
            painter.setFont(font)

            text = "Use the scrollbar to zoom in"
            fm = QFontMetrics(font)
            text_rect = fm.boundingRect(text)

            padding_x = CANVAS_ZOOM_HINT_PADDING_PX
            padding_y = CANVAS_ZOOM_HINT_PADDING_PX

            x = self.width() - text_rect.width() - padding_x
            y = self.height() - padding_y

            painter.setPen(BOARD_BG_COLOR.lighter(200))
            painter.drawText(x, y, text)

        # Largest square inside widget
        side = min(self.width(), self.height())
        x = (self.width() - side) // 2
        y = (self.height() - side) // 2
        self.square_rect = QRect(x, y, side, side)

        # Base scale
        self.base_scale = side / self.world_size
        scale = self.base_scale * self.zoom

        if self.offset == QPointF(0, 0):
            self.offset = QPointF(self.square_rect.x(), self.square_rect.y())

        self.clamp_offset()

        # Draw all shapes
        for shape in self.shapes:
            shape.draw(painter, scale, self.offset)

    def clear_interactives(self):
        """Clear all interactive shapes from the canvas."""
        self.interactive_shapes.clear()
        self.shapes = [shape for shape in self.shapes if not isinstance(shape, InteractiveShape)]
        self.hovered_shape = None

    def clear_planned_builds(self):
        """Clear the planned build overlays from the canvas."""
        self.planned_builds = []
        self.shapes = [shape for shape in self.shapes if shape not in self.planned_overlay_shapes]
        self.planned_overlay_shapes = []
        self.update()

    def clear_feedback_builds(self):
        """Clear the feedback build overlays from the canvas."""
        self.feedback_builds = []
        self.shapes = [shape for shape in self.shapes if shape not in self.feedback_overlay_shapes]
        self.feedback_overlay_shapes = []
        self.update()

    def screen_to_world(self, pos):
        """Convert screen coordinates into world coordinates."""
        scale = self.base_scale * self.zoom
        wx = (pos.x() - self.offset.x()) / scale
        wy = (pos.y() - self.offset.y()) / scale
        return wx, wy

    def display_board(self, controller: BoardDisplaySource):
        """Render the current board state on the canvas."""
        self.clear_shapes()
        cx, cy = self.get_world_centre()
        self.background_image = None

        for tile in controller.get_all_hexes():
            x, y = hex_center(tile.q, tile.r, cx, cy, HEX_TILE_RADIUS)
            self.add_shape(HexTileShape(x, y, HEX_TILE_RADIUS, tile, self.icons))

        for edge in controller.get_all_edges():
            v1, v2 = edge.vertices
            x1, y1 = vertex_xy(v1, cx, cy, HEX_TILE_RADIUS)
            x2, y2 = vertex_xy(v2, cx, cy, HEX_TILE_RADIUS)

            color = PLAYER_COLORS[edge.owner.player_number] if edge.owner else EDGE_COLOR
            self.add_shape(LineShape(x1, y1, x2, y2, ROAD_THICKNESS, color))

        # Draw ports
        for port, v1, v2 in controller.get_ports():
            x1, y1 = vertex_xy(v1, cx, cy, HEX_TILE_RADIUS)
            x2, y2 = vertex_xy(v2, cx, cy, HEX_TILE_RADIUS)

            # Work out position to draw port
            dx, dy = x2 - x1, y2 - y1
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            dist = math.hypot(dx, dy)
            scale = -0.7
            x = mx - dy / dist * dist * scale
            y = my + dx / dist * dist * scale

            self.add_shape(LineShape(x1, y1, x, y, VERTEX_SIZE, PORT_EDGE_COLOR))
            self.add_shape(LineShape(x2, y2, x, y, VERTEX_SIZE, PORT_EDGE_COLOR))

            scale = -0.75
            x = mx - dy / dist * dist * scale
            y = my + dx / dist * dist * scale

            self.add_shape(PixmapShape(x, y - 30, 80, 80, self.icons[PORT_ICONS[port]]))

        for vertex in controller.get_all_vertices():
            x, y = vertex_xy(vertex, cx, cy, HEX_TILE_RADIUS)
            self.add_shape(VertexShape(x, y, VERTEX_SIZE, vertex, self.icons))

        self._draw_planned_builds(self.planned_builds)
        self._draw_feedback_builds(self.feedback_builds)

    def draw_selectable_vertices(self, vertices):
        """Draw selectable vertices on the board."""
        self.interactive_shapes.clear()
        cx, cy = self.get_world_centre()

        for vertex in vertices:
            x, y = vertex_xy(vertex, cx, cy, HEX_TILE_RADIUS)

            shape = InteractiveCircle(x, y, VERTEX_SIZE * 1.5, HIGHLIGHT_COLOR, outline_color=OUTLINE_COLOR,
                                      payload=vertex)

            self.interactive_shapes.append(shape)
            self.add_shape(shape)

    def draw_selectable_edges(self, edges: List[Edge]):
        """Draw selectable edges on the board."""
        self.interactive_shapes.clear()
        cx, cy = self.get_world_centre()

        for edge in edges:
            v1, v2 = edge.vertices
            x1, y1 = vertex_xy(v1, cx, cy, HEX_TILE_RADIUS)
            x2, y2 = vertex_xy(v2, cx, cy, HEX_TILE_RADIUS)

            # Midpoint of the edge
            x = (x1 + x2) / 2
            y = (y1 + y2) / 2

            shape = InteractiveCircle(x, y, VERTEX_SIZE * 1.25, HIGHLIGHT_COLOR, outline_color=OUTLINE_COLOR,
                                      payload=edge)

            self.interactive_shapes.append(shape)
            self.add_shape(shape)

    def draw_selectable_tiles(self, tiles: List[HexTile]):
        """Draw selectable tiles on the board."""
        cx, cy = self.get_world_centre()

        for tile in tiles:
            x, y = hex_center(tile.q, tile.r, cx, cy, HEX_TILE_RADIUS)
            radius = 0.4 * HEX_TILE_RADIUS
            shape = InteractiveCircle(x, y, radius, HIGHLIGHT_COLOR, outline_color=OUTLINE_COLOR, payload=tile)

            self.interactive_shapes.append(shape)
            self.add_shape(shape)

    def draw_buildables(self, buildables: Dict):
        """Draw the currently buildable board options."""
        # Clear interactive shapes
        self.shapes = [s for s in self.shapes if not isinstance(s, InteractiveShape)]

        # Roads (edges)
        self.draw_selectable_edges(buildables[Buildable.ROAD])

        # Settlements and Cities (vertices)
        buildable_vertices = buildables[Buildable.SETTLEMENT] + buildables[Buildable.CITY]

        interactive_shapes = self.interactive_shapes.copy()
        self.draw_selectable_vertices(buildable_vertices)
        self.interactive_shapes.extend(interactive_shapes)

    def get_world_centre(self) -> Tuple[int, int]:
        """Return the board world centre point."""
        return int(self.world_size * 0.5), int(self.world_size * (21 / 40))

    def display_start_screen(self):
        """Render the start screen artwork on the canvas."""
        self.shapes.clear()
        self.planned_builds = []
        self.planned_overlay_shapes = []
        self.feedback_builds = []
        self.feedback_overlay_shapes = []
        w, h = self.world_size, self.world_size

        self.background_image = self.icons[SEA_BACKGROUND]

        self.add_shape(TextShape(w * 0.5, h * 0.35, "Catan", TITLE_COLOR, 200, outline_width=2, bold=True))

        self.add_shape(
            TextShape(w * 0.5, h * 0.55, "Explainable AI Tutor", TITLE_COLOR.lighter(150), 40, outline_width=1,
                      bold=True))

        self.add_shape(
            TextShape(w * 0.5, h * 0.65, "Your AI guide to smart moves and strategic insights in Catan.",
                      TITLE_COLOR.lighter(150), 25, bold=True))

    def render_planned_builds(self, builds: List[Tuple]):
        """Render the planned build overlays."""
        self.planned_builds = builds.copy()
        self.shapes = [shape for shape in self.shapes if shape not in self.planned_overlay_shapes]
        self.planned_overlay_shapes = []
        self._draw_planned_builds(self.planned_builds)

    def render_feedback_builds(self, builds: List[Tuple]):
        """Render the feedback build overlays."""
        self.feedback_builds = builds.copy()
        self.shapes = [shape for shape in self.shapes if shape not in self.feedback_overlay_shapes]
        self.feedback_overlay_shapes = []
        self._draw_feedback_builds(self.feedback_builds)

    def _draw_planned_builds(self, builds: List[Tuple]):
        """Draw the planned build overlay shapes."""
        cx, cy = self.get_world_centre()

        for buildable, position in builds:
            if buildable == Buildable.ROAD and isinstance(position, Edge):
                v1, v2 = position.vertices
                x1, y1 = vertex_xy(v1, cx, cy, HEX_TILE_RADIUS)
                x2, y2 = vertex_xy(v2, cx, cy, HEX_TILE_RADIUS)

                road_overlay = InteractiveRoadOverlay(x1, y1, x2, y2, ROAD_THICKNESS * 1.5, PLAN_OUTLINE_COLOR,
                                                      payload=(buildable, position), solid=False, normal_alpha=100,
                                                      hover_alpha=255)
                self.planned_overlay_shapes.append(road_overlay)
                self.add_shape(road_overlay)

                for vertex in (v1, v2):
                    if vertex.owner is None and vertex.building is None:
                        x, y = vertex_xy(vertex, cx, cy, HEX_TILE_RADIUS)
                        vertex_overlay = InteractiveRoadVertexOverlay(x, y, VERTEX_SIZE, PLAN_OUTLINE_COLOR,
                                                                      payload=(buildable, vertex), normal_alpha=100,
                                                                      hover_alpha=255)
                        self.planned_overlay_shapes.append(vertex_overlay)
                        self.add_shape(vertex_overlay)

            elif buildable == Buildable.SETTLEMENT and position is not None:
                x, y = vertex_xy(position, cx, cy, HEX_TILE_RADIUS)

                settlement_outline = InteractivePixmap(x, y, VERTEX_SIZE * 4, VERTEX_SIZE * 4,
                                                       self.icons[SETTLEMENT_OUTLINE], payload=(buildable, position))
                self.planned_overlay_shapes.append(settlement_outline)
                self.add_shape(settlement_outline)

                settlement_fill = InteractivePixmap(x, y, VERTEX_SIZE * 4, VERTEX_SIZE * 4,
                                                    self.icons[SETTLEMENT_OUTLINE_SOLID], payload=(buildable, position),
                                                    normal_alpha=150)
                self.planned_overlay_shapes.append(settlement_fill)
                self.add_shape(settlement_fill)

            elif buildable == Buildable.CITY and position is not None:
                x, y = vertex_xy(position, cx, cy, HEX_TILE_RADIUS)

                city_overlay = InteractivePixmap(x, y, VERTEX_SIZE * 4, VERTEX_SIZE * 4, self.icons[CITY_OUTLINE],
                                                 payload=(buildable, position))
                self.planned_overlay_shapes.append(city_overlay)
                self.add_shape(city_overlay)
            elif buildable == "ROBBER_HEX" and isinstance(position, HexTile):
                x, y = hex_center(position.q, position.r, cx, cy, HEX_TILE_RADIUS)
                robber_overlay = InteractiveCircle(x, y, HEX_TILE_RADIUS * 0.4, PLAN_OUTLINE_COLOR,
                                                   outline_color=OUTLINE_COLOR, payload=(buildable, position))
                self.planned_overlay_shapes.append(robber_overlay)
                self.add_shape(robber_overlay)

    def _draw_feedback_builds(self, builds: List[Tuple]):
        """Draw the feedback build overlay shapes."""
        cx, cy = self.get_world_centre()

        for buildable, position, player_number in builds:
            if buildable == Buildable.ROAD and isinstance(position, Edge):
                v1, v2 = position.vertices
                x1, y1 = vertex_xy(v1, cx, cy, HEX_TILE_RADIUS)
                x2, y2 = vertex_xy(v2, cx, cy, HEX_TILE_RADIUS)
                road_shape = PulsingLineShape(x1, y1, x2, y2, ROAD_THICKNESS, PLAYER_COLORS[player_number])
                self.feedback_overlay_shapes.append(road_shape)
                self.add_shape(road_shape)
            elif buildable == Buildable.SETTLEMENT and position is not None:
                x, y = vertex_xy(position, cx, cy, HEX_TILE_RADIUS)
                pixmap = self.icons[SETTLEMENT_ICONS[(player_number, Building.SETTLEMENT)]]
                settlement_shape = PulsingPixmapShape(x, y, VERTEX_SIZE * 4, VERTEX_SIZE * 4, pixmap)
                self.feedback_overlay_shapes.append(settlement_shape)
                self.add_shape(settlement_shape)
            elif buildable == Buildable.CITY and position is not None:
                x, y = vertex_xy(position, cx, cy, HEX_TILE_RADIUS)
                pixmap = self.icons[SETTLEMENT_ICONS[(player_number, Building.CITY)]]
                city_shape = PulsingPixmapShape(x, y, VERTEX_SIZE * 4, VERTEX_SIZE * 4, pixmap)
                self.feedback_overlay_shapes.append(city_shape)
                self.add_shape(city_shape)
