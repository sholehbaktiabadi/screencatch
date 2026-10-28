"""Annotation shapes.

All coordinates are in image pixels. Only cairo and Pango are used here so the
module works headless (unit tests, export) without a display connection.
"""

from __future__ import annotations

import math

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_foreign("cairo")
from gi.repository import Pango, PangoCairo  # noqa: E402

RGBA = tuple[float, float, float, float]

DEFAULT_COLOR: RGBA = (0.878, 0.106, 0.141, 1.0)  # #e01b24
HIGHLIGHTER_ALPHA = 0.4
FONT_FAMILY = "Sans Bold"


def parse_color(spec: str) -> RGBA:
    """Parse ``#rrggbb`` or ``#rrggbbaa`` into a float RGBA tuple."""
    value = spec.strip().lstrip("#")
    if len(value) not in (6, 8):
        raise ValueError(f"invalid color: {spec!r}")
    try:
        channels = [int(value[i : i + 2], 16) / 255 for i in range(0, len(value), 2)]
    except ValueError as exc:
        raise ValueError(f"invalid color: {spec!r}") from exc
    if len(channels) == 3:
        channels.append(1.0)
    return tuple(channels)  # type: ignore[return-value]


def color_to_hex(color: RGBA) -> str:
    r, g, b, a = (max(0, min(255, round(c * 255))) for c in color)
    if a == 255:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"#{r:02x}{g:02x}{b:02x}{a:02x}"


def luminance(color: RGBA) -> float:
    r, g, b, _a = color
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_color(color: RGBA) -> RGBA:
    """Black or white, whichever reads better on top of ``color``."""
    return (0.0, 0.0, 0.0, 1.0) if luminance(color) > 0.6 else (1.0, 1.0, 1.0, 1.0)


def distance_to_segment(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def snap_angle(x0, y0, x1, y1, step=math.pi / 4):
    """Snap the end point so the segment angle is a multiple of ``step``."""
    length = math.hypot(x1 - x0, y1 - y0)
    if length == 0:
        return x1, y1
    angle = round(math.atan2(y1 - y0, x1 - x0) / step) * step
    return x0 + length * math.cos(angle), y0 + length * math.sin(angle)


def snap_square(x0, y0, x1, y1):
    """Adjust the end point so the box spanned with the start point is square."""
    side = max(abs(x1 - x0), abs(y1 - y0))
    return x0 + math.copysign(side, x1 - x0 or 1), y0 + math.copysign(side, y1 - y0 or 1)


def normalize_rect(x0, y0, x1, y1):
    """Return ``(x, y, w, h)`` with non-negative width and height."""
    return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)


_measure_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
_measure_context = cairo.Context(_measure_surface)


class Shape:
    """Base class for every annotation."""

    tool = ""

    def __init__(self, color: RGBA, width: float):
        self.color = color
        self.width = float(width)

    # -- geometry -----------------------------------------------------------
    def bounds(self) -> tuple[float, float, float, float]:
        """Return ``(x0, y0, x1, y1)`` covering everything the shape paints."""
        raise NotImplementedError

    def hit_test(self, x: float, y: float, tolerance: float) -> bool:
        raise NotImplementedError

    def translate(self, dx: float, dy: float) -> None:
        raise NotImplementedError

    def update(self, x: float, y: float, constrain: bool = False) -> None:
        """Called while the shape is being created by dragging to ``(x, y)``."""

    def is_valid(self) -> bool:
        return True

    # -- style --------------------------------------------------------------
    def get_style(self) -> tuple[RGBA, float]:
        return self.color, self.width

    def set_style(self, color: RGBA, width: float) -> None:
        self.color = color
        self.width = float(width)

    # -- painting -----------------------------------------------------------
    def draw(self, cr: cairo.Context, base: cairo.ImageSurface) -> None:
        raise NotImplementedError

    def _use_color(self, cr, alpha=None):
        r, g, b, a = self.color
        cr.set_source_rgba(r, g, b, a if alpha is None else alpha)


class _BoxShape(Shape):
    """A shape defined by a drag rectangle."""

    def __init__(self, x, y, color, width):
        super().__init__(color, width)
        self.x0 = self.x1 = float(x)
        self.y0 = self.y1 = float(y)

    @property
    def rect(self):
        return normalize_rect(self.x0, self.y0, self.x1, self.y1)

    def update(self, x, y, constrain=False):
        if constrain:
            x, y = snap_square(self.x0, self.y0, x, y)
        self.x1, self.y1 = float(x), float(y)

    def translate(self, dx, dy):
        self.x0 += dx
        self.x1 += dx
        self.y0 += dy
        self.y1 += dy

    def is_valid(self):
        _x, _y, w, h = self.rect
        return w >= 3 and h >= 3

    def bounds(self):
        x, y, w, h = self.rect
        pad = self.width / 2
        return x - pad, y - pad, x + w + pad, y + h + pad


class RectangleShape(_BoxShape):
    tool = "rectangle"

    def draw(self, cr, base):
        x, y, w, h = self.rect
        cr.save()
        self._use_color(cr)
        cr.set_line_width(self.width)
        cr.set_line_join(cairo.LINE_JOIN_MITER)
        cr.rectangle(x, y, w, h)
        cr.stroke()
        cr.restore()

    def hit_test(self, x, y, tolerance):
        rx, ry, w, h = self.rect
        reach = tolerance + self.width / 2
        inside_outer = rx - reach <= x <= rx + w + reach and ry - reach <= y <= ry + h + reach
        inside_inner = rx + reach < x < rx + w - reach and ry + reach < y < ry + h - reach
        return inside_outer and not inside_inner


class EllipseShape(_BoxShape):
    tool = "ellipse"

    def draw(self, cr, base):
        x, y, w, h = self.rect
        if w <= 0 or h <= 0:
            return
        cr.save()
        cr.new_path()
        cr.translate(x + w / 2, y + h / 2)
        cr.scale(w / 2, h / 2)
        cr.arc(0, 0, 1, 0, 2 * math.pi)
        cr.restore()
        cr.save()
        self._use_color(cr)
        cr.set_line_width(self.width)
        cr.stroke()
        cr.restore()

    def hit_test(self, x, y, tolerance):
        rx, ry, w, h = self.rect
        a, b = w / 2, h / 2
        if a <= 0 or b <= 0:
            return False
        cx, cy = rx + a, ry + b
        normalized = math.hypot((x - cx) / a, (y - cy) / b)
        return abs(normalized - 1) * min(a, b) <= tolerance + self.width / 2


class PixelateShape(_BoxShape):
    """Hides the area beneath it by pixelating the original screenshot."""

    tool = "pixelate"

    @property
    def block_size(self) -> int:
        return max(6, round(self.width * 3))

    def bounds(self):
        x, y, w, h = self.rect
        return x, y, x + w, y + h

    def hit_test(self, x, y, tolerance):
        rx, ry, w, h = self.rect
        return rx - tolerance <= x <= rx + w + tolerance and ry - tolerance <= y <= ry + h + tolerance

    def draw(self, cr, base):
        x, y, w, h = self.rect
        x0 = max(0, math.floor(x))
        y0 = max(0, math.floor(y))
        x1 = min(base.get_width(), math.ceil(x + w))
        y1 = min(base.get_height(), math.ceil(y + h))
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            return
        block = self.block_size
        small_w, small_h = math.ceil(w / block), math.ceil(h / block)
        small = cairo.ImageSurface(cairo.FORMAT_ARGB32, small_w, small_h)
        sc = cairo.Context(small)
        sc.scale(small_w / w, small_h / h)
        sc.set_source_surface(base, -x0, -y0)
        source = sc.get_source()
        source.set_filter(cairo.FILTER_GOOD)
        source.set_extend(cairo.EXTEND_PAD)
        sc.paint()
        small.flush()

        cr.save()
        cr.rectangle(x0, y0, w, h)
        cr.clip()
        cr.translate(x0, y0)
        cr.scale(w / small_w, h / small_h)
        cr.set_source_surface(small, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()
        cr.restore()


class LineShape(Shape):
    tool = "line"

    def __init__(self, x, y, color, width):
        super().__init__(color, width)
        self.x0 = self.x1 = float(x)
        self.y0 = self.y1 = float(y)

    @property
    def length(self):
        return math.hypot(self.x1 - self.x0, self.y1 - self.y0)

    def update(self, x, y, constrain=False):
        if constrain:
            x, y = snap_angle(self.x0, self.y0, x, y)
        self.x1, self.y1 = float(x), float(y)

    def translate(self, dx, dy):
        self.x0 += dx
        self.x1 += dx
        self.y0 += dy
        self.y1 += dy

    def is_valid(self):
        return self.length >= 3

    def bounds(self):
        pad = self.width / 2
        return (
            min(self.x0, self.x1) - pad,
            min(self.y0, self.y1) - pad,
            max(self.x0, self.x1) + pad,
            max(self.y0, self.y1) + pad,
        )

    def hit_test(self, x, y, tolerance):
        d = distance_to_segment(x, y, self.x0, self.y0, self.x1, self.y1)
        return d <= tolerance + self.width / 2

    def draw(self, cr, base):
        cr.save()
        self._use_color(cr)
        cr.set_line_width(self.width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(self.x0, self.y0)
        cr.line_to(self.x1, self.y1)
        cr.stroke()
        cr.restore()


class ArrowShape(LineShape):
    tool = "arrow"

    def head_geometry(self):
        """Return ``(head_length, head_width)`` clamped to the arrow length."""
        head_length = max(10.0, self.width * 4.5)
        head_length = min(head_length, self.length * 0.6)
        return head_length, head_length * 0.9

    def bounds(self):
        x0, y0, x1, y1 = super().bounds()
        _length, head_width = self.head_geometry()
        pad = head_width / 2
        return x0 - pad, y0 - pad, x1 + pad, y1 + pad

    def draw(self, cr, base):
        length = self.length
        if length == 0:
            return
        ux, uy = (self.x1 - self.x0) / length, (self.y1 - self.y0) / length
        head_length, head_width = self.head_geometry()
        base_x, base_y = self.x1 - ux * head_length, self.y1 - uy * head_length
        half = head_width / 2

        cr.save()
        self._use_color(cr)
        cr.set_line_width(self.width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        # Stop the shaft inside the head so the round cap never pokes through the tip.
        shaft_end = head_length * 0.5
        cr.move_to(self.x0, self.y0)
        cr.line_to(self.x1 - ux * shaft_end, self.y1 - uy * shaft_end)
        cr.stroke()

        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_width(max(1.0, self.width / 3))
        cr.move_to(self.x1, self.y1)
        cr.line_to(base_x - uy * half, base_y + ux * half)
        cr.line_to(base_x + uy * half, base_y - ux * half)
        cr.close_path()
        cr.fill_preserve()
        cr.stroke()
        cr.restore()


class PenShape(Shape):
    tool = "pen"
    min_step = 1.5

    def __init__(self, x, y, color, width):
        super().__init__(color, width)
        self.points: list[tuple[float, float]] = [(float(x), float(y))]

    def update(self, x, y, constrain=False):
        if constrain:
            self.points = [self.points[0], (float(x), float(y))]
            return
        last_x, last_y = self.points[-1]
        if math.hypot(x - last_x, y - last_y) >= self.min_step:
            self.points.append((float(x), float(y)))

    def translate(self, dx, dy):
        self.points = [(x + dx, y + dy) for x, y in self.points]

    @property
    def stroke_width(self):
        return self.width

    def bounds(self):
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        pad = self.stroke_width / 2
        return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad

    def hit_test(self, x, y, tolerance):
        reach = tolerance + self.stroke_width / 2
        if len(self.points) == 1:
            px, py = self.points[0]
            return math.hypot(x - px, y - py) <= reach
        return any(
            distance_to_segment(x, y, ax, ay, bx, by) <= reach
            for (ax, ay), (bx, by) in zip(self.points, self.points[1:])
        )

    def _trace(self, cr):
        points = self.points
        cr.move_to(*points[0])
        if len(points) == 1:
            cr.line_to(*points[0])
            return
        if len(points) == 2:
            cr.line_to(*points[1])
            return
        # Quadratic smoothing through segment midpoints, expressed as cubic curves.
        current = points[0]
        for i in range(1, len(points) - 1):
            control = points[i]
            mid = ((points[i][0] + points[i + 1][0]) / 2, (points[i][1] + points[i + 1][1]) / 2)
            c1 = (current[0] + 2 / 3 * (control[0] - current[0]), current[1] + 2 / 3 * (control[1] - current[1]))
            c2 = (mid[0] + 2 / 3 * (control[0] - mid[0]), mid[1] + 2 / 3 * (control[1] - mid[1]))
            cr.curve_to(*c1, *c2, *mid)
            current = mid
        cr.line_to(*points[-1])

    def draw(self, cr, base):
        cr.save()
        self._use_color(cr)
        cr.set_line_width(self.stroke_width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        self._trace(cr)
        cr.stroke()
        cr.restore()


class HighlighterShape(PenShape):
    tool = "highlighter"

    @property
    def stroke_width(self):
        return max(12.0, self.width * 4)

    def draw(self, cr, base):
        cr.save()
        self._use_color(cr, alpha=HIGHLIGHTER_ALPHA)
        cr.set_line_width(self.stroke_width)
        cr.set_line_cap(cairo.LINE_CAP_SQUARE)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        self._trace(cr)
        cr.stroke()
        cr.restore()


def font_size_for_width(width: float) -> float:
    return max(14.0, width * 6)


class TextShape(Shape):
    tool = "text"

    def __init__(self, x, y, text, color, width):
        super().__init__(color, width)
        self.x = float(x)
        self.y = float(y)
        self.text = text

    @property
    def font_size(self):
        return font_size_for_width(self.width)

    def _layout(self, cr):
        layout = PangoCairo.create_layout(cr)
        description = Pango.FontDescription.from_string(FONT_FAMILY)
        description.set_absolute_size(self.font_size * Pango.SCALE)
        layout.set_font_description(description)
        layout.set_text(self.text, -1)
        return layout

    def size(self):
        width, height = self._layout(_measure_context).get_pixel_size()
        return width, height

    def is_valid(self):
        return bool(self.text.strip())

    def translate(self, dx, dy):
        self.x += dx
        self.y += dy

    def bounds(self):
        width, height = self.size()
        pad = self.halo_width
        return self.x - pad, self.y - pad, self.x + width + pad, self.y + height + pad

    def hit_test(self, x, y, tolerance):
        x0, y0, x1, y1 = self.bounds()
        return x0 - tolerance <= x <= x1 + tolerance and y0 - tolerance <= y <= y1 + tolerance

    @property
    def halo_width(self):
        return max(2.0, self.font_size / 7)

    def draw(self, cr, base):
        if not self.text:
            return
        cr.save()
        cr.new_path()
        layout = self._layout(cr)
        cr.move_to(self.x, self.y)
        PangoCairo.layout_path(cr, layout)
        halo = contrast_color(self.color)
        cr.set_source_rgba(halo[0], halo[1], halo[2], 0.9)
        cr.set_line_width(self.halo_width)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.stroke_preserve()
        self._use_color(cr)
        cr.fill()
        cr.restore()


class CounterShape(Shape):
    """A numbered badge for marking steps (1, 2, 3, ...)."""

    tool = "counter"

    def __init__(self, x, y, number, color, width):
        super().__init__(color, width)
        self.x = float(x)
        self.y = float(y)
        self.number = int(number)

    @property
    def radius(self):
        return max(12.0, self.width * 4.5)

    def update(self, x, y, constrain=False):
        self.x, self.y = float(x), float(y)

    def translate(self, dx, dy):
        self.x += dx
        self.y += dy

    def bounds(self):
        r = self.radius + 2
        return self.x - r, self.y - r, self.x + r, self.y + r

    def hit_test(self, x, y, tolerance):
        return math.hypot(x - self.x, y - self.y) <= self.radius + tolerance

    def draw(self, cr, base):
        r = self.radius
        cr.save()
        cr.new_path()
        cr.arc(self.x, self.y, r, 0, 2 * math.pi)
        self._use_color(cr)
        cr.fill_preserve()
        foreground = contrast_color(self.color)
        cr.set_source_rgba(*foreground)
        cr.set_line_width(max(1.5, r / 9))
        cr.stroke()

        layout = PangoCairo.create_layout(cr)
        description = Pango.FontDescription.from_string(FONT_FAMILY)
        description.set_absolute_size(r * 1.15 * Pango.SCALE)
        layout.set_font_description(description)
        layout.set_text(str(self.number), -1)
        ink, _logical = layout.get_pixel_extents()
        cr.move_to(self.x - ink.x - ink.width / 2, self.y - ink.y - ink.height / 2)
        cr.set_source_rgba(*foreground)
        PangoCairo.show_layout(cr, layout)
        cr.new_path()
        cr.restore()


# Tools whose shapes are created by dragging from a start point.
DRAG_SHAPES = {
    cls.tool: cls
    for cls in (RectangleShape, EllipseShape, ArrowShape, LineShape, PenShape, HighlighterShape, PixelateShape)
}
