import unittest

from screencatch.editor.document import Document
from screencatch.editor.history import AddShape, ChangeStyle, EditText, History, MoveShape, RemoveShape, SetCrop
from screencatch.editor.shapes import CounterShape, RectangleShape, TextShape

from .helpers import solid_surface

RED = (1.0, 0.0, 0.0, 1.0)


def make_rect(x0=10, y0=10, x1=40, y1=40):
    rect = RectangleShape(x0, y0, RED, 2)
    rect.update(x1, y1)
    return rect


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.doc = Document(solid_surface(100, 80))
        self.changes = 0
        self.history = History(self.doc, self._changed)

    def _changed(self):
        self.changes += 1

    def test_add_undo_redo(self):
        rect = make_rect()
        self.history.push(AddShape(rect))
        self.assertEqual(self.doc.shapes, [rect])
        self.assertTrue(self.history.can_undo)
        self.history.undo()
        self.assertEqual(self.doc.shapes, [])
        self.assertTrue(self.history.can_redo)
        self.history.redo()
        self.assertEqual(self.doc.shapes, [rect])
        self.assertEqual(self.changes, 3)

    def test_new_command_clears_redo(self):
        self.history.push(AddShape(make_rect()))
        self.history.undo()
        self.history.push(AddShape(make_rect()))
        self.assertFalse(self.history.can_redo)

    def test_undo_on_empty_is_noop(self):
        self.assertIsNone(self.history.undo())
        self.assertIsNone(self.history.redo())
        self.assertEqual(self.changes, 0)

    def test_remove_restores_original_position(self):
        a, b, c = make_rect(), make_rect(), make_rect()
        for shape in (a, b, c):
            self.history.push(AddShape(shape))
        self.history.push(RemoveShape(b))
        self.assertEqual(self.doc.shapes, [a, c])
        self.history.undo()
        self.assertEqual(self.doc.shapes, [a, b, c])

    def test_move_applied_live(self):
        rect = make_rect()
        self.history.push(AddShape(rect))
        rect.translate(5, 5)  # done interactively by the canvas
        self.history.push(MoveShape(rect, 5, 5), applied=True)
        self.assertEqual(rect.rect[:2], (15, 15))
        self.history.undo()
        self.assertEqual(rect.rect[:2], (10, 10))

    def test_change_style_and_text(self):
        text = TextShape(0, 0, "old", RED, 2)
        self.history.push(AddShape(text))
        self.history.push(ChangeStyle(text, (0, 0, 1, 1), 8))
        self.history.push(EditText(text, "new"))
        self.assertEqual((text.text, text.color, text.width), ("new", (0, 0, 1, 1), 8))
        self.history.undo()
        self.history.undo()
        self.assertEqual((text.text, text.color, text.width), ("old", RED, 2))

    def test_crop(self):
        self.history.push(SetCrop((10, 10, 20, 20)))
        self.assertEqual(self.doc.view_rect, (10, 10, 20, 20))
        self.history.undo()
        self.assertEqual(self.doc.view_rect, (0, 0, 100, 80))

    def test_version_tracks_changes(self):
        start = self.history.version
        self.history.push(AddShape(make_rect()))
        self.history.undo()
        self.assertEqual(self.history.version, start + 2)


class DocumentTests(unittest.TestCase):
    def test_topmost_and_counter_numbering(self):
        doc = Document(solid_surface(100, 100))
        lower, upper = make_rect(0, 0, 50, 50), make_rect(0, 0, 50, 50)
        doc.shapes += [lower, upper]
        self.assertIs(doc.topmost_at(0, 25, 2), upper)
        self.assertIsNone(doc.topmost_at(25, 25, 2))
        self.assertEqual(doc.next_counter_number(), 1)
        doc.shapes.append(CounterShape(5, 5, 4, RED, 2))
        self.assertEqual(doc.next_counter_number(), 5)

    def test_clamp_rect_to_view(self):
        doc = Document(solid_surface(100, 100))
        self.assertEqual(doc.clamp_rect(-10, -10, 50.4, 50.4), (0, 0, 40, 40))
        self.assertIsNone(doc.clamp_rect(200, 200, 5, 5))
        doc.crop = (10, 10, 30, 30)
        self.assertEqual(doc.clamp_rect(0, 0, 100, 100), (10, 10, 30, 30))

    def test_export_respects_crop_and_shapes(self):
        doc = Document(solid_surface(100, 100))
        doc.shapes.append(make_rect(0, 0, 100, 100))
        doc.crop = (20, 30, 40, 10)
        out = doc.export()
        self.assertEqual((out.get_width(), out.get_height()), (40, 10))

    def test_invalid_scale_falls_back(self):
        self.assertEqual(Document(solid_surface(4, 4), scale=0).scale, 1.0)


if __name__ == "__main__":
    unittest.main()
