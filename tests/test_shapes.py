import math
import unittest

from screencatch.editor import shapes
from screencatch.editor.shapes import (
    ArrowShape,
    CounterShape,
    EllipseShape,
    HighlighterShape,
    LineShape,
    PenShape,
    PixelateShape,
    RectangleShape,
    TextShape,
)

from .helpers import checker_surface, pixel, solid_surface

RED = (1.0, 0.0, 0.0, 1.0)


def render(shape, width=100, height=100, base=None):
    import cairo

    base = base or solid_surface(width, height)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    cr.set_source_surface(base, 0, 0)
    cr.paint()
    shape.draw(cr, base)
    surface.flush()
    return surface


class ColorTests(unittest.TestCase):
    def test_parse_and_format_round_trip(self):
        self.assertEqual(shapes.parse_color("#ff0000"), (1.0, 0.0, 0.0, 1.0))
        self.assertEqual(shapes.color_to_hex(shapes.parse_color("#3584e4")), "#3584e4")
        self.assertEqual(shapes.color_to_hex((0, 0, 0, 0.5)), "#00000080")

    def test_parse_rejects_garbage(self):
        for value in ("", "#12", "red", "#zzzzzz"):
            with self.assertRaises(ValueError):
                shapes.parse_color(value)

    def test_contrast_color(self):
        self.assertEqual(shapes.contrast_color((1, 1, 1, 1)), (0, 0, 0, 1))
        self.assertEqual(shapes.contrast_color((0.1, 0.1, 0.4, 1)), (1, 1, 1, 1))


class GeometryTests(unittest.TestCase):
    def test_distance_to_segment(self):
        self.assertAlmostEqual(shapes.distance_to_segment(5, 5, 0, 0, 10, 0), 5)
        self.assertAlmostEqual(shapes.distance_to_segment(-3, 4, 0, 0, 10, 0), 5)
        self.assertAlmostEqual(shapes.distance_to_segment(1, 1, 0, 0, 0, 0), math.sqrt(2))

    def test_snap_angle(self):
        x, y = shapes.snap_angle(0, 0, 10, 1)
        self.assertAlmostEqual(y, 0, places=6)
        x, y = shapes.snap_angle(0, 0, 10, 9)
        self.assertAlmostEqual(x, y, places=6)

    def test_snap_square(self):
        self.assertEqual(shapes.snap_square(0, 0, 10, -4), (10, -10))
        self.assertEqual(shapes.snap_square(5, 5, 1, 2), (1, 1))


class ShapeBehaviourTests(unittest.TestCase):
    def test_rectangle_hits_border_not_center(self):
        rect = RectangleShape(10, 10, RED, 4)
        rect.update(90, 90)
        self.assertTrue(rect.hit_test(10, 50, 2))
        self.assertTrue(rect.hit_test(89, 89, 2))
        self.assertFalse(rect.hit_test(50, 50, 2))
        self.assertFalse(rect.hit_test(0, 50, 2))

    def test_rectangle_constrain_makes_square(self):
        rect = RectangleShape(0, 0, RED, 2)
        rect.update(30, 10, constrain=True)
        _x, _y, w, h = rect.rect
        self.assertEqual(w, h)

    def test_ellipse_hit_on_outline(self):
        ellipse = EllipseShape(0, 0, RED, 2)
        ellipse.update(100, 50)
        self.assertTrue(ellipse.hit_test(0, 25, 3))
        self.assertTrue(ellipse.hit_test(50, 0, 3))
        self.assertFalse(ellipse.hit_test(50, 25, 3))

    def test_degenerate_shapes_are_invalid(self):
        for cls in (RectangleShape, EllipseShape, LineShape, ArrowShape, PixelateShape):
            shape = cls(5, 5, RED, 2)
            shape.update(6, 6)
            self.assertFalse(shape.is_valid(), cls.__name__)

    def test_translate_moves_bounds(self):
        for shape in (
            RectangleShape(0, 0, RED, 2),
            ArrowShape(0, 0, RED, 2),
            PenShape(0, 0, RED, 2),
            CounterShape(0, 0, 1, RED, 2),
            TextShape(0, 0, "Hi", RED, 2),
        ):
            shape.update(20, 20)
            before = shape.bounds()
            shape.translate(5, 7)
            after = shape.bounds()
            self.assertAlmostEqual(after[0] - before[0], 5, msg=type(shape).__name__)
            self.assertAlmostEqual(after[1] - before[1], 7, msg=type(shape).__name__)

    def test_pen_skips_tiny_moves_and_hits_path(self):
        pen = PenShape(0, 0, RED, 4)
        pen.update(0.5, 0.5)
        self.assertEqual(len(pen.points), 1)
        pen.update(10, 0)
        pen.update(20, 0)
        self.assertEqual(len(pen.points), 3)
        self.assertTrue(pen.hit_test(15, 1, 1))
        self.assertFalse(pen.hit_test(15, 20, 1))

    def test_highlighter_shift_draws_straight_line(self):
        marker = HighlighterShape(0, 0, RED, 4)
        for x in range(1, 50, 3):
            marker.update(x, x % 7)
        marker.update(50, 0, constrain=True)
        self.assertEqual(marker.points, [(0.0, 0.0), (50.0, 0.0)])

    def test_text_validity_and_hit(self):
        text = TextShape(10, 10, "  ", RED, 4)
        self.assertFalse(text.is_valid())
        text.text = "Hello"
        self.assertTrue(text.is_valid())
        width, height = text.size()
        self.assertGreater(width, 0)
        self.assertTrue(text.hit_test(10 + width / 2, 10 + height / 2, 0))

    def test_style_round_trip(self):
        arrow = ArrowShape(0, 0, RED, 2)
        arrow.set_style((0, 0, 1, 1), 8)
        self.assertEqual(arrow.get_style(), ((0, 0, 1, 1), 8.0))


class RenderingTests(unittest.TestCase):
    def test_rectangle_paints_border_only(self):
        rect = RectangleShape(10, 10, RED, 4)
        rect.update(90, 90)
        surface = render(rect)
        self.assertEqual(pixel(surface, 10, 50)[:3], (255, 0, 0))
        self.assertEqual(pixel(surface, 50, 50)[:3], (255, 255, 255))

    def test_arrow_paints_tip_and_tail(self):
        arrow = ArrowShape(10, 50, RED, 4)
        arrow.update(90, 50)
        surface = render(arrow)
        self.assertEqual(pixel(surface, 12, 50)[:3], (255, 0, 0))
        self.assertEqual(pixel(surface, 85, 50)[:3], (255, 0, 0))
        self.assertEqual(pixel(surface, 50, 10)[:3], (255, 255, 255))

    def test_counter_paints_disc(self):
        counter = CounterShape(50, 50, 3, RED, 4)
        surface = render(counter)
        r, g, b, _a = pixel(surface, 50 - int(counter.radius) + 4, 50)
        self.assertGreater(r, 200)
        self.assertLess(g, 60)

    def test_consecutive_shapes_do_not_connect(self):
        import cairo

        base = solid_surface(200, 60)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 60)
        cr = cairo.Context(surface)
        cr.set_source_surface(base, 0, 0)
        cr.paint()
        for shape in (CounterShape(20, 30, 1, RED, 2), CounterShape(180, 30, 2, RED, 2), EllipseShape(0, 0, RED, 2)):
            if isinstance(shape, EllipseShape):
                shape.update(10, 10)
            shape.draw(cr, base)
        surface.flush()
        # Nothing may be painted between the two badges.
        self.assertEqual(pixel(surface, 100, 30)[:3], (255, 255, 255))

    def test_highlighter_is_translucent(self):
        marker = HighlighterShape(10, 50, RED, 4)
        marker.update(90, 50)
        r, g, b, _a = pixel(render(marker), 50, 50)
        self.assertEqual(r, 255)
        self.assertTrue(100 < g < 255)

    def test_pixelate_averages_blocks(self):
        base = checker_surface(60, 60, cell=1)
        mosaic = PixelateShape(0, 0, RED, 4)
        mosaic.update(60, 60)
        surface = render(mosaic, 60, 60, base=base)
        r, _g, _b, _a = pixel(surface, 30, 30)
        # A 1px checkerboard averages to mid grey instead of pure black/white.
        self.assertTrue(60 < r < 200, r)
        # Pixels inside one block share a value.
        self.assertEqual(pixel(surface, 0, 0), pixel(surface, 1, 1))

    def test_pixelate_outside_image_is_safe(self):
        base = solid_surface(20, 20)
        mosaic = PixelateShape(-50, -50, RED, 4)
        mosaic.update(-10, -10)
        render(mosaic, 20, 20, base=base)  # must not raise


if __name__ == "__main__":
    unittest.main()
