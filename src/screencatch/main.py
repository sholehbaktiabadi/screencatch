"""Application entry point: command line, capture flow and app-wide actions."""

from __future__ import annotations

import logging
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
try:
    gi.require_foreign("cairo")
except ImportError:
    raise SystemExit("ScreenCatch: cairo support for PyGObject is missing (install python3-gi-cairo).") from None

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, ISSUE_URL, WEBSITE, __version__, export, shortcut  # noqa: E402
from .capture import CaptureCancelled, CapturePermissionError, ScreenshotPortal  # noqa: E402
from .gtkutil import ClipboardKeeper, load_image  # noqa: E402
from .overlay import ACTION_COPY, ACTION_EDIT, ACTION_SAVE, OverlaySession  # noqa: E402

log = logging.getLogger("screencatch")

# Time for our own windows to disappear from the screen before capturing.
HIDE_DELAY_MS = 300

CSS = """
.screencatch-overlay { background: black; }
.screencatch-actions { padding: 6px; border-radius: 12px; }
.screencatch-canvas { background-color: alpha(@view_fg_color, 0.08); }
.screencatch-swatch { min-width: 26px; min-height: 26px; padding: 2px; }
.screencatch-custom-color > button { min-width: 20px; padding: 4px 6px; }
"""


def _load_settings() -> Gio.Settings:
    source = Gio.SettingsSchemaSource.get_default()
    if source is None or source.lookup(APP_ID, True) is None:
        raise SystemExit(
            f"{APP_NAME}: the GSettings schema {APP_ID} is not installed. "
            "Install the package, or run ./run-dev.sh from the source tree."
        )
    return Gio.Settings.new(APP_ID)


class Application(Adw.Application):
    def __init__(self, pkgdatadir: str | None = None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.pkgdatadir = pkgdatadir
        self.settings: Gio.Settings | None = None
        self.clipboard = ClipboardKeeper(self)
        self.portal = ScreenshotPortal()
        self._capturing = False
        self._home = None
        self._permission_window = None

        GLib.set_application_name(APP_NAME)
        self.set_option_context_parameter_string("[IMAGE…]")
        self.set_option_context_summary("Take a screenshot and annotate it instantly.")
        for name, short, arg, description, arg_description in (
            ("full", "f", GLib.OptionArg.NONE, "Capture the whole screen and open the editor", None),
            ("delay", "d", GLib.OptionArg.INT, "Wait SECONDS before capturing", "SECONDS"),
            ("home", None, GLib.OptionArg.NONE, "Show the main window instead of capturing", None),
            ("preferences", None, GLib.OptionArg.NONE, "Open the preferences", None),
            ("debug", None, GLib.OptionArg.NONE, "Print debug messages", None),
            ("version", "v", GLib.OptionArg.NONE, "Show the version and exit", None),
            (GLib.OPTION_REMAINING, None, GLib.OptionArg.STRING_ARRAY, "Images to open in the editor", None),
        ):
            short_name = ord(short) if short else 0
            self.add_main_option(name, short_name, GLib.OptionFlags.NONE, arg, description, arg_description)

    # -- lifecycle ----------------------------------------------------------
    def do_handle_local_options(self, options):
        if options.contains("version"):
            print(f"{APP_NAME} {__version__}")
            return 0
        if options.contains("debug"):
            logging.getLogger().setLevel(logging.DEBUG)
        return -1

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.settings = _load_settings()

        display = Gdk.Display.get_default()
        if self.pkgdatadir:
            Gtk.IconTheme.get_for_display(display).add_search_path(os.path.join(self.pkgdatadir, "icons"))
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._setup_actions()
        self._setup_shortcut()

    def do_command_line(self, command_line):
        options = command_line.get_options_dict().end().unpack()
        files = options.get(GLib.OPTION_REMAINING, [])
        if files:
            for name in files:
                self.open_image(command_line.create_file_for_arg(name))
        elif "preferences" in options:
            self.show_preferences()
        elif "home" in options:
            self.show_home()
        else:
            self.start_capture(full="full" in options, delay=max(0, options.get("delay", 0)))
        return 0

    # -- actions ------------------------------------------------------------
    def _setup_actions(self):
        actions = {
            "capture-region": lambda *_: self.start_capture(),
            "capture-full": lambda *_: self.start_capture(full=True),
            "capture-delayed-region": lambda *_: self.start_capture(delay=self.settings.get_int("delay")),
            "capture-delayed-full": lambda *_: self.start_capture(full=True, delay=self.settings.get_int("delay")),
            "open-image": lambda *_: self.choose_image(),
            "preferences": lambda *_: self.show_preferences(),
            "shortcuts": lambda *_: self.show_shortcuts(),
            "about": lambda *_: self.show_about(),
            "quit": lambda *_: self.quit(),
        }
        for name, callback in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        show_file = Gio.SimpleAction.new("show-file", GLib.VariantType("s"))
        show_file.connect("activate", lambda _a, value: self.show_file(value.get_string()))
        self.add_action(show_file)

        accels = {
            "app.capture-region": ["<Control>n"],
            "app.open-image": ["<Control>o"],
            "app.preferences": ["<Control>comma"],
            "app.shortcuts": ["<Control>question"],
            "app.quit": ["<Control>q"],
            "win.undo": ["<Control>z"],
            "win.redo": ["<Control><Shift>z", "<Control>y"],
            "win.copy": ["<Control>c"],
            "win.save": ["<Control>s"],
            "win.save-as": ["<Control><Shift>s"],
            "win.done": ["<Control>Return", "<Control>KP_Enter"],
            "win.close": ["<Control>w"],
        }
        for action, keys in accels.items():
            self.set_accels_for_action(action, keys)

    def _setup_shortcut(self):
        self.settings.connect("changed::hotkey", lambda *_: self._apply_shortcut())
        self.settings.connect("changed::hotkey-enabled", lambda *_: self._apply_shortcut())
        if not shortcut.is_supported():
            return
        try:
            if not self.settings.get_boolean("hotkey-initialized"):
                self.settings.set_boolean("hotkey-initialized", True)
                self._apply_shortcut()
            elif self.settings.get_boolean("hotkey-enabled"):
                if shortcut.is_registered():
                    # Keep the command current, e.g. after moving from a dev build to the package.
                    shortcut.register(self.settings.get_string("hotkey"))
                else:
                    # The user removed it in GNOME Settings; reflect that instead of re-adding it.
                    self.settings.set_boolean("hotkey-enabled", False)
        except GLib.Error as exc:
            log.warning("Could not set up the global shortcut: %s", exc.message)

    def _apply_shortcut(self):
        try:
            accelerator = self.settings.get_string("hotkey")
            if self.settings.get_boolean("hotkey-enabled") and accelerator:
                shortcut.register(accelerator)
            else:
                shortcut.unregister()
        except GLib.Error as exc:
            log.warning("Could not update the global shortcut: %s", exc.message)

    # -- windows ------------------------------------------------------------
    def _active_window(self):
        window = self.get_active_window()
        if window is None or not window.get_visible():
            windows = [w for w in self.get_windows() if w.get_visible()]
            window = windows[0] if windows else None
        return window

    def show_home(self):
        from .window import HomeWindow

        if self._home is None:
            self._home = HomeWindow(self)
            self._home.connect("destroy", self._on_home_destroyed)
        self._home.present()
        return self._home

    def _on_home_destroyed(self, _window):
        self._home = None

    def _parent_window(self):
        return self._active_window() or self.show_home()

    def request_permission(self, on_granted):
        """Show the one-time window that lets the desktop ask for capture permission."""
        from .window import PermissionWindow

        if self._permission_window is None:
            self._permission_window = PermissionWindow(self, on_granted)
            self._permission_window.connect("destroy", self._on_permission_window_destroyed)
        self._permission_window.present()

    def _on_permission_window_destroyed(self, _window):
        self._permission_window = None

    def show_preferences(self):
        from .preferences import PreferencesDialog

        PreferencesDialog(self.settings).present(self._parent_window())

    def show_shortcuts(self):
        from .preferences import ShortcutsDialog

        ShortcutsDialog().present(self._parent_window())

    def show_about(self):
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            developer_name="Sholeh Bakti Abadi",
            version=__version__,
            website=WEBSITE,
            issue_url=ISSUE_URL,
            license_type=Gtk.License.MIT_X11,
            copyright="© 2026 Sholeh Bakti Abadi",
            developers=["Sholeh Bakti Abadi https://github.com/sholehbaktiabadi"],
            comments="Take a screenshot and mark it up with arrows, boxes, circles and text — instantly.",
        )
        about.present(self._parent_window())

    def show_error(self, heading: str, body: str):
        log.error("%s: %s", heading, body)
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "OK")
        dialog.present(self._parent_window())

    def show_file(self, path: str):
        launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(path))

        def on_done(source, result):
            try:
                source.open_containing_folder_finish(result)
            except GLib.Error as exc:
                log.warning("Could not open folder for %s: %s", path, exc.message)

        launcher.open_containing_folder(self._active_window(), None, on_done)

    def open_editor(self, surface, scale: float = 1.0, title: str | None = None):
        from .editor.window import EditorWindow

        window = EditorWindow(self, surface, scale, title)
        window.present()
        return window

    def open_image(self, file: Gio.File):
        path = file.get_path()
        if not path:
            self.show_error("Cannot Open Image", "Only local files are supported.")
            return
        try:
            surface = load_image(path)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            message = exc.message if isinstance(exc, GLib.Error) else str(exc)
            self.show_error("Cannot Open Image", f"{os.path.basename(path)}: {message}")
            return
        self.open_editor(surface, 1.0, os.path.basename(path))

    def choose_image(self):
        dialog = Gtk.FileDialog(title="Open Image", modal=True)
        images = Gtk.FileFilter(name="Images")
        images.add_pixbuf_formats()
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(images)
        dialog.set_filters(filters)

        def on_done(dlg, result):
            try:
                file = dlg.open_finish(result)
            except GLib.Error:
                return
            if file:
                self.open_image(file)

        dialog.open(self._active_window(), None, on_done)

    # -- capture flow -------------------------------------------------------
    def start_capture(self, full: bool = False, delay: int = 0):
        if self._capturing:
            log.debug("Capture already in progress")
            return
        self._capturing = True
        self.hold()
        hidden = [w for w in self.get_windows() if w.get_visible()]
        for window in hidden:
            window.set_visible(False)
        wait = delay * 1000 + (HIDE_DELAY_MS if hidden else 0)
        log.debug("Capturing in %d ms (full=%s)", wait, full)

        def capture():
            self.portal.capture(lambda surface, error: self._on_captured(surface, error, full, hidden))
            return GLib.SOURCE_REMOVE

        if wait:
            GLib.timeout_add(wait, capture)
        else:
            capture()

    def _end_capture(self, hidden):
        for window in hidden:
            window.set_visible(True)
        self._capturing = False
        self.release()

    def _on_captured(self, surface, error, full, hidden):
        if error is not None:
            self._end_capture(hidden)
            if isinstance(error, CapturePermissionError):
                self.request_permission(lambda: self.start_capture(full=full))
            elif not isinstance(error, CaptureCancelled):
                self.show_error("Screenshot Failed", str(error))
            return
        if full:
            ratio = self._desktop_ratio(surface)
            self._end_capture(hidden)
            self.open_editor(surface, ratio)
            return

        def on_done(action, region, ratio):
            self._end_capture(hidden)
            if action is not None and region is not None:
                self._handle_region(action, region, ratio)

        enter_action = self.settings.get_string("enter-action")
        if enter_action not in (ACTION_EDIT, ACTION_COPY, ACTION_SAVE):
            enter_action = ACTION_EDIT
        OverlaySession(self, surface, enter_action, on_done).present()

    @staticmethod
    def _desktop_ratio(surface) -> float:
        display = Gdk.Display.get_default()
        monitors = display.get_monitors()
        right = 0
        left = None
        for index in range(monitors.get_n_items()):
            g = monitors.get_item(index).get_geometry()
            left = g.x if left is None else min(left, g.x)
            right = max(right, g.x + g.width)
        width = right - (left or 0)
        return surface.get_width() / width if width > 0 else 1.0

    def _handle_region(self, action, region, ratio):
        if action == ACTION_EDIT:
            self.open_editor(region, ratio)
        elif action == ACTION_COPY:
            try:
                self.clipboard.copy(region)
            except Exception as exc:  # noqa: BLE001 - shown to the user
                self.show_error("Could Not Copy", str(exc))
                return
            self.notify_result(True, None)
        elif action == ACTION_SAVE:
            directory = export.resolve_save_dir(self.settings.get_string("save-directory"))
            try:
                path = export.save_to_folder(region, directory, self.settings.get_string("filename-template"))
            except OSError as exc:
                self.show_error("Could Not Save", str(exc))
                return
            self.notify_result(False, path)

    def notify_result(self, copied: bool, path: str | None):
        """Tell the user what happened once no ScreenCatch window is left to show it."""
        if path and copied:
            title = "Screenshot copied and saved"
        elif path:
            title = "Screenshot saved"
        elif copied:
            title = "Screenshot copied to clipboard"
        else:
            return
        notification = Gio.Notification.new(title)
        notification.set_icon(Gio.ThemedIcon.new(APP_ID))
        if path:
            notification.set_body(path.replace(GLib.get_home_dir(), "~", 1))
            notification.set_default_action_and_target("app.show-file", GLib.Variant("s", path))
            notification.add_button_with_target("Show in Folder", "app.show-file", GLib.Variant("s", path))
        else:
            notification.set_body("Paste it anywhere with Ctrl+V.")
        self.send_notification("result", notification)


def run(pkgdatadir: str | None = None, argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(levelname)s: %(message)s")
    app = Application(pkgdatadir)
    return app.run(argv if argv is not None else sys.argv)
