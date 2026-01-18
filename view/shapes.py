import math
import time
from collections import Counter
from typing import Dict

from PyQt6.QtCore import QPointF, Qt, QPoint
from PyQt6.QtGui import QPolygonF, QPixmap, QPen, QColor, QFontMetrics

from view.constants import TERRAIN_COLORS, TOKEN_COMMON_COLOR, TOKEN_COLOR, TOKEN_OUTLINE_COLOR, EDGE_COLOR, \
    hex_to_filepath, SETTLEMENT_ICONS, PLAYER_COLORS, ROBBER_ICON, HIGHLIGHT_ANIMATION
from game.HexTile import HexTile
from game.Vertex import Vertex


class Shape:
    def draw(self, painter, scale, offset):
        raise NotImplementedError


class Circle(Shape):
    def __init__(self, x: float, y: float, r: float, color: QColor, outline_color=None):
        self.x = int(x)
        self.y = int(y)
        self.r = int(r)
        self.color = color
        self.outline_color = outline_color

    def draw(self, painter, scale, offset):
        # Brush = fill color
        painter.setBrush(self.color)

        # Pen = outline color if provided
        if self.outline_color:
            painter.setPen(QPen(self.outline_color))
        else:
            painter.setPen(Qt.PenStyle.NoPen)

        px = self.x * scale + offset.x()
        py = self.y * scale + offset.y()
        pr = self.r * scale

        painter.drawEllipse(int(px - pr), int(py - pr), int(pr * 2), int(pr * 2))


class LineShape(Shape):
    def __init__(self, x1: float, y1: float, x2: float, y2: float, thickness: float, color: QColor):
        """
        x1, y1 = start point
        x2, y2 = end point
        thickness = line width
        color = QColor
        """
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.thickness = thickness
        self.color = color

    def draw(self, painter, scale, offset):
        pen = QPen(self.color)
        pen.setWidthF(self.thickness * scale)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        px1 = self.x1 * scale + offset.x()
        py1 = self.y1 * scale + offset.y()
        px2 = self.x2 * scale + offset.x()
        py2 = self.y2 * scale + offset.y()

        painter.drawLine(int(px1), int(py1), int(px2), int(py2))


class Rectangle(Shape):
    def __init__(self, x: float, y: float, w: float, h: float, color: QColor):
        self.x = int(x)
        self.y = int(y)
        self.w = w
        self.h = h
        self.color = color

    def draw(self, painter, scale, offset):
        painter.setBrush(self.color)
        painter.setPen(Qt.PenStyle.NoPen)
        px = self.x * scale + offset.x()
        py = self.y * scale + offset.y()
        pw = self.w * scale
        ph = self.h * scale
        painter.drawRect(int(px), int(py), int(pw), int(ph))


class TextShape(Shape):
    def __init__(self, x: float, y: float, text: str, color: QColor, font_size=20,
                 outline_color=QColor("black"), outline_width=0, bold=False):
        self.x = int(x)
        self.y = int(y)
        self.text = text
        self.color = color
        self.font_size = font_size
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.bold = bold

    def draw(self, painter, scale, offset):
        font = painter.font()
        font.setPointSizeF(self.font_size * scale)
        font.setBold(self.bold)
        painter.setFont(font)

        px = self.x * scale + offset.x()
        py = self.y * scale + offset.y()

        # Get bounding rect for the text
        fm = QFontMetrics(font)
        text_rect = fm.boundingRect(self.text)

        # Always add a minimum padding to avoid clipping
        min_padding = 2  # pixels
        outline_padding = max(self.outline_width * 2, min_padding)
        text_rect.adjust(-outline_padding, -outline_padding, outline_padding, outline_padding)

        # Center rect at (px, py)
        text_rect.moveCenter(QPoint(int(px), int(py)))

        # Draw outline if requested
        if self.outline_width > 0:
            painter.setPen(QPen(self.outline_color, self.outline_width))
            for dx in (-self.outline_width, 0, self.outline_width):
                for dy in (-self.outline_width, 0, self.outline_width):
                    if dx != 0 or dy != 0:
                        painter.drawText(text_rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, self.text)

        # Draw main text on top
        painter.setPen(self.color)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.text)


class Hexagon(Shape):
    def __init__(self, x: float, y: float, radius: float, color: QColor):
        """
        x, y = center of the hexagon in world coordinates
        radius = distance from center to any vertex
        color = QColor
        """
        self.x = int(x)
        self.y = int(y)
        self.radius = int(radius)
        self.color = color

    def draw(self, painter, scale, offset):
        painter.setBrush(self.color)
        painter.setPen(Qt.PenStyle.NoPen)

        # Scale size
        s = self.radius * scale
        cx = self.x * scale + offset.x()
        cy = self.y * scale + offset.y()

        # Calculate the 6 points (pointing up)
        points = []
        for i in range(6):
            angle_deg = 60 * i - 30  # -30 so the first point is top
            angle_rad = math.radians(angle_deg)
            px = cx + s * math.cos(angle_rad)
            py = cy + s * math.sin(angle_rad)
            points.append(QPointF(px, py))

        polygon = QPolygonF(points)
        painter.drawPolygon(polygon)


class PixmapShape(Shape):
    def __init__(self, x: float, y: float, width: float, height: float, pixmap: QPixmap):
        """
        x, y = center of the pixmap in world coordinates
        width, height = size of the pixmap in world units
        pixmap = QPixmap to draw
        """
        self.x = int(x)
        self.y = int(y)
        self.width = int(width)
        self.height = int(height)
        self.pixmap = pixmap

    def draw(self, painter, scale, offset):
        # Scale width and height
        w = self.width * scale
        h = self.height * scale

        # Top-left position for centering
        px = self.x * scale + offset.x() - w / 2
        py = self.y * scale + offset.y() - h / 2

        # Draw scaled pixmap
        painter.drawPixmap(
            int(px),
            int(py),
            self.pixmap.scaled(
                int(w),
                int(h),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
        )


class HexTileShape(Shape):
    def __init__(self, x: float, y: float, radius: float, tile: HexTile, icons: Dict[str, QPixmap]):
        """
        x, y = center of hex
        radius = hex radius
        tile = HexTile
        icon = QPixmap icon for tile resource
        """
        self.shapes = []

        # Hexagon
        self.shapes.append(Hexagon(x, y, radius, TERRAIN_COLORS[tile.type]))

        # Icon
        icon_size = radius * 0.75
        vertical_offset = -0.4 * radius
        self.shapes.append(PixmapShape(x, y + vertical_offset, icon_size, icon_size, icons[hex_to_filepath(tile.type)]))

        # Token
        if tile.production_number or tile.robber:
            token_offset_y = 0.35 * radius
            cx = x
            cy = y + token_offset_y
            token_radius = radius * 0.3

            if tile.production_number:
                # Token background
                self.shapes.append(Circle(cx, cy, token_radius, TOKEN_COLOR, TOKEN_OUTLINE_COLOR))

            if tile.robber:
                shape_radius = 1.8 * token_radius
                self.shapes.append(PixmapShape(cx, cy, shape_radius, shape_radius, icons[ROBBER_ICON]))
            if tile.production_number and not tile.robber:

                # Number
                colour = TOKEN_COMMON_COLOR if tile.production_number in (6, 8) else TOKEN_OUTLINE_COLOR
                self.shapes.append(TextShape(cx, cy - 5, str(tile.production_number), colour))

                # Frequency dots
                dots_map = {
                    2: 1, 3: 2, 4: 3, 5: 4, 6: 5,
                    8: 5, 9: 4, 10: 3, 11: 2, 12: 1
                }
                dots = dots_map.get(tile.production_number, 0)
                if dots > 0:
                    spacing = 0.2 * token_radius
                    total_width = (dots - 1) * spacing
                    dot_radius = 0.08 * token_radius
                    for i in range(dots):
                        dx = cx - total_width / 2 + i * spacing
                        dy = cy + 0.5 * token_radius
                        self.shapes.append(Circle(dx, dy, dot_radius, colour))

    def draw(self, painter, scale, offset):
        for shape in self.shapes:
            shape.draw(painter, scale, offset)


class VertexShape(Shape):
    def __init__(self, x: float, y: float, radius: float, vertex: Vertex, icons: Dict):
        self.shapes = []

        if vertex.building and vertex.owner:
            pixmap = icons[SETTLEMENT_ICONS[vertex.owner.player_number, vertex.building]]
            icon_size = 4.0 * radius
            self.shapes.append(PixmapShape(x, y, icon_size, icon_size, pixmap))
        else:
            color = next(
                (PLAYER_COLORS[p.player_number] for p, c in Counter(e.owner for e in vertex.edges if e.owner).items() if
                 c >= 2),
                EDGE_COLOR
            )
            self.shapes.append(Circle(x, y, radius, color))

    def draw(self, painter, scale, offset):
        for shape in self.shapes:
            shape.draw(painter, scale, offset)


class InteractiveShape(Shape):
    def __init__(self, payload=None):
        self.payload = payload
        self.hovered = False

    def contains(self, wx: float, wy: float) -> bool:
        """World-space hit test"""
        raise NotImplementedError

    def set_hover(self, hovered: bool):
        self.hovered = hovered


class InteractiveCircle(InteractiveShape):
    def __init__(self, x: float, y: float, r: float, color: QColor, outline_color=None, payload=None,
                 normal_alpha=90, hover_alpha=180):
        super().__init__(payload)

        self.x = float(x)
        self.y = float(y)
        self.r = float(r)
        self.base_r = r  # store original radius

        self.base_color = QColor(color)
        self.outline_color = outline_color

        self.normal_alpha = normal_alpha
        self.hover_alpha = hover_alpha

        self.color = QColor(self.base_color)
        self.color.setAlpha(self.normal_alpha)

        # Animation parameters
        self.pulse_amplitude = 0.10  # fraction of size to pulse
        self.pulse_speed = 0.5       # cycles per second
        self._start_time = time.time()

    def current_radius(self):
        """Compute animated radius based on elapsed time."""
        if not HIGHLIGHT_ANIMATION:
            return self.base_r

        t = time.time() - self._start_time
        pulse = math.sin(2 * math.pi * self.pulse_speed * t) * self.pulse_amplitude
        return self.base_r * (1 + pulse)

    def contains(self, wx: float, wy: float) -> bool:
        dx = wx - self.x

        dy = wy - self.y
        return dx * dx + dy * dy <= self.r * self.r

    def set_hover(self, hovered: bool):
        super().set_hover(hovered)

        self.color.setAlpha(self.hover_alpha if hovered else self.normal_alpha)

    def draw(self, painter, scale, offset):
        painter.setBrush(self.color)

        if self.outline_color:
            painter.setPen(QPen(self.outline_color))
        else:
            painter.setPen(Qt.PenStyle.NoPen)

        px = self.x * scale + offset.x()
        py = self.y * scale + offset.y()
        pr = self.current_radius() * scale  # use animated radius

        painter.drawEllipse(int(px - pr), int(py - pr), int(pr * 2), int(pr * 2))
