"""
StatusNotifierItem (SNI) tray backend for Linux Wayland hosts.

pystray on Linux prefers AppIndicator (PyGObject + libappindicator). Without those
system bindings it falls back to the legacy XEmbed ``_xorg`` backend, which fails
on pure Wayland compositors (niri + dms/waybar StatusNotifier hosts) with
"Failed to dock icon".

This module implements a minimal SNI + com.canonical.dbusmenu server over the
session bus using jeepney (pure Python D-Bus). No GTK / AppIndicator required.
"""

from __future__ import annotations

import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

from .detect import is_linux

# Soft dependency — only required on Linux tray path
HAVE_JEEPNEY = False
try:
    from jeepney import (  # type: ignore
        DBusAddress,
        HeaderFields,
        Message,
        MessageType,
        new_error,
        new_method_call,
        new_method_return,
        new_signal,
    )
    from jeepney.io.blocking import open_dbus_connection  # type: ignore

    HAVE_JEEPNEY = True
except ImportError:
    pass

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/StatusNotifierMenu"
IFACE_ITEM = "org.kde.StatusNotifierItem"
IFACE_MENU = "com.canonical.dbusmenu"
IFACE_PROPS = "org.freedesktop.DBus.Properties"
IFACE_INTROSPECT = "org.freedesktop.DBus.Introspectable"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
WATCHER_IFACE = "org.kde.StatusNotifierWatcher"

MenuCallback = Callable[[], None]


@dataclass
class TrayMenuEntry:
    """One tray menu row. ``label is None`` means a separator."""

    label: Optional[str]
    callback: Optional[MenuCallback] = None
    default: bool = False


def is_status_notifier_available() -> bool:
    """True when jeepney is importable and we are on Linux."""
    return bool(is_linux() and HAVE_JEEPNEY)


def is_status_notifier_host_registered(timeout: float = 2.0) -> bool:
    """
    Query the session bus for a StatusNotifier host (dms, waybar, etc.).

    Returns False if jeepney/watcher is missing or the call fails.
    """
    if not is_status_notifier_available():
        return False
    try:
        conn = open_dbus_connection(bus="SESSION")
        try:
            props = DBusAddress(
                WATCHER_PATH,
                bus_name=WATCHER_NAME,
                interface=IFACE_PROPS,
            )
            msg = new_method_call(
                props,
                "Get",
                "ss",
                (WATCHER_IFACE, "IsStatusNotifierHostRegistered"),
            )
            reply = conn.send_and_get_reply(msg, timeout=timeout)
            if reply.header.message_type != MessageType.method_return:
                return False
            # body: (('b', True),) variant
            value = reply.body[0]
            if isinstance(value, tuple) and len(value) == 2:
                return bool(value[1])
            return bool(value)
        finally:
            conn.close()
    except Exception:
        return False


def image_to_icon_pixmap(image, sizes: Sequence[int] = (16, 22, 32, 48)) -> list:
    """
    Convert a Pillow image to SNI ``IconPixmap`` value: ``a(iiay)``.

    Pixels are ARGB32 in network (big-endian) byte order per the SNI spec.
    """
    from PIL import Image

    im0 = image.convert("RGBA")
    result = []
    for size in sizes:
        im = im0.copy()
        im.thumbnail((size, size), Image.Resampling.LANCZOS)
        # Ensure exact square canvas for hosts that assume w*h*4 bytes
        if im.size != (size, size):
            canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            ox = (size - im.size[0]) // 2
            oy = (size - im.size[1]) // 2
            canvas.paste(im, (ox, oy))
            im = canvas
        w, h = im.size
        raw = im.tobytes("raw", "RGBA")
        out = bytearray(len(raw))
        # RGBA → ARGB network order
        for i in range(0, len(raw), 4):
            r, g, b, a = raw[i : i + 4]
            out[i : i + 4] = struct.pack(">BBBB", a, r, g, b)
        result.append((w, h, bytes(out)))
    return result


_INTROSPECT_ITEM = f"""<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
"http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node name="{ITEM_PATH}">
  <interface name="{IFACE_ITEM}">
    <method name="ContextMenu">
      <arg direction="in" type="i" name="x"/>
      <arg direction="in" type="i" name="y"/>
    </method>
    <method name="Activate">
      <arg direction="in" type="i" name="x"/>
      <arg direction="in" type="i" name="y"/>
    </method>
    <method name="SecondaryActivate">
      <arg direction="in" type="i" name="x"/>
      <arg direction="in" type="i" name="y"/>
    </method>
    <method name="Scroll">
      <arg direction="in" type="i" name="delta"/>
      <arg direction="in" type="s" name="orientation"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg type="s" name="status"/></signal>
    <signal name="NewMenu"/>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
  </interface>
  <interface name="{IFACE_PROPS}">
    <method name="Get">
      <arg type="s" direction="in" name="interface_name"/>
      <arg type="s" direction="in" name="property_name"/>
      <arg type="v" direction="out" name="value"/>
    </method>
    <method name="GetAll">
      <arg type="s" direction="in" name="interface_name"/>
      <arg type="a{{sv}}" direction="out" name="properties"/>
    </method>
    <method name="Set">
      <arg type="s" direction="in" name="interface_name"/>
      <arg type="s" direction="in" name="property_name"/>
      <arg type="v" direction="in" name="value"/>
    </method>
    <signal name="PropertiesChanged">
      <arg type="s" name="interface_name"/>
      <arg type="a{{sv}}" name="changed_properties"/>
      <arg type="as" name="invalidated_properties"/>
    </signal>
  </interface>
  <interface name="{IFACE_INTROSPECT}">
    <method name="Introspect">
      <arg type="s" direction="out" name="xml_data"/>
    </method>
  </interface>
</node>
"""

_INTROSPECT_MENU = f"""<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
"http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node name="{MENU_PATH}">
  <interface name="{IFACE_MENU}">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{{sv}}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{{sv}})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{{sv}})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/>
      <arg type="i" name="parent"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg type="i" name="id"/>
      <arg type="u" name="timestamp"/>
    </signal>
  </interface>
  <interface name="{IFACE_PROPS}">
    <method name="Get">
      <arg type="s" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="v" direction="out"/>
    </method>
    <method name="GetAll">
      <arg type="s" direction="in"/>
      <arg type="a{{sv}}" direction="out"/>
    </method>
    <method name="Set">
      <arg type="s" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="v" direction="in"/>
    </method>
  </interface>
  <interface name="{IFACE_INTROSPECT}">
    <method name="Introspect">
      <arg type="s" direction="out" name="xml_data"/>
    </method>
  </interface>
</node>
"""


class StatusNotifierIcon:
    """
    Blocking StatusNotifierItem tray icon.

    ``run()`` registers with the watcher and serves D-Bus requests until
    ``stop()`` is called (typically from a Quit menu action).
    """

    def __init__(
        self,
        image,
        title: str = "AIPromptBridge",
        app_id: str = "aipromptbridge",
        menu: Optional[Sequence[TrayMenuEntry]] = None,
        on_activate: Optional[MenuCallback] = None,
    ):
        if not HAVE_JEEPNEY:
            raise RuntimeError("jeepney is required for StatusNotifier tray support")

        self.title = title
        self.app_id = app_id
        self.icon_pixmap = image_to_icon_pixmap(image)
        self._menu_entries: List[TrayMenuEntry] = list(menu or [])
        self._on_activate = on_activate
        self._layout_revision = 1
        self._conn = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # id 0 = root; items start at 1
        self._id_to_callback: dict[int, MenuCallback] = {}
        self._rebuild_id_map()

    def _rebuild_id_map(self) -> None:
        self._id_to_callback = {}
        for idx, entry in enumerate(self._menu_entries, start=1):
            if entry.callback is not None and entry.label is not None:
                self._id_to_callback[idx] = entry.callback
        if self._on_activate is None:
            for entry in self._menu_entries:
                if entry.default and entry.callback is not None:
                    self._on_activate = entry.callback
                    break

    def update_menu(self, menu: Sequence[TrayMenuEntry]) -> None:
        """Replace menu entries and notify hosts (LayoutUpdated)."""
        with self._lock:
            self._menu_entries = list(menu)
            self._layout_revision += 1
            self._rebuild_id_map()
            rev = self._layout_revision
        self._emit_menu_layout_updated(rev)

    def stop(self) -> None:
        """Request the run loop to exit."""
        self._stop.set()

    # ── D-Bus property helpers ────────────────────────────────────────────

    def _item_props(self) -> dict:
        return {
            "Category": ("s", "ApplicationStatus"),
            "Id": ("s", self.app_id),
            "Title": ("s", self.title),
            "Status": ("s", "Active"),
            "WindowId": ("i", 0),
            "IconName": ("s", ""),
            "IconPixmap": ("a(iiay)", self.icon_pixmap),
            "OverlayIconName": ("s", ""),
            "OverlayIconPixmap": ("a(iiay)", []),
            "AttentionIconName": ("s", ""),
            "AttentionIconPixmap": ("a(iiay)", []),
            "AttentionMovieName": ("s", ""),
            "ToolTip": ("(sa(iiay)ss)", ("", self.icon_pixmap, self.title, "")),
            "ItemIsMenu": ("b", True),
            "Menu": ("o", MENU_PATH),
            "IconThemePath": ("s", ""),
        }

    def _menu_props(self) -> dict:
        return {
            "Version": ("u", 4),
            "TextDirection": ("s", "ltr"),
            "Status": ("s", "normal"),
            "IconThemePath": ("as", []),
        }

    def _entry_props(self, entry: TrayMenuEntry) -> dict:
        if entry.label is None:
            return {"type": ("s", "separator")}
        return {
            "label": ("s", entry.label),
            "enabled": ("b", True),
            "visible": ("b", True),
        }

    def _build_layout(self) -> Tuple[int, tuple]:
        with self._lock:
            rev = self._layout_revision
            entries = list(self._menu_entries)
        children = []
        for idx, entry in enumerate(entries, start=1):
            children.append(("(ia{sv}av)", (idx, self._entry_props(entry), [])))
        root = (0, {"children-display": ("s", "submenu")}, children)
        return rev, root

    # ── message helpers ───────────────────────────────────────────────────

    def _reply(self, request: Message, signature: str, body) -> None:
        assert self._conn is not None
        self._conn.send(new_method_return(request, signature, body))

    def _error(self, request: Message, name: str, message: str = "") -> None:
        assert self._conn is not None
        self._conn.send(new_error(request, name, "s", (message,)))

    def _emit_item_signal(self, member: str, signature: str = "", body=()) -> None:
        if self._conn is None:
            return
        try:
            emitter = DBusAddress(ITEM_PATH, interface=IFACE_ITEM)
            self._conn.send(new_signal(emitter, member, signature or None, body))
        except Exception:
            pass

    def _emit_menu_layout_updated(self, revision: int) -> None:
        if self._conn is None:
            return
        try:
            emitter = DBusAddress(MENU_PATH, interface=IFACE_MENU)
            self._conn.send(new_signal(emitter, "LayoutUpdated", "ui", (revision, 0)))
        except Exception:
            pass

    def _run_callback(self, callback: Optional[MenuCallback]) -> None:
        if callback is None:
            return

        def _safe():
            try:
                callback()
            except Exception as e:
                print(f"[Warning] Tray menu action failed: {e}")

        threading.Thread(target=_safe, daemon=True).start()

    # ── request dispatch ──────────────────────────────────────────────────

    def _handle(self, msg: Message) -> None:
        if msg.header.message_type != MessageType.method_call:
            return

        path = msg.header.fields.get(HeaderFields.path)
        member = msg.header.fields.get(HeaderFields.member)

        try:
            if member == "Introspect":
                if path == ITEM_PATH:
                    self._reply(msg, "s", (_INTROSPECT_ITEM,))
                elif path == MENU_PATH:
                    self._reply(msg, "s", (_INTROSPECT_MENU,))
                else:
                    self._reply(msg, "s", ("<node/>",))
                return

            if path == ITEM_PATH:
                self._handle_item(msg, member)
                return
            if path == MENU_PATH:
                self._handle_menu(msg, member)
                return

            self._error(msg, "org.freedesktop.DBus.Error.UnknownObject", str(path or ""))
        except Exception as e:
            try:
                self._error(msg, "org.freedesktop.DBus.Error.Failed", str(e))
            except Exception:
                pass

    def _handle_item(self, msg: Message, member: Optional[str]) -> None:
        if member == "Get":
            _iface, prop = msg.body
            props = self._item_props()
            if prop not in props:
                self._error(msg, "org.freedesktop.DBus.Error.UnknownProperty", prop)
                return
            sig, val = props[prop]
            self._reply(msg, "v", ((sig, val),))
            return
        if member == "GetAll":
            self._reply(msg, "a{sv}", (self._item_props(),))
            return
        if member == "Set":
            self._error(msg, "org.freedesktop.DBus.Error.PropertyReadOnly")
            return
        if member == "Activate":
            self._run_callback(self._on_activate)
            self._reply(msg, "", ())
            return
        if member in ("SecondaryActivate", "ContextMenu", "Scroll"):
            # Hosts with ItemIsMenu=true typically open dbusmenu themselves.
            self._reply(msg, "", ())
            return
        self._error(msg, "org.freedesktop.DBus.Error.UnknownMethod", str(member or ""))

    def _handle_menu(self, msg: Message, member: Optional[str]) -> None:
        if member == "Get":
            _iface, prop = msg.body
            props = self._menu_props()
            if prop not in props:
                self._error(msg, "org.freedesktop.DBus.Error.UnknownProperty", prop)
                return
            sig, val = props[prop]
            self._reply(msg, "v", ((sig, val),))
            return
        if member == "GetAll":
            self._reply(msg, "a{sv}", (self._menu_props(),))
            return
        if member == "GetLayout":
            rev, root = self._build_layout()
            self._reply(msg, "u(ia{sv}av)", (rev, root))
            return
        if member == "GetGroupProperties":
            ids, _prop_names = msg.body
            result = []
            with self._lock:
                entries = list(self._menu_entries)
            for i in ids:
                if i == 0:
                    result.append((0, {"children-display": ("s", "submenu")}))
                elif 1 <= i <= len(entries):
                    result.append((i, self._entry_props(entries[i - 1])))
            self._reply(msg, "a(ia{sv})", (result,))
            return
        if member == "GetProperty":
            i, name = msg.body
            with self._lock:
                entries = list(self._menu_entries)
            if 1 <= i <= len(entries):
                props = self._entry_props(entries[i - 1])
                if name in props:
                    sig, val = props[name]
                    self._reply(msg, "v", ((sig, val),))
                    return
            self._reply(msg, "v", (("s", ""),))
            return
        if member == "Event":
            item_id, event_id, _data, _timestamp = msg.body
            if event_id == "clicked":
                with self._lock:
                    cb = self._id_to_callback.get(int(item_id))
                self._run_callback(cb)
            self._reply(msg, "", ())
            return
        if member == "EventGroup":
            self._reply(msg, "ai", ([],))
            return
        if member == "AboutToShow":
            # False = layout still valid
            self._reply(msg, "b", (False,))
            return
        if member == "AboutToShowGroup":
            self._reply(msg, "aiai", ([], []))
            return
        if member == "Set":
            self._error(msg, "org.freedesktop.DBus.Error.PropertyReadOnly")
            return
        self._error(msg, "org.freedesktop.DBus.Error.UnknownMethod", str(member or ""))

    # ── main loop ─────────────────────────────────────────────────────────

    def run(self) -> None:
        """
        Register with StatusNotifierWatcher and serve until ``stop()``.

        Raises on connection/registration failure so callers can fall back.
        """
        self._conn = open_dbus_connection(bus="SESSION")
        unique = self._conn.unique_name

        watcher = DBusAddress(WATCHER_PATH, bus_name=WATCHER_NAME, interface=WATCHER_IFACE)
        # Prefer unique name (KDE/freedesktop convention → ":1.x/StatusNotifierItem")
        registered = False
        last_error: Optional[Exception] = None
        for service in (unique, f"{unique}{ITEM_PATH}", ITEM_PATH):
            try:
                reply = self._conn.send_and_get_reply(
                    new_method_call(watcher, "RegisterStatusNotifierItem", "s", (service,)),
                    timeout=5,
                )
                if reply.header.message_type == MessageType.method_return:
                    registered = True
                    break
                last_error = RuntimeError(f"RegisterStatusNotifierItem rejected for {service!r}")
            except Exception as e:
                last_error = e

        if not registered:
            self._conn.close()
            self._conn = None
            raise RuntimeError(f"Failed to register StatusNotifierItem with {WATCHER_NAME}: {last_error}")

        # Nudge hosts that only refresh on signals
        self._emit_item_signal("NewStatus", "s", ("Active",))
        self._emit_item_signal("NewIcon")
        self._emit_item_signal("NewTitle")
        self._emit_item_signal("NewMenu")

        try:
            while not self._stop.is_set():
                try:
                    msg = self._conn.receive(timeout=0.5)
                except TimeoutError:
                    continue
                except Exception:
                    if self._stop.is_set():
                        break
                    raise
                self._handle(msg)
        finally:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
