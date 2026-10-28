"""Screen capture through the XDG desktop portal.

The portal is the only way to grab the screen on Wayland, and it works on X11 too.
ScreenCatch asks for a non-interactive full-desktop screenshot and does the region
selection itself, so the user gets a single, consistent flow.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from collections.abc import Callable

import cairo
from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
SCREENSHOT_INTERFACE = "org.freedesktop.portal.Screenshot"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"

PERMISSION_STORE_BUS_NAME = "org.freedesktop.impl.portal.PermissionStore"
PERMISSION_STORE_PATH = "/org/freedesktop/impl/portal/PermissionStore"
PERMISSION_STORE_INTERFACE = "org.freedesktop.impl.portal.PermissionStore"
# Table and entry the portal uses for non-interactive screenshot permission.
SCREENSHOT_PERMISSION = "screenshot"

RESPONSE_SUCCESS = 0
RESPONSE_CANCELLED = 1


class CaptureError(Exception):
    """The screenshot could not be taken."""


class CaptureCancelled(CaptureError):
    """The user (or a permission prompt) cancelled the screenshot."""


class CapturePermissionError(CaptureError):
    """The portal refused the screenshot, almost always because permission is missing.

    The desktop asks for permission the first time an identified app captures the
    screen, but only while that app has keyboard focus.
    """


def request_object_path(unique_name: str, token: str) -> str:
    """Object path the portal will use for a request made with ``token``."""
    sender = unique_name.lstrip(":").replace(".", "_")
    return f"{PORTAL_OBJECT_PATH}/request/{sender}/{token}"


def interpret_response(code: int, results: dict) -> str:
    """Return the local path of the screenshot or raise :class:`CaptureError`."""
    if code == RESPONSE_SUCCESS:
        uri = results.get("uri")
        if not uri:
            raise CaptureError("The screenshot portal did not return an image.")
        path = Gio.File.new_for_uri(uri).get_path()
        if not path:
            raise CaptureError(f"The screenshot portal returned an unsupported location: {uri}")
        return path
    if code == RESPONSE_CANCELLED:
        raise CaptureCancelled("The screenshot was cancelled.")
    raise CapturePermissionError("ScreenCatch is not allowed to capture the screen yet.")


def permission_from_lookup(permissions: dict, app_id: str) -> str | None:
    """Pick ``app_id``'s value (``"yes"``/``"no"``) out of a PermissionStore lookup."""
    values = permissions.get(app_id) or []
    return values[0] if values else None


def load_png(path: str) -> cairo.ImageSurface:
    try:
        return cairo.ImageSurface.create_from_png(path)
    except (cairo.Error, MemoryError, OSError) as exc:
        raise CaptureError(f"Could not read the captured image: {exc}") from exc


def discard_portal_file(path: str, requested_at: float) -> None:
    """Delete the temporary file the portal wrote for us.

    GNOME's portal stores the capture in the user's Pictures folder. ScreenCatch
    saves its own (annotated) copy, so the raw file would only be clutter. Only a
    file created after our request is removed, never a pre-existing one.
    """
    try:
        if os.stat(path).st_mtime + 2 >= requested_at:
            os.unlink(path)
    except OSError as exc:
        log.warning("Could not remove portal file %s: %s", path, exc)


class ScreenshotPortal:
    def __init__(self):
        self._bus: Gio.DBusConnection | None = None

    def _connection(self) -> Gio.DBusConnection:
        if self._bus is None:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return self._bus

    def get_permission(self, app_id: str) -> str | None:
        """Return the stored screenshot permission for ``app_id``, if any."""
        try:
            result = self._connection().call_sync(
                PERMISSION_STORE_BUS_NAME,
                PERMISSION_STORE_PATH,
                PERMISSION_STORE_INTERFACE,
                "Lookup",
                GLib.Variant("(ss)", (SCREENSHOT_PERMISSION, SCREENSHOT_PERMISSION)),
                GLib.VariantType("(a{sas}v)"),
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            )
        except GLib.Error as exc:
            log.debug("Permission lookup failed: %s", exc.message)
            return None
        permissions, _data = result.unpack()
        return permission_from_lookup(permissions, app_id)

    def reset_permission(self, app_id: str) -> None:
        """Forget an earlier "Deny" so the desktop asks again on the next capture."""
        try:
            self._connection().call_sync(
                PERMISSION_STORE_BUS_NAME,
                PERMISSION_STORE_PATH,
                PERMISSION_STORE_INTERFACE,
                "DeletePermission",
                GLib.Variant("(sss)", (SCREENSHOT_PERMISSION, SCREENSHOT_PERMISSION, app_id)),
                None,
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            )
        except GLib.Error as exc:
            log.debug("Permission reset failed: %s", exc.message)

    def capture(self, callback: Callable[[cairo.ImageSurface | None, CaptureError | None], None]) -> None:
        """Capture the whole desktop and call ``callback(surface, error)``."""
        try:
            bus = self._connection()
        except GLib.Error as exc:
            GLib.idle_add(callback, None, CaptureError(f"Cannot connect to the session bus: {exc.message}"))
            return

        token = "screencatch_" + secrets.token_hex(8)
        handle = request_object_path(bus.get_unique_name(), token)
        requested_at = time.time()
        state = {"subscription": 0, "done": False}

        def finish(surface, error):
            if state["done"]:
                return
            state["done"] = True
            if state["subscription"]:
                bus.signal_unsubscribe(state["subscription"])
                state["subscription"] = 0
            callback(surface, error)

        def on_response(_conn, _sender, _path, _iface, _signal, params):
            code, results = params.unpack()
            log.debug("Portal response %s: %s", code, results)
            try:
                path = interpret_response(code, results)
            except CaptureError as exc:
                finish(None, exc)
                return
            try:
                surface = load_png(path)
            except CaptureError as exc:
                finish(None, exc)
                return
            finally:
                discard_portal_file(path, requested_at)
            finish(surface, None)

        # Subscribe before calling so a fast response cannot be missed.
        state["subscription"] = bus.signal_subscribe(
            PORTAL_BUS_NAME,
            REQUEST_INTERFACE,
            "Response",
            handle,
            None,
            Gio.DBusSignalFlags.NO_MATCH_RULE,
            on_response,
        )

        options = {
            "handle_token": GLib.Variant("s", token),
            "interactive": GLib.Variant("b", False),
            "modal": GLib.Variant("b", False),
        }

        def on_called(conn, result):
            try:
                conn.call_finish(result)
            except GLib.Error as exc:
                log.debug("Portal call failed: %s", exc.message)
                missing = ("ServiceUnknown", "UnknownMethod", "UnknownInterface")
                if any(name in exc.message for name in missing):
                    message = (
                        "No screenshot portal is available. Install xdg-desktop-portal "
                        "and a backend such as xdg-desktop-portal-gnome."
                    )
                else:
                    message = f"The screenshot portal failed: {exc.message}"
                finish(None, CaptureError(message))

        bus.call(
            PORTAL_BUS_NAME,
            PORTAL_OBJECT_PATH,
            SCREENSHOT_INTERFACE,
            "Screenshot",
            GLib.Variant("(sa{sv})", ("", options)),
            GLib.VariantType("(o)"),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            on_called,
        )
