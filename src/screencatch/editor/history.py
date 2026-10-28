"""Undo/redo built on small reversible commands."""

from __future__ import annotations

from collections.abc import Callable

from .document import Document, Rect
from .shapes import RGBA, Shape, TextShape


class Command:
    def do(self, doc: Document) -> None:
        raise NotImplementedError

    def undo(self, doc: Document) -> None:
        raise NotImplementedError


class AddShape(Command):
    def __init__(self, shape: Shape):
        self.shape = shape

    def do(self, doc):
        doc.shapes.append(self.shape)

    def undo(self, doc):
        doc.shapes.remove(self.shape)


class RemoveShape(Command):
    def __init__(self, shape: Shape):
        self.shape = shape
        self.index = -1

    def do(self, doc):
        self.index = doc.shapes.index(self.shape)
        del doc.shapes[self.index]

    def undo(self, doc):
        doc.shapes.insert(self.index, self.shape)


class MoveShape(Command):
    def __init__(self, shape: Shape, dx: float, dy: float):
        self.shape = shape
        self.dx = dx
        self.dy = dy

    def do(self, doc):
        self.shape.translate(self.dx, self.dy)

    def undo(self, doc):
        self.shape.translate(-self.dx, -self.dy)


class ChangeStyle(Command):
    def __init__(self, shape: Shape, color: RGBA, width: float):
        self.shape = shape
        self.new = (color, width)
        self.old = shape.get_style()

    def do(self, doc):
        self.shape.set_style(*self.new)

    def undo(self, doc):
        self.shape.set_style(*self.old)


class EditText(Command):
    def __init__(self, shape: TextShape, text: str):
        self.shape = shape
        self.new = text
        self.old = shape.text

    def do(self, doc):
        self.shape.text = self.new

    def undo(self, doc):
        self.shape.text = self.old


class SetCrop(Command):
    def __init__(self, crop: Rect | None):
        self.new = crop
        self.old: Rect | None = None

    def do(self, doc):
        self.old = doc.crop
        doc.crop = self.new

    def undo(self, doc):
        doc.crop = self.old


class History:
    def __init__(self, doc: Document, on_change: Callable[[], None] | None = None):
        self.doc = doc
        self.on_change = on_change
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        # Increases on every change; lets callers detect unsaved edits.
        self.version = 0

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def push(self, command: Command, applied: bool = False) -> None:
        """Record ``command``; run it first unless it was already applied live."""
        if not applied:
            command.do(self.doc)
        self._undo.append(command)
        self._redo.clear()
        self._changed()

    def undo(self) -> Command | None:
        if not self._undo:
            return None
        command = self._undo.pop()
        command.undo(self.doc)
        self._redo.append(command)
        self._changed()
        return command

    def redo(self) -> Command | None:
        if not self._redo:
            return None
        command = self._redo.pop()
        command.do(self.doc)
        self._undo.append(command)
        self._changed()
        return command

    def _changed(self):
        self.version += 1
        if self.on_change:
            self.on_change()
