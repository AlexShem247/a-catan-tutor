import math
from typing import Dict

from PyQt6.QtCore import Qt, QRect, QPointF, QSize
from PyQt6.QtGui import QPainter, QCursor, QPixmap
from PyQt6.QtWidgets import QWidget

from drawing.board_geometry import hex_center, vertex_xy
from drawing.constants import WINDOW_HEIGHT, BOARD_BG_COLOR, HEX_TILE_RADIUS, SETTLEMENT_ICONS, hex_to_filepath, \
    EDGE_COLOR, PLAYER_COLORS, ROAD_THICKNESS, VERTEX_SIZE
from drawing.shapes import HexTileShape, Circle, VertexShape, LineShape
from game import Game
from game.Resources import HexType


class SquareCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.square_rect = None
        self.base_scale = None
        self.setMinimumSize(WINDOW_HEIGHT // 2, WINDOW_HEIGHT // 2)
        self.world_size = 1000

        self.zoom = 1.0
        self.min_zoom = 1.0
        self.max_zoom = 20.0

        self.offset = QPointF(0, 0)
        self.last_mouse_pos = None
        self.dragging = False

        self.setMouseTracking(True)

        # List of shapes
        self.shapes = []

        # Load icons
        self.icons: Dict[str, QPixmap] = {}
        for hex_type in HexType:
            filepath = hex_to_filepath(hex_type)
            pm = QPixmap(filepath)
            if not pm.isNull():
                self.icons[filepath] = pm

        for key, path in SETTLEMENT_ICONS.items():
            pm = QPixmap(path)
            if not pm.isNull():
                self.icons[path] = pm

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
        if (event.button() == Qt.MouseButton.LeftButton
                and self.zoom > self.min_zoom
                and self.square_rect.contains(event.position().toPoint())):
            self.dragging = True
            self.last_mouse_pos = event.position()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))

    def mouseMoveEvent(self, event):
        if self.dragging:
            delta = event.position() - self.last_mouse_pos
            self.offset += delta
            self.last_mouse_pos = event.position()
            self.clamp_offset()
            self.update()

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

    def display_board(self, game: Game):
        self.clear_shapes()

        cx = cy = self.world_size // 2
        radius = HEX_TILE_RADIUS

        for tile in game.get_all_hexes():
            x, y = hex_center(tile.q, tile.r, cx, cy, radius)
            self.add_shape(HexTileShape(x, y, radius, tile, self.icons))

        for edge in game.get_all_edges():
            v1, v2 = edge.vertices
            x1, y1 = vertex_xy(v1, cx, cy, radius)
            x2, y2 = vertex_xy(v2, cx, cy, radius)

            color = PLAYER_COLORS[edge.owner.playerNumber] if edge.owner else EDGE_COLOR
            self.add_shape(LineShape(x1, y1, x2, y2, ROAD_THICKNESS, color))

        for vertex in game.get_all_vertices():
            x, y = vertex_xy(vertex, cx, cy, radius)
            self.add_shape(VertexShape(x, y, VERTEX_SIZE, vertex, self.icons))
