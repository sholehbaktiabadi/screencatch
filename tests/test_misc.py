import unittest

from screencatch import shortcut
from screencatch.overlay import image_rect_for_selection


class ShortcutPathTests(unittest.TestCase):
    def test_with_path_is_idempotent(self):
        paths = ["/custom0/"]
        once = shortcut.with_path(paths)
        self.assertEqual(once, ["/custom0/", shortcut.KEYBINDING_PATH])
        self.assertEqual(shortcut.with_path(once), once)

    def test_without_path_keeps_others(self):
        paths = ["/a/", shortcut.KEYBINDING_PATH, "/b/"]
        self.assertEqual(shortcut.without_path(paths), ["/a/", "/b/"])


class SelectionMappingTests(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(image_rect_for_selection((10, 20, 30, 40), (0, 0), 1.0, (100, 100)), (10, 20, 30, 40))

    def test_hidpi_scale(self):
        self.assertEqual(image_rect_for_selection((10, 10, 5, 5), (0, 0), 2.0, (400, 400)), (20, 20, 10, 10))

    def test_fractional_scale_rounds_edges(self):
        self.assertEqual(image_rect_for_selection((1, 1, 3, 3), (0, 0), 1.25, (100, 100)), (1, 1, 4, 4))

    def test_offset_origin_and_clamping(self):
        # Desktop starting at x=-100 (monitor left of the primary one).
        self.assertEqual(image_rect_for_selection((-100, 0, 50, 50), (-100, 0), 1.0, (300, 100)), (0, 0, 50, 50))
        self.assertEqual(image_rect_for_selection((150, 50, 100, 100), (-100, 0), 1.0, (300, 100)), (250, 50, 50, 50))


if __name__ == "__main__":
    unittest.main()
