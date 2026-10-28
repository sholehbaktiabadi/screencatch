"""The launcher window shown when ScreenCatch is opened from the app grid, and the
one-time screen capture permission window."""

from __future__ import annotations

from gi.repository import Adw, Gio, GLib, Gtk

from . import APP_ID, shortcut
from .capture import CaptureCancelled


class HomeWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="ScreenCatch", default_width=440, default_height=640)
        settings = app.settings

        header = Adw.HeaderBar()
        menu = Gio.Menu()
        menu.append("Open Image…", "app.open-image")
        section = Gio.Menu()
        section.append("Preferences", "app.preferences")
        section.append("Keyboard Shortcuts", "app.shortcuts")
        section.append("About ScreenCatch", "app.about")
        menu.append_section(None, section)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Main Menu"))

        status = Adw.StatusPage(icon_name=APP_ID, title="ScreenCatch", vexpand=True)
        self.hint = status
        settings.connect("changed::hotkey", lambda *_: self._refresh_hint())
        settings.connect("changed::hotkey-enabled", lambda *_: self._refresh_hint())

        buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        region = Gtk.Button(label="Capture Region", action_name="app.capture-delayed-region")
        region.add_css_class("pill")
        region.add_css_class("suggested-action")
        full = Gtk.Button(label="Capture Whole Screen", action_name="app.capture-delayed-full")
        full.add_css_class("pill")
        buttons.append(region)
        buttons.append(full)

        delay_group = Adw.PreferencesGroup(margin_top=24)
        delay = Adw.SpinRow.new_with_range(0, 30, 1)
        delay.set_title("Delay")
        delay.set_subtitle("Seconds to wait before capturing")
        settings.bind("delay", delay, "value", Gio.SettingsBindFlags.DEFAULT)
        delay_group.add(delay)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(buttons)
        content.append(delay_group)
        clamp = Adw.Clamp(maximum_size=360, child=content, margin_bottom=32, margin_start=16, margin_end=16)
        status.set_child(clamp)

        view = Adw.ToolbarView(content=status)
        view.add_top_bar(header)
        self.set_content(view)
        self.settings = settings
        self._refresh_hint()

    def _refresh_hint(self):
        accelerator = self.settings.get_string("hotkey")
        if self.settings.get_boolean("hotkey-enabled") and shortcut.is_supported() and accelerator:
            ok, keyval, mods = Gtk.accelerator_parse(accelerator)
            label = Gtk.accelerator_get_label(keyval, mods) if ok and keyval else accelerator
            label = GLib.markup_escape_text(label)
            self.hint.set_description(f"Press <b>{label}</b> anywhere to capture and annotate a region.")
        else:
            self.hint.set_description("Capture a region, mark it up with arrows, boxes and text, then copy or save it.")


class PermissionWindow(Adw.ApplicationWindow):
    """Asks the desktop for screen capture permission while ScreenCatch has focus.

    GNOME only shows its "Allow … to take screenshots?" dialog for the focused app,
    but a capture normally runs with every ScreenCatch window hidden. This window
    gives the request a focused window once; afterwards captures work silently.
    """

    def __init__(self, app, on_granted):
        super().__init__(application=app, title="Allow Screen Capture", default_width=440, default_height=520)
        self.app = app
        self.on_granted = on_granted

        self.status = Adw.StatusPage(icon_name=APP_ID, title="Allow Screen Capture", vexpand=True)
        self.button = Gtk.Button(label="Allow Screen Capture", halign=Gtk.Align.CENTER)
        self.button.add_css_class("pill")
        self.button.add_css_class("suggested-action")
        self.button.connect("clicked", self._on_clicked)
        self.feedback = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, visible=False, margin_top=18)
        self.feedback.add_css_class("error")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(self.button)
        content.append(self.feedback)
        self.status.set_child(Adw.Clamp(maximum_size=360, child=content, margin_start=16, margin_end=16))

        view = Adw.ToolbarView(content=self.status)
        view.add_top_bar(Adw.HeaderBar())
        self.set_content(view)
        self._refresh()

    def _denied(self) -> bool:
        return self.app.portal.get_permission(APP_ID) == "no"

    def _refresh(self):
        if self._denied():
            self.status.set_description(
                "Screen capture was denied for ScreenCatch earlier. Click the button to ask again, "
                "then choose <b>Allow</b>."
            )
        else:
            self.status.set_description(
                "Your desktop needs to approve screen capture once. Click the button, then choose "
                "<b>Allow</b> in the dialog that appears."
            )

    def _on_clicked(self, _button):
        self.button.set_sensitive(False)
        self.feedback.set_visible(False)
        if self._denied():
            self.app.portal.reset_permission(APP_ID)
        # Capture with this window visible and focused so the desktop may ask.
        self.app.portal.capture(self._on_result)

    def _on_result(self, _surface, error):
        if error is None:
            self.destroy()
            self.on_granted()
            return
        self.button.set_sensitive(True)
        if isinstance(error, CaptureCancelled):
            message = "The request was cancelled. Click the button to try again."
        else:
            message = f"Screen capture is still not allowed. {error}"
        self.feedback.set_label(message)
        self.feedback.set_visible(True)
        self._refresh()
