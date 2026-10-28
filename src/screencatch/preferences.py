"""Preferences and keyboard-shortcut dialogs."""

from __future__ import annotations

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from . import export, shortcut

ENTER_ACTIONS = (
    ("edit", "Open the editor"),
    ("copy", "Copy to clipboard"),
    ("save", "Save to folder"),
)


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, settings: Gio.Settings):
        super().__init__(title="Preferences", search_enabled=False)
        self.settings = settings
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")
        self.add(page)
        page.add(self._build_capture_group())
        page.add(self._build_done_group())
        page.add(self._build_saving_group())
        page.add(self._build_shortcut_group())

    # -- groups -------------------------------------------------------------
    def _build_capture_group(self):
        group = Adw.PreferencesGroup(title="After Selecting a Region")
        row = Adw.ComboRow(
            title="Enter key and double-click",
            subtitle="The quick action in the selection overlay",
            model=Gtk.StringList.new([label for _key, label in ENTER_ACTIONS]),
        )
        keys = [key for key, _label in ENTER_ACTIONS]
        current = self.settings.get_string("enter-action")
        row.set_selected(keys.index(current) if current in keys else 0)
        row.connect("notify::selected", lambda r, _p: self.settings.set_string("enter-action", keys[r.get_selected()]))
        group.add(row)
        return group

    def _build_done_group(self):
        group = Adw.PreferencesGroup(title="Editor “Done” Button")
        for key, title in (
            ("done-copy", "Copy to clipboard"),
            ("done-save", "Save to folder"),
            ("close-after-done", "Close the editor"),
        ):
            row = Adw.SwitchRow(title=title)
            self.settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
            group.add(row)
        return group

    def _build_saving_group(self):
        group = Adw.PreferencesGroup(title="Saving")

        self.folder_row = Adw.ActionRow(title="Folder")
        self.folder_row.add_css_class("property")
        choose = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Choose Folder")
        choose.add_css_class("flat")
        choose.connect("clicked", self._choose_folder)
        reset = Gtk.Button(icon_name="edit-undo-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Use Default Folder")
        reset.add_css_class("flat")
        reset.connect("clicked", lambda _b: self.settings.reset("save-directory"))
        self.folder_row.add_suffix(choose)
        self.folder_row.add_suffix(reset)
        group.add(self.folder_row)

        self.template_row = Adw.EntryRow(title="File name", show_apply_button=True)
        self.template_row.set_text(self.settings.get_string("filename-template"))
        self.template_row.connect("apply", self._apply_template)
        group.add(self.template_row)

        self.example_row = Adw.ActionRow(title="Example", subtitle_selectable=True)
        self.example_row.add_css_class("property")
        group.add(self.example_row)
        group.set_description("The file name accepts strftime codes such as %Y, %m, %d, %H, %M and %S.")

        self.settings.connect("changed::save-directory", lambda *_: self._refresh_saving())
        self.settings.connect("changed::filename-template", lambda *_: self._refresh_saving())
        self._refresh_saving()
        return group

    def _build_shortcut_group(self):
        group = Adw.PreferencesGroup(title="Global Shortcut")
        if not shortcut.is_supported():
            group.set_description(
                "Automatic setup needs GNOME. In your desktop's keyboard settings, "
                "bind a key to the command “screencatch”."
            )
            return group
        group.set_description("Captures a region from anywhere. Managed through GNOME's custom keyboard shortcuts.")

        enabled = Adw.SwitchRow(title="Enable shortcut")
        self.settings.bind("hotkey-enabled", enabled, "active", Gio.SettingsBindFlags.DEFAULT)
        group.add(enabled)

        self.hotkey_row = Adw.ActionRow(title="Shortcut")
        self.hotkey_label = Gtk.ShortcutLabel(valign=Gtk.Align.CENTER)
        change = Gtk.Button(label="Change…", valign=Gtk.Align.CENTER)
        change.connect("clicked", self._change_hotkey)
        self.hotkey_row.add_suffix(self.hotkey_label)
        self.hotkey_row.add_suffix(change)
        self.settings.bind("hotkey-enabled", self.hotkey_row, "sensitive", Gio.SettingsBindFlags.GET)
        group.add(self.hotkey_row)

        self.settings.connect("changed::hotkey", lambda *_: self._refresh_hotkey())
        self._refresh_hotkey()
        return group

    # -- callbacks ----------------------------------------------------------
    def _refresh_saving(self):
        directory = export.resolve_save_dir(self.settings.get_string("save-directory"))
        self.folder_row.set_subtitle(directory.replace(GLib.get_home_dir(), "~", 1))
        self.example_row.set_subtitle(export.expand_template(self.settings.get_string("filename-template")))

    def _apply_template(self, row):
        template = row.get_text().strip()
        if template:
            self.settings.set_string("filename-template", template)
        else:
            self.settings.reset("filename-template")
            row.set_text(self.settings.get_string("filename-template"))

    def _choose_folder(self, _button):
        dialog = Gtk.FileDialog(title="Choose Screenshot Folder", modal=True)
        current = export.resolve_save_dir(self.settings.get_string("save-directory"))
        dialog.set_initial_folder(Gio.File.new_for_path(current))

        def on_done(dlg, result):
            try:
                folder = dlg.select_folder_finish(result)
            except GLib.Error:
                return
            if folder and folder.get_path():
                self.settings.set_string("save-directory", folder.get_path())

        dialog.select_folder(self.get_root(), None, on_done)

    def _refresh_hotkey(self):
        self.hotkey_label.set_accelerator(self.settings.get_string("hotkey"))

    def _change_hotkey(self, _button):
        dialog = ShortcutCaptureDialog()
        dialog.connect("captured", lambda _d, accel: self.settings.set_string("hotkey", accel))
        dialog.present(self)


class ShortcutCaptureDialog(Adw.AlertDialog):
    __gsignals__ = {"captured": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self):
        super().__init__(
            heading="Set Shortcut",
            body="Press the new key combination, or Esc to cancel.\n"
            "Plain Print and Shift+Print are reserved by GNOME's own screenshot tool.",
            close_response="cancel",
        )
        self.add_response("cancel", "Cancel")
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    def _on_key(self, _controller, keyval, _keycode, state):
        modifiers = state & Gtk.accelerator_get_default_mod_mask()
        if keyval == Gdk.KEY_Escape and not modifiers:
            self.close()
            return True
        if keyval in (
            Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Control_L, Gdk.KEY_Control_R,
            Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Super_L, Gdk.KEY_Super_R,
            Gdk.KEY_Meta_L, Gdk.KEY_Meta_R, Gdk.KEY_ISO_Level3_Shift,
        ):  # fmt: skip
            return True
        if keyval == Gdk.KEY_Sys_Req:
            # Alt+Print is reported as Sys_Req on most keyboards.
            keyval = Gdk.KEY_Print
        keyval = Gdk.keyval_to_lower(keyval)
        if not Gtk.accelerator_valid(keyval, modifiers):
            return True
        if not modifiers and keyval != Gdk.KEY_Print and not (Gdk.KEY_F1 <= keyval <= Gdk.KEY_F35):
            # A bare letter would make that key unusable for typing.
            return True
        self.emit("captured", Gtk.accelerator_name(keyval, modifiers))
        self.close()
        return True


SHORTCUTS = (
    (
        "Selection Overlay",
        (
            ("Open editor", "Return"),
            ("Copy region", "<Control>c"),
            ("Save region", "<Control>s"),
            ("Select whole screen", "space"),
            ("Move / resize selection", "Left Right Up Down"),
            ("Cancel", "Escape"),
        ),
    ),
    (
        "Editor Tools",
        (
            ("Select and move", "v"),
            ("Arrow", "a"),
            ("Rectangle", "r"),
            ("Ellipse", "e"),
            ("Line", "l"),
            ("Pen", "p"),
            ("Highlighter", "h"),
            ("Text", "t"),
            ("Numbered step", "n"),
            ("Pixelate", "b"),
            ("Crop", "c"),
            ("Constrain shape (square, circle, 45°)", "hold:Shift"),
        ),
    ),
    (
        "Editor",
        (
            ("Done", "<Control>Return"),
            ("Copy to clipboard", "<Control>c"),
            ("Save", "<Control>s"),
            ("Save as", "<Control><Shift>s"),
            ("Undo", "<Control>z"),
            ("Redo", "<Control><Shift>z"),
            ("Delete selected annotation", "Delete"),
            ("Close", "<Control>w"),
        ),
    ),
    (
        "General",
        (
            ("New capture", "<Control>n"),
            ("Open image", "<Control>o"),
            ("Preferences", "<Control>comma"),
            ("Quit", "<Control>q"),
        ),
    ),
)


class ShortcutsDialog(Adw.Dialog):
    def __init__(self):
        super().__init__(title="Keyboard Shortcuts", content_width=480, content_height=640)
        page = Adw.PreferencesPage()
        for title, items in SHORTCUTS:
            group = Adw.PreferencesGroup(title=title)
            for label, accelerator in items:
                row = Adw.ActionRow(title=label)
                if accelerator.startswith("hold:"):
                    hint = Gtk.Label(label="Hold " + accelerator[5:], valign=Gtk.Align.CENTER)
                    hint.add_css_class("dim-label")
                    row.add_suffix(hint)
                else:
                    row.add_suffix(Gtk.ShortcutLabel(accelerator=accelerator, valign=Gtk.Align.CENTER))
                group.add(row)
            page.add(group)
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)
