"""The annotated image: the captured screenshot, its shapes and an optional crop."""

from __future__ import annotations

import cairo

from .shapes import CounterShape, Shape

Rect = tuple[int, int, int, int]


class Document:
    def __init__(self, base: cairo.ImageSurface, scale: float = 1.0):
        self.base = base
        # Image pixels per logical screen pixel; annotation sizes are multiplied by it
        # so strokes look the same on HiDPI captures.
        self.scale = scale if scale > 0 else 1.0
        self.shapes: list[Shape] = []
        self.crop: Rect | None = None

    @property
    def width(self) -> int:
        return self.base.get_width()

    @property
    def height(self) -> int:
        return self.base.get_height()

    @property
    def view_rect(self) -> Rect:
        """The visible part of the image, ``(x, y, w, h)``."""
        return self.crop if self.crop else (0, 0, self.width, self.height)

    def clamp_rect(self, x: float, y: float, w: float, h: float) -> Rect | None:
        """Round a rectangle to whole pixels and clip it to the current view."""
        vx, vy, vw, vh = self.view_rect
        x0 = max(vx, round(x))
        y0 = max(vy, round(y))
        x1 = min(vx + vw, round(x + w))
        y1 = min(vy + vh, round(y + h))
        if x1 - x0 < 1 or y1 - y0 < 1:
            return None
        return x0, y0, x1 - x0, y1 - y0

    def topmost_at(self, x: float, y: float, tolerance: float) -> Shape | None:
        for shape in reversed(self.shapes):
            if shape.hit_test(x, y, tolerance):
                return shape
        return None

    def next_counter_number(self) -> int:
        numbers = [s.number for s in self.shapes if isinstance(s, CounterShape)]
        return max(numbers, default=0) + 1

    def render(self, cr: cairo.Context, exclude: Shape | None = None) -> None:
        """Paint the base image and every shape in image coordinates."""
        cr.save()
        cr.set_source_surface(self.base, 0, 0)
        cr.paint()
        cr.restore()
        for shape in self.shapes:
            if shape is not exclude:
                shape.draw(cr, self.base)

    def export(self) -> cairo.ImageSurface:
        """Render the visible area at full resolution into a new ARGB32 surface."""
        x, y, w, h = self.view_rect
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        cr.translate(-x, -y)
        self.render(cr)
        surface.flush()
        return surface
