"""Registers the global capture shortcut as a GNOME custom keybinding.

Wayland does not let ordinary applications grab keys globally, so the shortcut is
handed to gnome-settings-daemon, which runs ``screencatch`` when it is pressed.
The entry shows up (and can be edited) in GNOME Settings > Keyboard > Custom Shortcuts.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys

from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

MEDIA_KEYS_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_KEYBINDING_SCHEMA = MEDIA_KEYS_SCHEMA + ".custom-keybinding"
KEYBINDING_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/screencatch/"
KEYBINDING_NAME = "ScreenCatch: capture region"
DEFAULT_ACCELERATOR = "<Control><Shift>Print"


def is_supported() -> bool:
    source = Gio.SettingsSchemaSource.get_default()
    if source is None:
        return False
    media_keys = source.lookup(MEDIA_KEYS_SCHEMA, True)
    return (
        media_keys is not None
        and media_keys.has_key("custom-keybindings")
        and source.lookup(CUSTOM_KEYBINDING_SCHEMA, True) is not None
    )


def with_path(paths: list[str], path: str = KEYBINDING_PATH) -> list[str]:
    return paths if path in paths else [*paths, path]


def without_path(paths: list[str], path: str = KEYBINDING_PATH) -> list[str]:
    return [p for p in paths if p != path]


def launch_command() -> str:
    """The command the keybinding should run."""
    launcher = os.path.realpath(sys.argv[0])
    installed = shutil.which("screencatch")
    if installed and os.path.realpath(installed) == launcher:
        return "screencatch"
    # Running from a development tree: point at this exact launcher.
    return GLib.shell_quote(launcher)


def is_registered() -> bool:
    if not is_supported():
        return False
    return KEYBINDING_PATH in Gio.Settings.new(MEDIA_KEYS_SCHEMA).get_strv("custom-keybindings")


def register(accelerator: str, command: str | None = None) -> bool:
    """Create or update the keybinding. Returns False when GNOME is not available."""
    if not is_supported():
        log.info("GNOME custom keybindings are not available; skipping shortcut setup")
        return False
    custom = Gio.Settings.new_with_path(CUSTOM_KEYBINDING_SCHEMA, KEYBINDING_PATH)
    custom.set_string("name", KEYBINDING_NAME)
    custom.set_string("command", command or launch_command())
    custom.set_string("binding", accelerator)
    media_keys = Gio.Settings.new(MEDIA_KEYS_SCHEMA)
    paths = list(media_keys.get_strv("custom-keybindings"))
    updated = with_path(paths)
    if updated != paths:
        media_keys.set_strv("custom-keybindings", updated)
    Gio.Settings.sync()
    log.info("Registered global shortcut %s", accelerator)
    return True


def unregister() -> None:
    if not is_supported():
        return
    media_keys = Gio.Settings.new(MEDIA_KEYS_SCHEMA)
    paths = list(media_keys.get_strv("custom-keybindings"))
    if KEYBINDING_PATH in paths:
        media_keys.set_strv("custom-keybindings", without_path(paths))
    custom = Gio.Settings.new_with_path(CUSTOM_KEYBINDING_SCHEMA, KEYBINDING_PATH)
    for key in ("name", "command", "binding"):
        custom.reset(key)
    Gio.Settings.sync()
    log.info("Removed global shortcut")
