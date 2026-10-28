import datetime
import os
import stat
import tempfile
import unittest

import cairo

from screencatch import export

from .helpers import pixel, solid_surface

WHEN = datetime.datetime(2026, 10, 28, 9, 5, 7)


class TemplateTests(unittest.TestCase):
    def test_default_template(self):
        self.assertEqual(export.expand_template(export.DEFAULT_TEMPLATE, WHEN), "Screenshot_2026-10-28_09-05-07.png")

    def test_png_suffix_not_duplicated(self):
        self.assertEqual(export.expand_template("shot.PNG", WHEN), "shot.PNG")

    def test_slashes_and_hidden_names_are_sanitized(self):
        self.assertEqual(export.expand_template("a/b", WHEN), "a-b.png")
        self.assertEqual(export.expand_template("..hidden", WHEN), "hidden.png")

    def test_empty_template_falls_back(self):
        self.assertEqual(export.expand_template("   ", WHEN), "Screenshot_2026-10-28_09-05-07.png")
        self.assertEqual(export.expand_template("", WHEN), "Screenshot_2026-10-28_09-05-07.png")


class SavingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_unique_path(self):
        first = export.unique_path(self.tmp.name, "a.png")
        open(first, "wb").close()
        second = export.unique_path(self.tmp.name, "a.png")
        self.assertEqual(os.path.basename(second), "a-1.png")

    def test_save_to_folder_creates_directory_and_png(self):
        target = os.path.join(self.tmp.name, "nested", "dir")
        path = export.save_to_folder(solid_surface(8, 6, (0, 0, 1)), target, "shot")
        self.assertTrue(path.endswith("shot.png"))
        loaded = cairo.ImageSurface.create_from_png(path)
        self.assertEqual((loaded.get_width(), loaded.get_height()), (8, 6))
        self.assertEqual(os.listdir(target), ["shot.png"])  # no temp files left behind
        mode = stat.S_IMODE(os.stat(path).st_mode)
        self.assertTrue(mode & stat.S_IRUSR and not mode & stat.S_IXUSR)

    def test_second_save_does_not_overwrite(self):
        a = export.save_to_folder(solid_surface(2, 2), self.tmp.name, "same")
        b = export.save_to_folder(solid_surface(2, 2), self.tmp.name, "same")
        self.assertNotEqual(a, b)

    def test_resolve_save_dir(self):
        self.assertEqual(export.resolve_save_dir("~/x"), os.path.expanduser("~/x"))
        self.assertTrue(export.resolve_save_dir("").endswith("Screenshots"))


class SurfaceTests(unittest.TestCase):
    def test_png_bytes(self):
        data = export.surface_to_png_bytes(solid_surface(3, 3))
        self.assertTrue(data.startswith(b"\x89PNG"))

    def test_crop_surface(self):
        source = solid_surface(10, 10, (1, 0, 0))
        cr = cairo.Context(source)
        cr.set_source_rgb(0, 0, 1)
        cr.rectangle(5, 5, 5, 5)
        cr.fill()
        cropped = export.crop_surface(source, 5, 5, 3, 2)
        self.assertEqual((cropped.get_width(), cropped.get_height()), (3, 2))
        self.assertEqual(pixel(cropped, 0, 0)[:3], (0, 0, 255))


if __name__ == "__main__":
    unittest.main()
