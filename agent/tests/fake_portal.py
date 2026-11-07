"""A stand-in xdg-desktop-portal for tests, run with the system python3 on a
private D-Bus bus (never the real session bus).

It speaks the real protocol: methods return a Request object path built from
the caller's handle_token, and the answer arrives later as that Request's
Response signal - which is exactly the part of the Wayland path that had
never been exercised. OpenPipeWireRemote hands back a real file descriptor.
Every call is appended to $FAKE_PORTAL_LOG as one JSON line.

Knobs (environment):
  FAKE_PORTAL_DENY=<Method>   answer that method with response 1 (cancelled)
  FAKE_PORTAL_NO_REMOTE=1     offer ScreenCast only, like xdg-desktop-portal-wlr
"""
import json
import os
import sys

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

PATH = "/org/freedesktop/portal/desktop"
LOG = os.environ["FAKE_PORTAL_LOG"]
DENY = os.environ.get("FAKE_PORTAL_DENY", "")
NO_REMOTE = os.environ.get("FAKE_PORTAL_NO_REMOTE") == "1"
NODE = 47

XML = """
<node>
  <interface name="org.freedesktop.portal.ScreenCast">
    <method name="CreateSession"><arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method>
    <method name="SelectSources"><arg type="o" direction="in"/><arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method>
    <method name="Start"><arg type="o" direction="in"/><arg type="s" direction="in"/><arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method>
    <method name="OpenPipeWireRemote"><arg type="o" direction="in"/><arg type="a{sv}" direction="in"/><arg type="h" direction="out"/></method>
    <property name="version" type="u" access="read"/>
    <property name="AvailableCursorModes" type="u" access="read"/>
  </interface>
  <interface name="org.freedesktop.portal.RemoteDesktop">
    <method name="CreateSession"><arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method>
    <method name="SelectDevices"><arg type="o" direction="in"/><arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method>
    <method name="Start"><arg type="o" direction="in"/><arg type="s" direction="in"/><arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method>
    <method name="NotifyPointerMotionAbsolute"><arg type="o" direction="in"/><arg type="a{sv}" direction="in"/><arg type="u" direction="in"/><arg type="d" direction="in"/><arg type="d" direction="in"/></method>
    <method name="NotifyPointerButton"><arg type="o" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="in"/></method>
    <method name="NotifyPointerAxisDiscrete"><arg type="o" direction="in"/><arg type="a{sv}" direction="in"/><arg type="u" direction="in"/><arg type="i" direction="in"/></method>
    <method name="NotifyKeyboardKeysym"><arg type="o" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="in"/></method>
    <property name="version" type="u" access="read"/>
  </interface>
</node>
"""
SESSION_XML = """
<node><interface name="org.freedesktop.portal.Session">
  <method name="Close"/>
</interface></node>
"""

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
node_info = Gio.DBusNodeInfo.new_for_xml(XML)
session_info = Gio.DBusNodeInfo.new_for_xml(SESSION_XML).interfaces[0]
sessions = {}
pipes = []


def record(entry: dict) -> None:
    with open(LOG, "a") as handle:
        handle.write(json.dumps(entry) + "\n")


def plain(value):
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def answer(sender: str, token: str, method: str, results: dict) -> str:
    """Return a Request path now and emit its Response a moment later."""
    path = f"{PATH}/request/{sender.lstrip(':').replace('.', '_')}/{token}"
    code = 1 if method == DENY else 0

    def emit():
        bus.emit_signal(sender, path, "org.freedesktop.portal.Request", "Response",
                        GLib.Variant("(ua{sv})", (code, results if code == 0 else {})))
        return False

    GLib.timeout_add(30, emit)
    return path


def session_call(_c, _sender, path, _iface, method, _params, invocation):
    record({"iface": "Session", "method": method, "path": path})
    invocation.return_value(None)


def method_call(_c, sender, _path, iface, method, params, invocation):
    args = params.unpack()
    short = iface.rsplit(".", 1)[-1]
    record({"iface": short, "method": method, "args": plain(args)})
    if method == "CreateSession":
        options = args[0]
        handle = f"{PATH}/session/{sender.lstrip(':').replace('.', '_')}/{options['session_handle_token']}"
        sessions[handle] = bus.register_object(handle, session_info, session_call, None, None)
        path = answer(sender, options.get("handle_token", "missing"), method,
                      {"session_handle": GLib.Variant("s", handle)})
        invocation.return_value(GLib.Variant("(o)", (path,)))
    elif method in ("SelectSources", "SelectDevices"):
        options = args[1]
        path = answer(sender, options.get("handle_token", "missing"), method, {})
        invocation.return_value(GLib.Variant("(o)", (path,)))
    elif method == "Start":
        options = args[2]
        stream = GLib.Variant("a(ua{sv})", [(NODE, {
            "size": GLib.Variant("(ii)", (1366, 768)),
            "position": GLib.Variant("(ii)", (1920, 0)),
        })])
        results = {"streams": stream, "restore_token": GLib.Variant("s", "restore-abc")}
        if short == "RemoteDesktop":
            results["devices"] = GLib.Variant("u", 3)
        path = answer(sender, options.get("handle_token", "missing"), method, results)
        invocation.return_value(GLib.Variant("(o)", (path,)))
    elif method == "OpenPipeWireRemote":
        read_end, write_end = os.pipe()
        pipes.append(write_end)
        fds = Gio.UnixFDList.new()
        fds.append(read_end)
        os.close(read_end)
        invocation.return_value_with_unix_fd_list(GLib.Variant("(h)", (0,)), fds)
    else:  # Notify*
        invocation.return_value(None)


def get_property(_c, _sender, _path, iface, name):
    if name == "AvailableCursorModes":
        return GLib.Variant("u", 7)
    return GLib.Variant("u", 2 if iface.endswith("RemoteDesktop") else 5)


for info in node_info.interfaces:
    if NO_REMOTE and info.name.endswith("RemoteDesktop"):
        continue
    bus.register_object(PATH, info, method_call, get_property, None)


def acquired(*_args):
    print("ready", flush=True)


Gio.bus_own_name_on_connection(bus, "org.freedesktop.portal.Desktop",
                               Gio.BusNameOwnerFlags.NONE, acquired, lambda *a: sys.exit(1))
GLib.MainLoop().run()
