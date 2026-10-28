"""The drawing surface of the editor: shows the document and turns pointer input into shapes."""

from __future__ import annotations

import cairo
from gi.repository import Gdk, GLib, GObject, Gtk

from .document import Document
from .history import AddShape, ChangeStyle, EditText, History, MoveShape, RemoveShape, SetCrop
from .shapes import DRAG_SHAPES, RGBA, CounterShape, Shape, TextShape, font_size_for_width

MARGIN = 16
HIT_TOLERANCE = 6  # logical pixels
SELECTION_COLOR = (0.208, 0.518, 0.894)
MIN_CROP = 4

TOOL_CURSORS = {"select": "default", "text": "text"}


class Canvas(Gtk.DrawingArea):
    __gsignals__ = {
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, doc: Document, history: History):
        super().__init__(hexpand=True, vexpand=True, focusable=True)
        self.doc = doc
        self.history = history
        self.tool = "arrow"
        self.color: RGBA = (0.878, 0.106, 0.141, 1.0)
        self.width_level = 4.0
        self.selected: Shape | None = None

        self._active: Shape | None = None  # shape being created
        self._moving: list | None = None  # [shape, applied_dx, applied_dy]
        self._editing_text: TextShape | None = None
        self._crop_preview: tuple[float, float, float, float] | None = None
        self._cache: cairo.ImageSurface | None = None
        self._cache_exclude: Shape | None = None
        self._transform = (1.0, 0.0, 0.0)  # zoom, offset x, offset y

        self.set_draw_func(self._draw)
        self._update_cursor()

        drag = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        click = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

    # -- public API ---------------------------------------------------------
    @property
    def stroke_width(self) -> float:
        return self.width_level * self.doc.scale

    def set_tool(self, tool: str):
        self.tool = tool
        if tool != "select":
            self.select(None)
        self._update_cursor()

    def set_color(self, color: RGBA):
        self.color = color
        if self.selected is not None and self.selected.color != color:
            self.history.push(ChangeStyle(self.selected, color, self.selected.width))

    def set_width_level(self, level: float):
        self.width_level = level
        if self.selected is not None and self.selected.width != self.stroke_width:
            self.history.push(ChangeStyle(self.selected, self.selected.color, self.stroke_width))

    def select(self, shape: Shape | None):
        if shape is self.selected:
            return
        self.selected = shape
        self.queue_draw()
        self.emit("selection-changed")

    def delete_selected(self) -> bool:
        if self.selected is None or self.selected not in self.doc.shapes:
            return False
        shape = self.selected
        self.select(None)
        self.history.push(RemoveShape(shape))
        return True

    def document_changed(self):
        """Call after the history changed the document."""
        if self.selected is not None and self.selected not in self.doc.shapes:
            self.select(None)
        self.invalidate()

    def invalidate(self, exclude: Shape | None = None):
        self._cache = None
        self._cache_exclude = exclude
        self.queue_draw()

    # -- coordinates --------------------------------------------------------
    def _update_transform(self, width: int, height: int):
        _vx, _vy, vw, vh = self.doc.view_rect
        natural = 1 / self.doc.scale
        zoom = min(natural, (width - 2 * MARGIN) / vw, (height - 2 * MARGIN) / vh)
        zoom = max(zoom, 0.01)
        self._transform = (zoom, (width - vw * zoom) / 2, (height - vh * zoom) / 2)

    def to_image(self, x: float, y: float) -> tuple[float, float]:
        zoom, ox, oy = self._transform
        vx, vy, _vw, _vh = self.doc.view_rect
        return (x - ox) / zoom + vx, (y - oy) / zoom + vy

    def to_widget(self, x: float, y: float) -> tuple[float, float]:
        zoom, ox, oy = self._transform
        vx, vy, _vw, _vh = self.doc.view_rect
        return (x - vx) * zoom + ox, (y - vy) * zoom + oy

    @property
    def zoom(self) -> float:
        return self._transform[0]

    def _tolerance(self) -> float:
        return HIT_TOLERANCE / self.zoom

    # -- drawing ------------------------------------------------------------
    def _composite(self) -> cairo.ImageSurface:
        if self._cache is None:
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.doc.width, self.doc.height)
            self.doc.render(cairo.Context(surface), exclude=self._cache_exclude)
            surface.flush()
            self._cache = surface
        return self._cache

    def _draw(self, _area, cr, width, height):
        self._update_transform(width, height)
        zoom, ox, oy = self._transform
        vx, vy, vw, vh = self.doc.view_rect

        # Drop shadow behind the image.
        cr.rectangle(ox + 1, oy + 2, vw * zoom, vh * zoom)
        cr.set_source_rgba(0, 0, 0, 0.25)
        cr.fill()

        cr.save()
        cr.translate(ox, oy)
        cr.scale(zoom, zoom)
        cr.translate(-vx, -vy)
        cr.rectangle(vx, vy, vw, vh)
        cr.clip()

        cr.set_source_surface(self._composite(), 0, 0)
        cr.get_source().set_filter(cairo.FILTER_GOOD if zoom < 1 else cairo.FILTER_NEAREST)
        cr.paint()

        if self._cache_exclude is not None and self._cache_exclude in self.doc.shapes:
            self._cache_exclude.draw(cr, self.doc.base)
        if self._active is not None:
            self._active.draw(cr, self.doc.base)
        if self._crop_preview is not None:
            self._draw_crop_preview(cr)
        if self.selected is not None and self.selected in self.doc.shapes:
            self._draw_selection(cr, self.selected)
        cr.restore()

    def _draw_selection(self, cr, shape):
        x0, y0, x1, y1 = shape.bounds()
        pad = 4 / self.zoom
        cr.rectangle(x0 - pad, y0 - pad, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad)
        cr.set_line_width(1.5 / self.zoom)
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.stroke_preserve()
        cr.set_dash([4 / self.zoom, 4 / self.zoom])
        cr.set_source_rgb(*SELECTION_COLOR)
        cr.stroke()
        cr.set_dash([])

    def _draw_crop_preview(self, cr):
        vx, vy, vw, vh = self.doc.view_rect
        x, y, w, h = self._crop_preview
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(vx, vy, vw, vh)
        cr.rectangle(x, y, w, h)
        cr.set_source_rgba(0, 0, 0, 0.5)
        cr.fill()
        cr.set_fill_rule(cairo.FILL_RULE_WINDING)
        cr.rectangle(x, y, w, h)
        cr.set_line_width(1.5 / self.zoom)
        cr.set_source_rgb(1, 1, 1)
        cr.set_dash([6 / self.zoom, 4 / self.zoom])
        cr.stroke()
        cr.set_dash([])

    # -- input --------------------------------------------------------------
    def _update_cursor(self, name: str | None = None):
        self.set_cursor_from_name(name or TOOL_CURSORS.get(self.tool, "crosshair"))

    def _on_motion(self, _controller, x, y):
        if self.tool != "select" or self._moving is not None:
            return
        ix, iy = self.to_image(x, y)
        hovering = self.doc.topmost_at(ix, iy, self._tolerance()) is not None
        self._update_cursor("move" if hovering else None)

    def _on_click(self, gesture, n_press, x, y):
        if n_press != 2 or self.tool != "select":
            return
        ix, iy = self.to_image(x, y)
        shape = self.doc.topmost_at(ix, iy, self._tolerance())
        if isinstance(shape, TextShape):
            self._open_text_popover(x, y, shape)

    def _on_drag_begin(self, gesture, x, y):
        self.grab_focus()
        ix, iy = self.to_image(x, y)
        tool = self.tool
        if tool == "select":
            shape = self.doc.topmost_at(ix, iy, self._tolerance())
            self.select(shape)
            if shape is not None:
                self._moving = [shape, 0.0, 0.0]
                self.invalidate(exclude=shape)
        elif tool == "text":
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            existing = self.doc.topmost_at(ix, iy, self._tolerance())
            if isinstance(existing, TextShape):
                self._open_text_popover(x, y, existing)
            else:
                self._open_text_popover(x, y)
        elif tool == "counter":
            self._active = CounterShape(ix, iy, self.doc.next_counter_number(), self.color, self.stroke_width)
        elif tool == "crop":
            self._crop_preview = (ix, iy, 0, 0)
        elif tool in DRAG_SHAPES:
            self._active = DRAG_SHAPES[tool](ix, iy, self.color, self.stroke_width)
        self.queue_draw()

    def _on_drag_update(self, gesture, dx, dy):
        ok, sx, sy = gesture.get_start_point()
        if not ok or self.tool == "text":
            return
        constrain = bool(gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK)
        ix, iy = self.to_image(sx + dx, sy + dy)
        if self._moving is not None:
            shape, applied_x, applied_y = self._moving
            total_x, total_y = dx / self.zoom, dy / self.zoom
            shape.translate(total_x - applied_x, total_y - applied_y)
            self._moving = [shape, total_x, total_y]
        elif self._active is not None:
            self._active.update(ix, iy, constrain)
        elif self._crop_preview is not None:
            x0, y0 = self.to_image(sx, sy)
            self._crop_preview = (min(x0, ix), min(y0, iy), abs(ix - x0), abs(iy - y0))
        self.queue_draw()

    def _on_drag_end(self, _gesture, _dx, _dy):
        if self.tool == "text":
            return  # The text popover owns the preview shape.
        if self._moving is not None:
            shape, total_x, total_y = self._moving
            self._moving = None
            if total_x or total_y:
                self.history.push(MoveShape(shape, total_x, total_y), applied=True)
            self.invalidate()
        elif self._active is not None:
            shape, self._active = self._active, None
            if shape.is_valid():
                self.history.push(AddShape(shape))
        elif self._crop_preview is not None:
            preview, self._crop_preview = self._crop_preview, None
            rect = self.doc.clamp_rect(*preview)
            if rect is not None and rect[2] >= MIN_CROP and rect[3] >= MIN_CROP and rect != self.doc.view_rect:
                self.history.push(SetCrop(rect))
        self.queue_draw()

    # -- text ---------------------------------------------------------------
    def _open_text_popover(self, x: float, y: float, shape: TextShape | None = None):
        if self._editing_text is not None:
            return
        ix, iy = self.to_image(x, y)
        if shape is None:
            size = font_size_for_width(self.stroke_width)
            preview = TextShape(ix, iy - size * 0.6, "", self.color, self.stroke_width)
            self._active = preview
            original = ""
        else:
            preview = shape
            original = shape.text
            self._editing_text = shape
            self.select(shape)
            self.invalidate(exclude=shape)

        popover = Gtk.Popover(has_arrow=True, position=Gtk.PositionType.BOTTOM)
        popover.set_parent(self)
        anchor = Gdk.Rectangle()
        anchor.x, anchor.y, anchor.width, anchor.height = int(x), int(y), 1, 1
        popover.set_pointing_to(anchor)

        entry = Gtk.Entry(text=original, width_chars=28, placeholder_text="Type, then press Enter")
        popover.set_child(entry)
        state = {"cancelled": False}

        def on_changed(_entry):
            preview.text = entry.get_text()
            self.queue_draw()

        def on_key(_controller, keyval, _keycode, _state):
            if keyval == Gdk.KEY_Escape:
                state["cancelled"] = True
                popover.popdown()
                return True
            return False

        def on_closed(_popover):
            text = entry.get_text()
            if shape is None:
                self._active = None
                if not state["cancelled"] and text.strip():
                    preview.text = text
                    self.history.push(AddShape(preview))
            else:
                shape.text = original
                self._editing_text = None
                if not state["cancelled"] and text != original:
                    if text.strip():
                        self.history.push(EditText(shape, text))
                    else:
                        self.select(None)
                        self.history.push(RemoveShape(shape))
                self.invalidate()
            self.queue_draw()
            GLib.idle_add(popover.unparent)
            self.grab_focus()

        entry.connect("changed", on_changed)
        entry.connect("activate", lambda _e: popover.popdown())
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", on_key)
        entry.add_controller(keys)
        popover.connect("closed", on_closed)
        popover.popup()
        entry.grab_focus()
