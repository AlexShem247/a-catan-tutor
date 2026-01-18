import math
from typing import Dict, List, Tuple

from PyQt6.QtCore import Qt, QRect, QPointF, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QCursor, QPixmap
from PyQt6.QtWidgets import QWidget

from GameController import GameController
from game.Edge import Edge
from game.HexTile import HexTile
from game.PlayerAssets import Buildable
from game.Resources import HexType
from view.board_geometry import hex_center, vertex_xy
from config.view_constants import WINDOW_HEIGHT, BOARD_BG_COLOR, HEX_TILE_RADIUS, SETTLEMENT_ICONS, hex_to_filepath, \
    EDGE_COLOR, PLAYER_COLORS, ROAD_THICKNESS, VERTEX_SIZE, ROBBER_ICON, HIGHLIGHT_COLOR, OUTLINE_COLOR, \
    PORT_EDGE_COLOR, PORT_ICONS, TITLE_COLOR, SEA_BACKGROUND
from view.shapes import HexTileShape, VertexShape, LineShape, InteractiveShape, InteractiveCircle, PixmapShape, \
    TextShape


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
        self.hovered_shape: InteractiveShape | None = None
        self.disable_interactivity = True

        # Timer for animation
        self.anim_timer = QTimer()
        self.anim_timer.timeout.connect(self.update)
        self.anim_timer.start(16)

        # Load icons
        self.icons: Dict[str, QPixmap] = {}
        for hex_type in HexType:
            filepath = hex_to_filepath(hex_type)
            self.icons[filepath] = QPixmap(filepath)

        for key, path in SETTLEMENT_ICONS.items():
            self.icons[path] = QPixmap(path)

        self.icons[ROBBER_ICON] = QPixmap(ROBBER_ICON)
        self.icons[SEA_BACKGROUND] = QPixmap(SEA_BACKGROUND)

        for key, path in PORT_ICONS.items():
            self.icons[path] = QPixmap(path)

    def sizeHint(self):
        return QSize(WINDOW_HEIGHT, WINDOW_HEIGHT)

    def add_shape(self, shape):
        self.shapes.append(shape)
        self.update()

    def clear_shapes(self):
        self.shapes = []
        self.update()

    def clamp_offset(self):
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
        if event.button() == Qt.MouseButton.LeftButton:

            # Manage object selection
            if not self.disable_interactivity:
                wx, wy = self.screen_to_world(event.position())
                for shape in self.interactive_shapes:
                    if shape.contains(wx, wy):
                        self.selectionMade.emit(shape.payload)
                        return

            # Manage zoom-in
            if (self.zoom > self.min_zoom
                    and self.square_rect.contains(event.position().toPoint())):
                self.dragging = True
                self.last_mouse_pos = event.position()
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))

    def mouseMoveEvent(self, event):
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
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.last_mouse_pos = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def wheelEvent(self, event):
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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        if self.background_image:
            painter.drawPixmap(self.rect(), self.background_image)
        else:
            painter.fillRect(self.rect(), BOARD_BG_COLOR)

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
        self.interactive_shapes.clear()
        self.shapes = [shape for shape in self.shapes if not isinstance(shape, InteractiveShape)]
        self.hovered_shape = None

    def screen_to_world(self, pos):
        scale = self.base_scale * self.zoom
        wx = (pos.x() - self.offset.x()) / scale
        wy = (pos.y() - self.offset.y()) / scale
        return wx, wy

    def display_board(self, controller: GameController):
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

        self.add_shape(TextShape(1000, 980, "Use the scrollbar to zoom in", BOARD_BG_COLOR.lighter(200), font_size=16))

    def draw_selectable_vertices(self, vertices):
        self.interactive_shapes.clear()
        cx, cy = self.get_world_centre()

        for vertex in vertices:
            x, y = vertex_xy(vertex, cx, cy, HEX_TILE_RADIUS)

            shape = InteractiveCircle(x, y, VERTEX_SIZE * 1.5, HIGHLIGHT_COLOR,
                                      outline_color=OUTLINE_COLOR, payload=vertex)

            self.interactive_shapes.append(shape)
            self.add_shape(shape)

    def draw_selectable_edges(self, edges: List[Edge]):
        self.interactive_shapes.clear()
        cx, cy = self.get_world_centre()

        for edge in edges:
            v1, v2 = edge.vertices
            x1, y1 = vertex_xy(v1, cx, cy, HEX_TILE_RADIUS)
            x2, y2 = vertex_xy(v2, cx, cy, HEX_TILE_RADIUS)

            # Midpoint of the edge
            x = (x1 + x2) / 2
            y = (y1 + y2) / 2

            shape = InteractiveCircle(x, y, VERTEX_SIZE * 1.25, HIGHLIGHT_COLOR,
                                      outline_color=OUTLINE_COLOR, payload=edge)

            self.interactive_shapes.append(shape)
            self.add_shape(shape)

    def draw_selectable_tiles(self, tiles: List[HexTile]):
        cx, cy = self.get_world_centre()

        for tile in tiles:
            x, y = hex_center(tile.q, tile.r, cx, cy, HEX_TILE_RADIUS)
            radius = 0.4 * HEX_TILE_RADIUS
            shape = InteractiveCircle(x, y, radius, HIGHLIGHT_COLOR,
                                      outline_color=OUTLINE_COLOR, payload=tile)

            self.interactive_shapes.append(shape)
            self.add_shape(shape)

    def draw_buildables(self, buildables: Dict):
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
        return int(self.world_size * 0.5), int(self.world_size * (21/40))

    def display_start_screen(self):
        self.shapes.clear()
        w, h = self.world_size, self.world_size

        self.background_image = self.icons[SEA_BACKGROUND]

        self.add_shape(TextShape(w * 0.5, h * 0.35, "Catan",
                                 TITLE_COLOR, 200, outline_width=2, bold=True))

        self.add_shape(TextShape(w * 0.5, h * 0.55, "Explainable AI Tutor",
                                 TITLE_COLOR.lighter(150), 40, outline_width=1, bold=True))

        self.add_shape(TextShape(w * 0.5, h * 0.65,
                                 "Your AI guide to smart moves and strategic insights in Catan.",
                                 TITLE_COLOR.lighter(150), 25, bold=True))
