"""Turning surfaces into files: naming, saving and PNG encoding (no GTK needed)."""

from __future__ import annotations

import datetime
import io
import os
import tempfile

import cairo
from gi.repository import GLib

DEFAULT_TEMPLATE = "Screenshot_%Y-%m-%d_%H-%M-%S"


def surface_to_png_bytes(surface: cairo.ImageSurface) -> bytes:
    buffer = io.BytesIO()
    surface.write_to_png(buffer)
    return buffer.getvalue()


def expand_template(template: str, when: datetime.datetime | None = None) -> str:
    """Expand strftime codes in ``template`` and return a safe ``.png`` file name."""
    when = when or datetime.datetime.now()
    try:
        name = when.strftime(template or DEFAULT_TEMPLATE)
    except ValueError:
        name = when.strftime(DEFAULT_TEMPLATE)
    name = name.replace("/", "-").replace("\0", "").strip().lstrip(".")
    if not name:
        name = when.strftime(DEFAULT_TEMPLATE)
    if not name.lower().endswith(".png"):
        name += ".png"
    return name


def unique_path(directory: str, filename: str) -> str:
    """Return a path in ``directory`` that does not exist yet (``name-1.png`` ...)."""
    stem, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    counter = 1
    while os.path.lexists(candidate):
        candidate = os.path.join(directory, f"{stem}-{counter}{ext}")
        counter += 1
    return candidate


def default_save_dir() -> str:
    pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
    if not pictures:
        pictures = os.path.join(GLib.get_home_dir(), "Pictures")
    return os.path.join(pictures, "Screenshots")


def resolve_save_dir(configured: str) -> str:
    return os.path.expanduser(configured) if configured else default_save_dir()


def save_surface(surface: cairo.ImageSurface, path: str) -> str:
    """Write ``surface`` as PNG to ``path`` atomically and return the path."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".screencatch-", suffix=".png", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            surface.write_to_png(handle)
        os.chmod(tmp_path, 0o666 & ~_current_umask())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise
    return path


def _current_umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


def save_to_folder(surface: cairo.ImageSurface, directory: str, template: str) -> str:
    """Save under a fresh, non-conflicting name generated from ``template``."""
    os.makedirs(directory, exist_ok=True)
    return save_surface(surface, unique_path(directory, expand_template(template)))


def crop_surface(surface: cairo.ImageSurface, x: int, y: int, w: int, h: int) -> cairo.ImageSurface:
    result = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(result)
    cr.set_source_surface(surface, -x, -y)
    cr.paint()
    result.flush()
    return result
