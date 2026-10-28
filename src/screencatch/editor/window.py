"""The annotation editor window."""

from __future__ import annotations

import logging
import math
import os

import cairo
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .. import export
from .canvas import Canvas
from .document import Document
from .history import History, SetCrop
from .shapes import color_to_hex, parse_color

log = logging.getLogger(__name__)

# (id, icon, tooltip, key)
TOOLS = (
    ("select", "screencatch-select-symbolic", "Select and Move", "v"),
    ("arrow", "screencatch-arrow-symbolic", "Arrow", "a"),
    ("rectangle", "screencatch-rectangle-symbolic", "Rectangle", "r"),
    ("ellipse", "screencatch-ellipse-symbolic", "Ellipse", "e"),
    ("line", "screencatch-line-symbolic", "Line", "l"),
    ("pen", "screencatch-pen-symbolic", "Pen", "p"),
    ("highlighter", "screencatch-highlighter-symbolic", "Highlighter", "h"),
    ("text", "screencatch-text-symbolic", "Text", "t"),
    ("counter", "screencatch-counter-symbolic", "Numbered Step", "n"),
    ("pixelate", "screencatch-pixelate-symbolic", "Pixelate", "b"),
    ("crop", "screencatch-crop-symbolic", "Crop", "c"),
)
TOOL_KEYS = {getattr(Gdk, "KEY_" + key): tool for tool, _icon, _tip, key in TOOLS}

COLORS = (
    ("#e01b24", "Red"),
    ("#ff7800", "Orange"),
    ("#f6d32d", "Yellow"),
    ("#2ec27e", "Green"),
    ("#3584e4", "Blue"),
    ("#9141ac", "Purple"),
    ("#ffffff", "White"),
    ("#000000", "Black"),
)
WIDTHS = ((2, "Small"), (4, "Medium"), (8, "Large"))


class _Swatch(Gtk.DrawingArea):
    """A small circle used as the face of color and size buttons."""

    def __init__(self, color: str | None = None, diameter: float = 16):
        super().__init__(content_width=18, content_height=18, can_target=False)
        self._color = parse_color(color) if color else None
        self._diameter = diameter
        self.set_draw_func(self._draw)

    def _draw(self, _area, cr, width, height):
        radius = self._diameter / 2
        cr.arc(width / 2, height / 2, radius, 0, 2 * math.pi)
        if self._color is None:
            fg = self.get_color()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, fg.alpha)
            cr.fill()
            return
        cr.set_source_rgba(*self._color)
        cr.fill_preserve()
        fg = self.get_color()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.35)
        cr.set_line_width(1)
        cr.stroke()


class EditorWindow(Adw.ApplicationWindow):
    def __init__(self, app, surface: cairo.ImageSurface, scale: float = 1.0, title: str | None = None):
        super().__init__(application=app, title=title or "ScreenCatch")
        self.app = app
        self.settings = app.settings
        self.doc = Document(surface, scale)
        self.history = History(self.doc, self._on_history_changed)
        self._exported_version = 0
        self._saved_path: str | None = None
        self._force_close = False

        self.canvas = Canvas(self.doc, self.history)
        self.canvas.connect("selection-changed", lambda _c: self._update_actions())

        self._setup_actions()
        self._build_ui()
        self._restore_style()
        self._set_default_size()

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self.connect("close-request", self._on_close_request)
        self._update_actions()

    # -- construction -------------------------------------------------------
    def _setup_actions(self):
        simple = {
            "undo": lambda *_: self.history.undo(),
            "redo": lambda *_: self.history.redo(),
            "copy": lambda *_: self.copy(),
            "save": lambda *_: self.save(),
            "save-as": lambda *_: self.save_as(),
            "done": lambda *_: self.done(),
            "delete": lambda *_: self.canvas.delete_selected(),
            "reset-crop": lambda *_: self._reset_crop(),
            "close": lambda *_: self.close(),
        }
        for name, callback in simple.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        tool = Gio.SimpleAction.new_stateful("tool", GLib.VariantType("s"), GLib.Variant("s", "arrow"))
        tool.connect("change-state", self._on_tool_changed)
        self.add_action(tool)

        color = Gio.SimpleAction.new_stateful("color", GLib.VariantType("s"), GLib.Variant("s", COLORS[0][0]))
        color.connect("change-state", self._on_color_changed)
        self.add_action(color)

        width = Gio.SimpleAction.new_stateful("width", GLib.VariantType("i"), GLib.Variant("i", 4))
        width.connect("change-state", self._on_width_changed)
        self.add_action(width)

    def _build_ui(self):
        header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle(title="ScreenCatch")
        header.set_title_widget(self.title_widget)

        header.pack_start(
            Gtk.Button(icon_name="edit-undo-symbolic", action_name="win.undo", tooltip_text="Undo (Ctrl+Z)")
        )
        header.pack_start(
            Gtk.Button(icon_name="edit-redo-symbolic", action_name="win.redo", tooltip_text="Redo (Ctrl+Shift+Z)")
        )

        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Save As…", "win.save-as")
        section.append("Reset Crop", "win.reset-crop")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("New Capture", "app.capture-region")
        section.append("Open Image…", "app.open-image")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Preferences", "app.preferences")
        section.append("Keyboard Shortcuts", "app.shortcuts")
        section.append("About ScreenCatch", "app.about")
        menu.append_section(None, section)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Main Menu"))

        done = Gtk.Button(label="Done", action_name="win.done", tooltip_text="Finish (Ctrl+Enter)")
        done.add_css_class("suggested-action")
        header.pack_end(done)
        header.pack_end(
            Gtk.Button(icon_name="document-save-symbolic", action_name="win.save", tooltip_text="Save (Ctrl+S)")
        )
        copy = Gtk.Button(icon_name="edit-copy-symbolic", action_name="win.copy")
        copy.set_tooltip_text("Copy to Clipboard (Ctrl+C)")
        header.pack_end(copy)

        toolbar = Gtk.Box(spacing=2, halign=Gtk.Align.CENTER, margin_start=6, margin_end=6)
        toolbar.add_css_class("toolbar")
        for tool, icon, tip, key in TOOLS:
            button = Gtk.ToggleButton(
                icon_name=icon,
                tooltip_text=f"{tip} ({key.upper()})",
                action_name="win.tool",
                action_target=GLib.Variant("s", tool),
                focus_on_click=False,
            )
            button.add_css_class("flat")
            toolbar.append(button)
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        for hex_color, name in COLORS:
            button = Gtk.ToggleButton(
                tooltip_text=name,
                action_name="win.color",
                action_target=GLib.Variant("s", hex_color),
                focus_on_click=False,
            )
            button.set_child(_Swatch(hex_color))
            button.add_css_class("flat")
            button.add_css_class("circular")
            button.add_css_class("screencatch-swatch")
            toolbar.append(button)

        self.color_button = Gtk.ColorDialogButton(
            dialog=Gtk.ColorDialog(with_alpha=False), tooltip_text="Custom Color"
        )
        self.color_button.set_valign(Gtk.Align.CENTER)
        self.color_button.add_css_class("screencatch-custom-color")
        self.color_button.connect("notify::rgba", self._on_custom_color)
        toolbar.append(self.color_button)
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        for width, name in WIDTHS:
            button = Gtk.ToggleButton(
                tooltip_text=f"{name} Size",
                action_name="win.width",
                action_target=GLib.Variant("i", width),
                focus_on_click=False,
            )
            button.set_child(_Swatch(None, diameter=3 + width * 1.25))
            button.add_css_class("flat")
            button.add_css_class("screencatch-swatch")
            toolbar.append(button)

        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
            child=toolbar,
        )

        self.toasts = Adw.ToastOverlay(child=self.canvas)
        self.toasts.add_css_class("screencatch-canvas")

        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        view.add_top_bar(scroller)
        self.set_content(view)

    def _restore_style(self):
        tool = self.settings.get_string("tool")
        if tool not in {t[0] for t in TOOLS} or tool == "crop":
            tool = "arrow"
        self.activate_action("win.tool", GLib.Variant("s", tool))
        color = self.settings.get_string("color")
        try:
            parse_color(color)
        except ValueError:
            color = COLORS[0][0]
        self.activate_action("win.color", GLib.Variant("s", color))
        width = self.settings.get_int("stroke-width")
        if width not in {w for w, _n in WIDTHS}:
            width = 4
        self.activate_action("win.width", GLib.Variant("i", width))

    def _set_default_size(self):
        image_w = self.doc.width / self.doc.scale
        image_h = self.doc.height / self.doc.scale
        max_w, max_h = 1280, 800
        display = Gdk.Display.get_default()
        monitors = display.get_monitors() if display else None
        if monitors and monitors.get_n_items():
            geometry = monitors.get_item(0).get_geometry()
            max_w, max_h = int(geometry.width * 0.85), int(geometry.height * 0.85)
        width = int(min(max(image_w + 2 * 16, 1010), max_w))
        height = int(min(max(image_h + 2 * 16 + 110, 480), max_h))
        self.set_default_size(width, height)
        self.title_widget.set_subtitle(f"{self.doc.width} × {self.doc.height}")

    # -- state --------------------------------------------------------------
    def _on_history_changed(self):
        self.canvas.document_changed()
        _x, _y, w, h = self.doc.view_rect
        self.title_widget.set_subtitle(f"{w} × {h}")
        self._update_actions()

    def _update_actions(self):
        self.lookup_action("undo").set_enabled(self.history.can_undo)
        self.lookup_action("redo").set_enabled(self.history.can_redo)
        self.lookup_action("delete").set_enabled(self.canvas.selected is not None)
        self.lookup_action("reset-crop").set_enabled(self.doc.crop is not None)

    @property
    def is_dirty(self) -> bool:
        return self.history.version != self._exported_version and (bool(self.doc.shapes) or self.doc.crop is not None)

    def _mark_exported(self):
        self._exported_version = self.history.version

    def _reset_crop(self):
        if self.doc.crop is not None:
            self.history.push(SetCrop(None))

    def _on_tool_changed(self, action, value):
        action.set_state(value)
        tool = value.get_string()
        self.canvas.set_tool(tool)
        if tool != "crop":
            self.settings.set_string("tool", tool)

    def _on_color_changed(self, action, value):
        action.set_state(value)
        hex_color = value.get_string()
        color = parse_color(hex_color)
        self.canvas.set_color(color)
        self.settings.set_string("color", hex_color)

    def _on_custom_color(self, button, _pspec):
        rgba = button.get_rgba()
        hex_color = color_to_hex((rgba.red, rgba.green, rgba.blue, 1.0))
        current = self.lookup_action("color").get_state().get_string()
        if hex_color != current:
            self.activate_action("win.color", GLib.Variant("s", hex_color))

    def _on_width_changed(self, action, value):
        action.set_state(value)
        width = value.get_int32()
        self.canvas.set_width_level(width)
        self.settings.set_int("stroke-width", width)

    # -- keyboard -----------------------------------------------------------
    def _on_key(self, _controller, keyval, _keycode, state):
        modifiers = state & Gtk.accelerator_get_default_mod_mask()
        if modifiers & ~Gdk.ModifierType.SHIFT_MASK:
            return False
        if keyval == Gdk.KEY_Escape:
            if self.canvas.selected is not None:
                self.canvas.select(None)
            else:
                self.close()
            return True
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete, Gdk.KEY_BackSpace):
            return self.canvas.delete_selected()
        if modifiers:
            return False
        tool = TOOL_KEYS.get(Gdk.keyval_to_lower(keyval))
        if tool:
            self.activate_action("win.tool", GLib.Variant("s", tool))
            return True
        return False

    # -- output -------------------------------------------------------------
    def _render(self) -> cairo.ImageSurface:
        return self.doc.export()

    def _toast(self, title: str, path: str | None = None):
        toast = Adw.Toast(title=title, timeout=3)
        if path:
            toast.set_button_label("Show in Folder")
            toast.set_action_name("app.show-file")
            toast.set_action_target_value(GLib.Variant("s", path))
        self.toasts.add_toast(toast)

    def _error(self, heading: str, body: str):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "OK")
        dialog.present(self)

    def copy(self, quiet: bool = False) -> bool:
        try:
            self.app.clipboard.copy(self._render())
        except Exception as exc:  # noqa: BLE001 - reported to the user
            log.exception("Copy failed")
            self._error("Could Not Copy", str(exc))
            return False
        self._mark_exported()
        if not quiet:
            self._toast("Copied to clipboard")
        return True

    def save(self, quiet: bool = False) -> str | None:
        try:
            surface = self._render()
            if self._saved_path:
                path = export.save_surface(surface, self._saved_path)
            else:
                directory = export.resolve_save_dir(self.settings.get_string("save-directory"))
                path = export.save_to_folder(surface, directory, self.settings.get_string("filename-template"))
        except (OSError, cairo.Error) as exc:
            log.exception("Save failed")
            self._error("Could Not Save", str(exc))
            return None
        self._saved_path = path
        self._mark_exported()
        if not quiet:
            self._toast(f"Saved as “{os.path.basename(path)}”", path)
        return path

    def save_as(self):
        dialog = Gtk.FileDialog(title="Save Screenshot", modal=True)
        directory = export.resolve_save_dir(self.settings.get_string("save-directory"))
        if self._saved_path:
            dialog.set_initial_file(Gio.File.new_for_path(self._saved_path))
        else:
            if os.path.isdir(directory):
                dialog.set_initial_folder(Gio.File.new_for_path(directory))
            dialog.set_initial_name(export.expand_template(self.settings.get_string("filename-template")))
        png = Gtk.FileFilter(name="PNG images")
        png.add_mime_type("image/png")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(png)
        dialog.set_filters(filters)
        dialog.set_default_filter(png)

        def on_done(dlg, result):
            try:
                file = dlg.save_finish(result)
            except GLib.Error as exc:
                if not exc.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                    self._error("Could Not Save", exc.message)
                return
            path = file.get_path()
            if not path:
                self._error("Could Not Save", "Only local folders are supported.")
                return
            if not path.lower().endswith(".png"):
                path += ".png"
            try:
                export.save_surface(self._render(), path)
            except (OSError, cairo.Error) as exc:
                self._error("Could Not Save", str(exc))
                return
            self._saved_path = path
            self._mark_exported()
            self._toast(f"Saved as “{os.path.basename(path)}”", path)

        dialog.save(self, None, on_done)

    def done(self):
        want_copy = self.settings.get_boolean("done-copy")
        want_save = self.settings.get_boolean("done-save")
        if not want_copy and not want_save:
            want_copy = True
        copied = self.copy(quiet=True) if want_copy else False
        path = self.save(quiet=True) if want_save else None
        if (want_copy and not copied) or (want_save and not path):
            return
        if self.settings.get_boolean("close-after-done"):
            self.app.notify_result(copied, path)
            self._force_close = True
            self.close()
        elif path:
            self._toast(("Copied and saved" if copied else "Saved") + f" as “{os.path.basename(path)}”", path)
        else:
            self._toast("Copied to clipboard")

    def _on_close_request(self, _window):
        if self._force_close or not self.is_dirty:
            return False
        dialog = Adw.AlertDialog(
            heading="Discard Annotations?",
            body="This screenshot has not been copied or saved since your last change.",
            close_response="cancel",
            default_response="cancel",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("discard", "Discard")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_dialog, response):
            if response == "discard":
                self._force_close = True
                self.close()

        dialog.connect("response", on_response)
        dialog.present(self)
        return True
