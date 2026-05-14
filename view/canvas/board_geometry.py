import math


def hex_center(q, r, cx, cy, radius):
    a = radius * (math.sqrt(3) / 2)
    return (
        cx + q * 2 * a + (r - 2) * a,
        cy + (r - 2) * 1.5 * radius
    )


def vertex_offset(direction, radius):
    angle = math.radians(direction * 60 - 90)
    return radius * math.cos(angle), radius * math.sin(angle)


def vertex_xy(vertex, cx, cy, radius):
    q, r, d = vertex.pos
    x, y = hex_center(q, r, cx, cy, radius)
    dx, dy = vertex_offset(d, radius)
    return x + dx, y + dy
