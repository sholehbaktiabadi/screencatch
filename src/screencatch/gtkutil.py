"""Helpers that need GTK: textures, the clipboard and opening images."""

from __future__ import annotations

import io
import logging
import sys

import cairo
from gi.repository import Gdk, GLib, GObject, Gtk

log = logging.getLogger(__name__)


def surface_to_texture(surface: cairo.ImageSurface) -> Gdk.Texture:
    """Wrap an ARGB32 cairo surface in a GdkTexture without re-encoding."""
    if surface.get_format() != cairo.FORMAT_ARGB32:
        converted = cairo.ImageSurface(cairo.FORMAT_ARGB32, surface.get_width(), surface.get_height())
        cr = cairo.Context(converted)
        cr.set_source_surface(surface, 0, 0)
        cr.paint()
        surface = converted
    surface.flush()
    # cairo stores ARGB32 as native-endian 32-bit words.
    if sys.byteorder == "little":
        memory_format = Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED
    else:
        memory_format = Gdk.MemoryFormat.A8R8G8B8_PREMULTIPLIED
    data = GLib.Bytes.new(bytes(surface.get_data()))
    return Gdk.MemoryTexture.new(surface.get_width(), surface.get_height(), memory_format, data, surface.get_stride())


def load_image(path: str) -> cairo.ImageSurface:
    """Load any image format GTK understands into a cairo surface."""
    if path.lower().endswith(".png"):
        try:
            return cairo.ImageSurface.create_from_png(path)
        except (cairo.Error, MemoryError):
            pass  # Fall back to the GTK loaders below.
    texture = Gdk.Texture.new_from_filename(path)
    png = texture.save_to_png_bytes().get_data()
    return cairo.ImageSurface.create_from_png(io.BytesIO(png))


class ClipboardKeeper:
    """Copies images and keeps the process alive while it owns the clipboard.

    On Wayland the clipboard content is served by the copying process, so it would
    disappear the moment ScreenCatch exits. Holding the application until another
    program takes over the clipboard keeps pasted screenshots working.
    """

    def __init__(self, app: Gtk.Application):
        self._app = app
        self._held = False
        self._clipboard: Gdk.Clipboard | None = None

    def copy(self, surface: cairo.ImageSurface) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("No display available for the clipboard")
        clipboard = display.get_clipboard()
        if self._clipboard is not clipboard:
            self._clipboard = clipboard
            clipboard.connect("notify::local", self._on_local_changed)
        # gdk_clipboard_set_texture() is not introspectable; build the provider from a
        # GdkTexture-typed value so GTK offers every image format it can serialize.
        value = GObject.Value(Gdk.Texture, surface_to_texture(surface))
        clipboard.set_content(Gdk.ContentProvider.new_for_value(value))
        if not self._held:
            self._held = True
            self._app.hold()
            log.debug("Holding application while it owns the clipboard")

    def _on_local_changed(self, clipboard, _pspec):
        if self._held and not clipboard.get_property("local"):
            self._held = False
            log.debug("Clipboard taken over by another client; releasing")
            self._app.release()
