"""Full-screen region selection over a frozen screenshot.

One undecorated full-screen window is opened per monitor. Each shows its slice of
the captured desktop; the selection is kept in global logical coordinates so it
can be drawn consistently on every monitor.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import cairo
from gi.repository import Gdk, Gtk, PangoCairo

from .export import crop_surface

HANDLE_SIZE = 8
HANDLE_REACH = 12
MIN_SELECTION = 3
DIM_ALPHA = 0.45
ACCENT = (0.208, 0.518, 0.894)  # GNOME blue

ACTION_EDIT = "edit"
ACTION_COPY = "copy"
ACTION_SAVE = "save"

_HANDLE_CURSORS = {
    "nw": "nw-resize",
    "n": "n-resize",
    "ne": "ne-resize",
    "e": "e-resize",
    "se": "se-resize",
    "s": "s-resize",
    "sw": "sw-resize",
    "w": "w-resize",
}

Rect = tuple[float, float, float, float]


def _monitor_rects(display: Gdk.Display) -> list[tuple[Gdk.Monitor, Rect]]:
    monitors = display.get_monitors()
    result = []
    for index in range(monitors.get_n_items()):
        monitor = monitors.get_item(index)
        g = monitor.get_geometry()
        result.append((monitor, (g.x, g.y, g.width, g.height)))
    return result


def _union(rects: list[Rect]) -> Rect:
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return x0, y0, x1 - x0, y1 - y0


def image_rect_for_selection(selection: Rect, origin: tuple[float, float], ratio: float, size: tuple[int, int]):
    """Convert a global logical selection to whole image pixels, clamped to the image."""
    x, y, w, h = selection
    ox, oy = origin
    width, height = size
    x0 = max(0, min(width, math.floor((x - ox) * ratio + 0.5)))
    y0 = max(0, min(height, math.floor((y - oy) * ratio + 0.5)))
    x1 = max(0, min(width, math.floor((x + w - ox) * ratio + 0.5)))
    y1 = max(0, min(height, math.floor((y + h - oy) * ratio + 0.5)))
    return x0, y0, x1 - x0, y1 - y0


class OverlaySession:
    """Owns the overlay windows and the shared selection state."""

    def __init__(
        self,
        app: Gtk.Application,
        image: cairo.ImageSurface,
        default_action: str,
        on_done: Callable[[str | None, cairo.ImageSurface | None, float], None],
    ):
        self.app = app
        self.image = image
        self.default_action = default_action
        self.on_done = on_done
        self.selection: Rect | None = None
        self._finished = False

        display = Gdk.Display.get_default()
        monitors = _monitor_rects(display)
        self.union = _union([rect for _m, rect in monitors])
        ux, uy, uw, uh = self.union
        # Image pixels per logical pixel. The portal captures the whole desktop at
        # device resolution, so this is the (possibly fractional) scale factor.
        self.ratio = image.get_width() / uw if uw else 1.0
        self.windows = [OverlayWindow(self, monitor, rect) for monitor, rect in monitors]

    @property
    def origin(self):
        return self.union[0], self.union[1]

    def present(self):
        for window in self.windows:
            window.present()

    def set_selection(self, rect: Rect | None):
        if rect is not None:
            x, y, w, h = rect
            ux, uy, uw, uh = self.union
            x0, y0 = max(ux, x), max(uy, y)
            x1, y1 = min(ux + uw, x + w), min(uy + uh, y + h)
            rect = (x0, y0, max(0, x1 - x0), max(0, y1 - y0))
        self.selection = rect
        for window in self.windows:
            window.queue_draw_all()

    def has_selection(self) -> bool:
        return self.selection is not None and self.selection[2] >= MIN_SELECTION and self.selection[3] >= MIN_SELECTION

    def selection_size_px(self) -> tuple[int, int]:
        _x, _y, w, h = image_rect_for_selection(
            self.selection, self.origin, self.ratio, (self.image.get_width(), self.image.get_height())
        )
        return w, h

    def finish(self, action: str | None):
        if self._finished:
            return
        if action is not None and not self.has_selection():
            return
        self._finished = True
        surface = None
        if action is not None:
            x, y, w, h = image_rect_for_selection(
                self.selection, self.origin, self.ratio, (self.image.get_width(), self.image.get_height())
            )
            if w > 0 and h > 0:
                surface = crop_surface(self.image, x, y, w, h)
            else:
                action = None
        # Run the action while the overlay is still mapped and focused: Wayland only lets a
        # focused client take the clipboard, and hiding a window gives up its focus.
        windows, self.windows = self.windows, []
        try:
            self.on_done(action, surface, self.ratio)
        finally:
            for window in windows:
                window.destroy()


class OverlayWindow(Gtk.Window):
    def __init__(self, session: OverlaySession, monitor: Gdk.Monitor, rect: Rect):
        super().__init__(application=session.app, decorated=False, title="ScreenCatch selection")
        self.session = session
        self.monitor_rect = rect
        self.add_css_class("screencatch-overlay")
        self._drag_mode: str | None = None
        self._drag_origin: Rect | None = None
        self._pointer: tuple[float, float] | None = None

        self.area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.area.set_draw_func(self._draw)
        self.area.set_cursor_from_name("crosshair")

        self.actions_bar = self._build_actions_bar()
        overlay = Gtk.Overlay(child=self.area)
        overlay.add_overlay(self.actions_bar)
        self.set_child(overlay)

        drag = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.area.add_controller(drag)

        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self._on_click)
        self.area.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.area.add_controller(motion)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        self.fullscreen_on_monitor(monitor)

    # -- widgets ------------------------------------------------------------
    def _build_actions_bar(self):
        box = Gtk.Box(spacing=4, halign=Gtk.Align.START, valign=Gtk.Align.START, visible=False)
        box.add_css_class("osd")
        box.add_css_class("toolbar")
        box.add_css_class("screencatch-actions")
        for icon, label, tooltip, action in (
            ("screencatch-pen-symbolic", "Edit", "Annotate (Enter)", ACTION_EDIT),
            ("edit-copy-symbolic", "Copy", "Copy to clipboard (Ctrl+C)", ACTION_COPY),
            ("document-save-symbolic", "Save", "Save to folder (Ctrl+S)", ACTION_SAVE),
        ):
            button = Gtk.Button(tooltip_text=tooltip)
            content = Gtk.Box(spacing=6)
            content.append(Gtk.Image.new_from_icon_name(icon))
            content.append(Gtk.Label(label=label))
            button.set_child(content)
            button.connect("clicked", lambda _b, a=action: self.session.finish(a))
            if action == ACTION_EDIT:
                button.add_css_class("suggested-action")
            box.append(button)
        cancel = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Cancel (Esc)")
        cancel.connect("clicked", lambda _b: self.session.finish(None))
        box.append(cancel)
        return box

    def queue_draw_all(self):
        self.area.queue_draw()
        self._place_actions_bar()

    def _local_selection(self) -> Rect | None:
        sel = self.session.selection
        if sel is None:
            return None
        mx, my, _mw, _mh = self.monitor_rect
        return sel[0] - mx, sel[1] - my, sel[2], sel[3]

    def _place_actions_bar(self):
        bar = self.actions_bar
        sel = self._local_selection()
        if self._drag_mode is not None or sel is None or not self.session.has_selection():
            bar.set_visible(False)
            return
        x, y, w, h = sel
        _mx, _my, mw, mh = self.monitor_rect
        # Show the bar on the monitor that contains the selection's bottom-right corner.
        corner_x, corner_y = x + w, y + h
        if not (0 <= corner_x <= mw and 0 <= corner_y <= mh):
            bar.set_visible(False)
            return
        _min_w, nat_w, _b1, _b2 = bar.measure(Gtk.Orientation.HORIZONTAL, -1)
        _min_h, nat_h, _b3, _b4 = bar.measure(Gtk.Orientation.VERTICAL, -1)
        gap = 8
        left = min(max(0, corner_x - nat_w), mw - nat_w)
        if corner_y + gap + nat_h <= mh:
            top = corner_y + gap
        elif y - gap - nat_h >= 0:
            top = y - gap - nat_h
        else:
            top = max(0, corner_y - nat_h - gap)
        bar.set_margin_start(int(max(0, left)))
        bar.set_margin_top(int(max(0, top)))
        bar.set_visible(True)

    # -- drawing ------------------------------------------------------------
    def _draw(self, _area, cr, width, height):
        session = self.session
        mx, my, _mw, _mh = self.monitor_rect
        ox, oy = session.origin
        ratio = session.ratio

        cr.save()
        cr.scale(1 / ratio, 1 / ratio)
        cr.set_source_surface(session.image, -(mx - ox) * ratio, -(my - oy) * ratio)
        if ratio != 1:
            cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()

        sel = self._local_selection()
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(0, 0, width, height)
        if sel and sel[2] > 0 and sel[3] > 0:
            cr.rectangle(*sel)
        cr.set_source_rgba(0, 0, 0, DIM_ALPHA)
        cr.fill()
        cr.set_fill_rule(cairo.FILL_RULE_WINDING)

        if sel and sel[2] > 0 and sel[3] > 0:
            self._draw_selection(cr, sel)
        elif self.session.selection is None:
            self._draw_hint(cr, width, height)

    def _draw_selection(self, cr, sel):
        x, y, w, h = sel
        cr.set_source_rgb(*ACCENT)
        cr.set_line_width(1.5)
        cr.rectangle(x + 0.75, y + 0.75, max(0, w - 1.5), max(0, h - 1.5))
        cr.stroke()

        for hx, hy in self._handle_points(sel).values():
            half = HANDLE_SIZE / 2
            cr.rectangle(hx - half, hy - half, HANDLE_SIZE, HANDLE_SIZE)
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgb(*ACCENT)
            cr.set_line_width(1.5)
            cr.stroke()

        pw, ph = self.session.selection_size_px()
        label = f"{pw} × {ph}"
        lx = x
        ly = y - 30 if y >= 34 else y + 6
        self._draw_label(cr, label, lx + (6 if ly > y else 0), ly)

    def _draw_label(self, cr, text, x, y):
        layout = self.area.create_pango_layout(text)
        tw, th = layout.get_pixel_size()
        pad_x, pad_y = 8, 4
        self._rounded_rect(cr, x, y, tw + pad_x * 2, th + pad_y * 2, 6)
        cr.set_source_rgba(0, 0, 0, 0.75)
        cr.fill()
        cr.move_to(x + pad_x, y + pad_y)
        cr.set_source_rgb(1, 1, 1)
        PangoCairo.show_layout(cr, layout)

    def _draw_hint(self, cr, width, height):
        text = "Drag to select an area  ·  Space: whole screen  ·  Esc: cancel"
        layout = self.area.create_pango_layout(text)
        tw, _th = layout.get_pixel_size()
        self._draw_label(cr, text, (width - tw) / 2 - 8, 32)

    @staticmethod
    def _rounded_rect(cr, x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    @staticmethod
    def _handle_points(sel):
        x, y, w, h = sel
        return {
            "nw": (x, y),
            "n": (x + w / 2, y),
            "ne": (x + w, y),
            "e": (x + w, y + h / 2),
            "se": (x + w, y + h),
            "s": (x + w / 2, y + h),
            "sw": (x, y + h),
            "w": (x, y + h / 2),
        }

    # -- interaction --------------------------------------------------------
    def _to_global(self, x, y):
        return x + self.monitor_rect[0], y + self.monitor_rect[1]

    def _hit(self, x, y) -> str:
        """Return ``"move"``, a handle name, or ``"new"`` for the local point."""
        sel = self._local_selection()
        if sel is None or not self.session.has_selection():
            return "new"
        for name, (hx, hy) in self._handle_points(sel).items():
            if abs(x - hx) <= HANDLE_REACH and abs(y - hy) <= HANDLE_REACH:
                return name
        sx, sy, sw, sh = sel
        if sx <= x <= sx + sw and sy <= y <= sy + sh:
            return "move"
        return "new"

    def _on_motion(self, _controller, x, y):
        self._pointer = (x, y)
        if self._drag_mode is not None:
            return
        hit = self._hit(x, y)
        if hit == "new":
            self.area.set_cursor_from_name("crosshair")
        elif hit == "move":
            self.area.set_cursor_from_name("move")
        else:
            self.area.set_cursor_from_name(_HANDLE_CURSORS[hit])

    def _on_drag_begin(self, _gesture, x, y):
        self._drag_mode = self._hit(x, y)
        self._drag_origin = self.session.selection
        if self._drag_mode == "new":
            gx, gy = self._to_global(x, y)
            self.session.set_selection((gx, gy, 0, 0))
        self.queue_draw_all()

    def _on_drag_update(self, gesture, dx, dy):
        ok, sx, sy = gesture.get_start_point()
        if not ok or self._drag_mode is None:
            return
        gx0, gy0 = self._to_global(sx, sy)
        mode = self._drag_mode
        if mode == "new":
            gx1, gy1 = gx0 + dx, gy0 + dy
            self.session.set_selection((min(gx0, gx1), min(gy0, gy1), abs(gx1 - gx0), abs(gy1 - gy0)))
            return
        x, y, w, h = self._drag_origin
        if mode == "move":
            ux, uy, uw, uh = self.session.union
            nx = min(max(ux, x + dx), ux + uw - w)
            ny = min(max(uy, y + dy), uy + uh - h)
            self.session.set_selection((nx, ny, w, h))
            return
        x0, y0, x1, y1 = x, y, x + w, y + h
        if "w" in mode:
            x0 += dx
        if "e" in mode:
            x1 += dx
        if "n" in mode:
            y0 += dy
        if "s" in mode:
            y1 += dy
        self.session.set_selection((min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)))

    def _on_drag_end(self, _gesture, _dx, _dy):
        mode = self._drag_mode
        self._drag_mode = None
        if mode == "new" and not self.session.has_selection():
            # A plain click without dragging: restore the previous selection.
            self.session.set_selection(self._drag_origin)
        self.queue_draw_all()

    def _on_click(self, gesture, n_press, x, y):
        button = gesture.get_current_button()
        if button == Gdk.BUTTON_SECONDARY:
            if self.session.selection is not None:
                self.session.set_selection(None)
            else:
                self.session.finish(None)
            return
        if button == Gdk.BUTTON_PRIMARY and n_press == 2 and self._hit(x, y) != "new":
            self.session.finish(self.session.default_action)

    def _select_monitor(self):
        self.session.set_selection(self.monitor_rect)

    def _on_key(self, _controller, keyval, _keycode, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if keyval == Gdk.KEY_Escape:
            self.session.finish(None)
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter):
            self.session.finish(self.session.default_action)
        elif keyval == Gdk.KEY_space:
            self._select_monitor()
        elif ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_C):
            self.session.finish(ACTION_COPY)
        elif ctrl and keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self.session.finish(ACTION_SAVE)
        elif ctrl and keyval in (Gdk.KEY_a, Gdk.KEY_A):
            self._select_monitor()
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down) and self.session.has_selection():
            step = 10 if shift else 1
            dx = {Gdk.KEY_Left: -step, Gdk.KEY_Right: step}.get(keyval, 0)
            dy = {Gdk.KEY_Up: -step, Gdk.KEY_Down: step}.get(keyval, 0)
            x, y, w, h = self.session.selection
            if ctrl:
                self.session.set_selection((x, y, max(MIN_SELECTION, w + dx), max(MIN_SELECTION, h + dy)))
            else:
                self.session.set_selection((x + dx, y + dy, w, h))
        else:
            return False
        return True
