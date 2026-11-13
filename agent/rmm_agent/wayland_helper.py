"""Wayland screen share and input, run under the machine's OWN python3.

Why a separate process: a Wayland desktop only lets an app read the screen or
inject input through the XDG desktop portal, reached over D-Bus, with frames
delivered over PipeWire. That needs PyGObject, GLib, GStreamer and PipeWire -
and they have to match the libraries and the PipeWire daemon actually running
on *this* machine. A PyInstaller-built agent carries the build machine's
copies instead (and in practice CI could not even build PyGObject, so it
carried none), which is why Wayland never worked from an installed agent.
The distribution's own python3 + python3-gi + gstreamer pipewire plugin
always match the machine, on any distro - the .deb depends on them and
installers/linux/install.sh installs the same set elsewhere.

So the agent starts this file with the system python3 and talks to it over
stdin/stdout. It must therefore never import anything from rmm_agent.

Protocol
  agent -> helper : one JSON object per line.
      first line   {"want_input": bool, "persist_mode": 0|1|2, "restore_token": str|null}
      afterwards   {"op": "grab"} | {"op": "motion", "x": f, "y": f}
                   {"op": "button", "button": int, "pressed": bool}
                   {"op": "axis", "steps": int} | {"op": "key", "keysym": int, "pressed": bool}
                   {"op": "close"}
  helper -> agent : 1 byte kind + u32 little-endian length + payload.
      b"J" JSON   {"event": "ready", "monitors": [...], "input": bool, "restore_token": str|null}
                  {"event": "error", "detail": str, "denied": bool}
      b"F" frame  u32 width, u32 height, then a JPEG of the frame. The frame is
                  JPEG-encoded in the helper's GStreamer pipeline, so ~100 KB
                  crosses the pipe per frame instead of a multi-MB raw frame;
                  the agent decodes it once (capture.py) and feeds its existing
                  tile encoder. (Was packed RGB before 2026-11-11.)
      b"S" same   no new frame since the last one (a still screen)
      b"E" error  utf-8 text: the stream is gone
  Only "grab" is answered, so input ops never desynchronise the stream. Frames
  are pulled inline on the main reader thread (the one that owns the pipeline);
  input is injected on its own thread (see main) so a pointer move is not stuck
  behind a frame being pulled.

`python3 wayland_helper.py --check` prints one JSON line describing what this
machine can do, for `rmm-agent status` and CI.
"""
import json
import os
import queue
import struct
import sys
import threading
import time

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REQUEST_IFACE = "org.freedesktop.portal.Request"
SESSION_IFACE = "org.freedesktop.portal.Session"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
REMOTE_DESKTOP_IFACE = "org.freedesktop.portal.RemoteDesktop"

SOURCE_TYPE_MONITOR = 1
CURSOR_HIDDEN = 1
CURSOR_EMBEDDED = 2
DEVICE_KEYBOARD = 1
DEVICE_POINTER = 2

# The person answering the compositor's dialog is the slow part.
REQUEST_TIMEOUT = 180.0
FIRST_FRAME_TIMEOUT = 8.0

_out = sys.stdout.buffer


def log(message: str) -> None:
    sys.stderr.write(f"{message}\n")
    sys.stderr.flush()


def send(kind: bytes, payload: bytes) -> None:
    _out.write(kind + struct.pack("<I", len(payload)) + payload)
    _out.flush()


def send_json(obj: dict) -> None:
    send(b"J", json.dumps(obj).encode())


class Denied(Exception):
    """The person (or the compositor) refused the share."""


class Portal:
    def __init__(self, Gio, GLib) -> None:
        self.Gio = Gio
        self.GLib = GLib
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.sender = self.bus.get_unique_name().lstrip(":").replace(".", "_")
        self.counter = 0
        self.session = None
        self.node = None

    # ------------------------------------------------------------ plumbing

    def version(self, iface: str) -> int:
        try:
            reply = self.bus.call_sync(
                PORTAL_BUS, PORTAL_PATH, "org.freedesktop.DBus.Properties", "Get",
                self.GLib.Variant("(ss)", (iface, "version")),
                self.GLib.VariantType.new("(v)"), self.Gio.DBusCallFlags.NONE, 5000, None,
            )
            return int(reply.unpack()[0])
        except Exception:
            return 0

    def prop(self, iface: str, name: str, default):
        try:
            reply = self.bus.call_sync(
                PORTAL_BUS, PORTAL_PATH, "org.freedesktop.DBus.Properties", "Get",
                self.GLib.Variant("(ss)", (iface, name)),
                self.GLib.VariantType.new("(v)"), self.Gio.DBusCallFlags.NONE, 5000, None,
            )
            return reply.unpack()[0]
        except Exception:
            return default

    def request(self, iface: str, method: str, signature: str, args: tuple, options: dict) -> dict:
        """Call a portal method that answers through a Request object, and
        wait for its Response. The handle_token makes the Request's path
        predictable, so the subscription exists before the call is made and
        a fast answer cannot be missed. Signals are delivered on this
        thread's default main context, which is the one iterated below."""
        GLib = self.GLib
        self.counter += 1
        token = f"rmm{os.getpid()}_{self.counter}"
        options = dict(options)
        options["handle_token"] = GLib.Variant("s", token)
        path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{token}"
        box: dict = {}

        def on_response(_c, _s, _p, _i, _n, parameters) -> None:
            code, results = parameters.unpack()
            box["code"] = code
            box["results"] = results

        sub = self.bus.signal_subscribe(
            None, REQUEST_IFACE, "Response", path, None,
            self.Gio.DBusSignalFlags.NONE, on_response,
        )
        try:
            reply = self.bus.call_sync(
                PORTAL_BUS, PORTAL_PATH, iface, method,
                GLib.Variant(signature, args + (options,)),
                GLib.VariantType.new("(o)"), self.Gio.DBusCallFlags.NONE, -1, None,
            )
            actual = reply.unpack()[0]
            if actual != path:
                # Only a portal too old to honour handle_token does this.
                self.bus.signal_unsubscribe(sub)
                sub = self.bus.signal_subscribe(
                    None, REQUEST_IFACE, "Response", actual, None,
                    self.Gio.DBusSignalFlags.NONE, on_response,
                )
            context = GLib.MainContext.default()
            deadline = time.monotonic() + REQUEST_TIMEOUT
            while "code" not in box:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"no answer to {method} within {REQUEST_TIMEOUT:.0f}s")
                if not context.iteration(False):
                    time.sleep(0.02)
        finally:
            self.bus.signal_unsubscribe(sub)
        if box["code"] == 1:
            raise Denied(f"{method} was cancelled at the compositor's dialog")
        if box["code"] != 0:
            raise RuntimeError(f"{method} failed (portal response {box['code']})")
        return box.get("results") or {}

    # ------------------------------------------------------------ handshake

    def start(self, want_input: bool, persist_mode: int, restore_token) -> dict:
        GLib = self.GLib
        iface = REMOTE_DESKTOP_IFACE if want_input else SCREENCAST_IFACE
        self.counter += 1
        token = f"rmmsession{os.getpid()}_{self.counter}"
        created = self.request(
            iface, "CreateSession", "(a{sv})", (),
            {"session_handle_token": GLib.Variant("s", token)},
        )
        self.session = created.get("session_handle")
        if not self.session:
            raise RuntimeError("CreateSession returned no session handle")

        persist = {}
        if persist_mode:
            persist["persist_mode"] = GLib.Variant("u", int(persist_mode))
            if restore_token:
                persist["restore_token"] = GLib.Variant("s", str(restore_token))

        if want_input:
            devices = {"types": GLib.Variant("u", DEVICE_KEYBOARD | DEVICE_POINTER)}
            # Remote-desktop sessions persist through SelectDevices (v2+).
            if persist and self.version(REMOTE_DESKTOP_IFACE) >= 2:
                devices.update(persist)
            self.request(REMOTE_DESKTOP_IFACE, "SelectDevices", "(oa{sv})", (self.session,), devices)

        cursor_modes = int(self.prop(SCREENCAST_IFACE, "AvailableCursorModes", 0) or 0)
        sources = {
            "types": GLib.Variant("u", SOURCE_TYPE_MONITOR),
            "multiple": GLib.Variant("b", False),
        }
        if cursor_modes & CURSOR_EMBEDDED:
            sources["cursor_mode"] = GLib.Variant("u", CURSOR_EMBEDDED)
            cursor = "embedded"
        elif cursor_modes & CURSOR_HIDDEN:
            sources["cursor_mode"] = GLib.Variant("u", CURSOR_HIDDEN)
            cursor = "hidden"
        else:
            cursor = "none"
        # Which cursor mode we got decides whether a pointer move alone produces
        # a new frame: only "embedded" paints the cursor into the capture, so
        # with anything else a mouse move changes nothing on screen and sends no
        # frame. Logged so a "frozen unless content changes" report is readable.
        log(f"cursor mode: {cursor} (available bitmask {cursor_modes})")
        # A screen-cast-only session persists through SelectSources (v4+).
        if persist and not want_input and self.version(SCREENCAST_IFACE) >= 4:
            sources.update(persist)
        self.request(SCREENCAST_IFACE, "SelectSources", "(oa{sv})", (self.session,), sources)

        started = self.request(iface, "Start", "(osa{sv})", (self.session, ""), {})
        streams = started.get("streams") or []
        if not streams:
            raise RuntimeError("Start returned no screen stream")
        node, props = streams[0]
        self.node = int(node)
        width, height = props.get("size") or (0, 0)
        left, top = props.get("position") or (0, 0)
        granted = int(started.get("devices", 0) or 0)

        reply, fds = self.bus.call_with_unix_fd_list_sync(
            PORTAL_BUS, PORTAL_PATH, SCREENCAST_IFACE, "OpenPipeWireRemote",
            GLib.Variant("(oa{sv})", (self.session, {})),
            GLib.VariantType.new("(h)"), self.Gio.DBusCallFlags.NONE, -1, None, None,
        )
        fd = fds.get(reply.unpack()[0])
        return {
            "fd": fd,
            "width": int(width), "height": int(height),
            "left": int(left), "top": int(top),
            "input": bool(want_input and granted & DEVICE_POINTER),
            "restore_token": started.get("restore_token"),
        }

    # ------------------------------------------------------------ input

    def notify(self, method: str, signature: str, args: tuple) -> None:
        try:
            self.bus.call_sync(
                PORTAL_BUS, PORTAL_PATH, REMOTE_DESKTOP_IFACE, method,
                self.GLib.Variant(signature, (self.session, {}) + args),
                None, self.Gio.DBusCallFlags.NONE, -1, None,
            )
        except Exception as exc:
            log(f"{method} failed: {exc}")

    def close(self) -> None:
        if self.session:
            try:
                self.bus.call_sync(
                    PORTAL_BUS, self.session, SESSION_IFACE, "Close",
                    None, None, self.Gio.DBusCallFlags.NONE, 3000, None,
                )
            except Exception:
                pass
            self.session = None


class Stream:
    """Pulls frames from the PipeWire node through GStreamer's pipewiresrc,
    which does PipeWire's buffer negotiation for us. The pipeline JPEG-encodes
    each frame (jpegenc) so the pipe to the agent carries ~100 KB, not a
    multi-MB raw frame - the single biggest cost of the Wayland path, which the
    zero-copy X11 path never pays."""

    def __init__(self, Gst, fd: int, node: int) -> None:
        self.Gst = Gst
        # Tests (and only tests) can stand a GStreamer test source in for the
        # PipeWire one, so everything after it is exercised for real.
        source = os.environ.get("RMM_WAYLAND_TEST_SOURCE") or (
            f"pipewiresrc fd={fd} path={node} do-timestamp=true always-copy=true"
        )
        # jpegenc (gstreamer1.0-plugins-good) compresses in-pipeline, before the
        # frame ever reaches Python or the pipe. videoconvert gives it a format
        # it accepts; the agent re-tiles after decoding, so quality is kept high.
        self.pipeline = Gst.parse_launch(
            f"{source} ! videoconvert ! jpegenc quality=90 ! "
            "appsink name=sink max-buffers=1 drop=true sync=false"
        )
        self.sink = self.pipeline.get_by_name("sink")
        self.bus = self.pipeline.get_bus()
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError(self._error() or "the PipeWire stream would not start")
        self.have_frame = False

    def _error(self) -> str | None:
        Gst = self.Gst
        message = self.bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
        if message is None:
            return None
        if message.type == Gst.MessageType.EOS:
            return "the screen share ended"
        error, _debug = message.parse_error()
        return f"stream error: {error.message}"

    def pull(self, timeout: float):
        """A new frame as (width, height, jpeg) or None if nothing new.

        jpegenc hands us a finished JPEG, so there is no raw RGB stride to
        de-pad and no multi-MB buffer to copy row by row - just the compressed
        blob, which is what makes this path cheap."""
        Gst = self.Gst
        sample = self.sink.emit("try-pull-sample", int(timeout * Gst.SECOND))
        if sample is None:
            problem = self._error()
            if problem:
                raise RuntimeError(problem)
            return None
        structure = sample.get_caps().get_structure(0)
        # image/jpeg caps still carry the frame size.
        width = structure.get_value("width")
        height = structure.get_value("height")
        buffer = sample.get_buffer()
        ok, mapping = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return None
        try:
            jpeg = bytes(mapping.data)
        finally:
            buffer.unmap(mapping)
        self.have_frame = True
        return width, height, jpeg

    def close(self) -> None:
        try:
            self.pipeline.set_state(self.Gst.State.NULL)
        except Exception:
            pass


def check() -> int:
    report = {"python": sys.executable, "pygobject": False, "gstreamer": None,
              "pipewiresrc": False, "jpegenc": False, "screencast": 0, "remote_desktop": 0}
    try:
        import gi

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        gi.require_version("Gst", "1.0")
        from gi.repository import Gio, GLib, Gst

        report["pygobject"] = True
        Gst.init(None)
        report["gstreamer"] = Gst.version_string()
        report["pipewiresrc"] = Gst.ElementFactory.find("pipewiresrc") is not None
        # jpegenc lives in gstreamer1.0-plugins-good; the capture pipeline needs
        # it to compress frames before they cross the pipe.
        report["jpegenc"] = Gst.ElementFactory.find("jpegenc") is not None
        try:
            portal = Portal(Gio, GLib)
            report["screencast"] = portal.version(SCREENCAST_IFACE)
            report["remote_desktop"] = portal.version(REMOTE_DESKTOP_IFACE)
        except Exception as exc:
            report["bus_error"] = str(exc)
    except Exception as exc:
        report["error"] = str(exc)
    print(json.dumps(report))
    return 0


def main() -> int:
    if "--check" in sys.argv:
        return check()

    config = json.loads(sys.stdin.readline() or "{}")
    try:
        import gi

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        gi.require_version("Gst", "1.0")
        from gi.repository import Gio, GLib, Gst
    except Exception as exc:
        send_json({"event": "error", "denied": False,
                   "detail": f"PyGObject/GStreamer missing for {sys.executable}: {exc}"})
        return 2

    Gst.init(None)
    portal = None
    stream = None
    try:
        portal = Portal(Gio, GLib)
        want_input = bool(config.get("want_input", True))
        try:
            granted = portal.start(want_input, int(config.get("persist_mode", 0)),
                                   config.get("restore_token"))
        except Denied:
            raise
        except Exception as exc:
            if not want_input:
                raise
            # Some portals (xdg-desktop-portal-wlr, older KDE) offer screen
            # casting but no RemoteDesktop. A view with no control beats a
            # black screen, so try again for the picture alone.
            log(f"remote-desktop portal unavailable ({exc}); sharing the screen without input")
            portal.close()
            granted = portal.start(False, int(config.get("persist_mode", 0)),
                                   config.get("restore_token"))
        stream = Stream(Gst, granted["fd"], portal.node)
        first = stream.pull(FIRST_FRAME_TIMEOUT)
        if first is None:
            raise RuntimeError("the portal stream started but sent no picture")
        width, height = granted["width"] or first[0], granted["height"] or first[1]
        send_json({
            "event": "ready",
            "monitors": [{"index": 0, "label": "Shared screen", "width": width,
                          "height": height, "left": granted["left"], "top": granted["top"]}],
            "input": granted["input"],
            "restore_token": granted["restore_token"],
        })
    except Denied as exc:
        send_json({"event": "error", "denied": True, "detail": str(exc)})
        if portal:
            portal.close()
        return 3
    except Exception as exc:
        send_json({"event": "error", "denied": False, "detail": str(exc)})
        if stream:
            stream.close()
        if portal:
            portal.close()
        return 1

    # Input runs on its own thread so a pointer move is never stuck behind a
    # frame being pulled; frames are pulled INLINE in this reader loop, on the
    # very thread that created and started the GStreamer pipeline. Moving the
    # frame pull onto a second worker thread is what froze the picture after the
    # first frame (the worker stopped after one pull while input, on its own
    # thread, kept working - exactly the "frozen screen, agent still responds"
    # symptom). The appsink pull (frames, this thread) and GDBus call_sync
    # (input, the worker) touch different subsystems, so they never collide, and
    # only this thread ever writes to the pipe, so no output lock is needed.
    input_q: "queue.Queue" = queue.Queue()
    pending = first
    frames_sent = 0

    def input_worker() -> None:
        # Drains to the sentinel so input queued before close is still injected.
        while True:
            command = input_q.get()
            if command is None:
                break
            op = command.get("op")
            try:
                if op == "motion":
                    portal.notify("NotifyPointerMotionAbsolute", "(oa{sv}udd)",
                                  (portal.node, float(command["x"]), float(command["y"])))
                elif op == "button":
                    portal.notify("NotifyPointerButton", "(oa{sv}iu)",
                                  (int(command["button"]), 1 if command.get("pressed") else 0))
                elif op == "axis":
                    portal.notify("NotifyPointerAxisDiscrete", "(oa{sv}ui)",
                                  (0, int(command["steps"])))
                elif op == "key":
                    portal.notify("NotifyKeyboardKeysym", "(oa{sv}iu)",
                                  (int(command["keysym"]), 1 if command.get("pressed") else 0))
            except Exception as exc:
                log(f"input {op} failed: {exc}")

    worker = threading.Thread(target=input_worker, name="wl-input", daemon=True)
    worker.start()

    # Keep a GLib main loop running for the life of the stream. During the
    # handshake, request() iterated the default main context by hand, which is
    # what let pipewiresrc negotiate and buffer its first few frames. Once the
    # handshake returned, nothing iterated it any more - so the startup burst
    # drained and the appsink never saw another buffer (the "frames 1,2,3 then
    # frozen" the log showed). pipewiresrc and the portal session's D-Bus events
    # are serviced from that main context, so it has to keep being pumped.
    glib_loop = GLib.MainLoop()
    glib_thread = threading.Thread(target=glib_loop.run, name="wl-glib", daemon=True)
    glib_thread.start()
    try:
        for line in sys.stdin:
            try:
                command = json.loads(line)
            except ValueError:
                continue
            op = command.get("op")
            if op == "grab":
                # Pull and answer on this thread. The first frame was already
                # pulled during the handshake, so it is sent as-is.
                try:
                    if pending is not None:
                        frame, pending = pending, None
                    else:
                        frame = stream.pull(0.05)
                except RuntimeError as exc:
                    # The stream itself ended: tell the agent and stop.
                    send(b"E", str(exc).encode())
                    break
                except Exception as exc:
                    # A transient pull hiccup must NEVER freeze the picture.
                    # Report it as "no new frame" and keep serving the next grab.
                    log(f"frame pull failed, treating as still: {exc}")
                    send(b"S", b"")
                    continue
                if frame is None:
                    send(b"S", b"")
                else:
                    w, h, jpeg = frame
                    send(b"F", struct.pack("<II", w, h) + jpeg)
                    frames_sent += 1
                    # Proof of frame flow in agent.log: the first few, then every
                    # 30, so whether frames keep coming (and at what rate) is
                    # obvious from the log alone.
                    if frames_sent <= 3 or frames_sent % 30 == 0:
                        log(f"frames sent: {frames_sent}")
            elif op in ("motion", "button", "axis", "key"):
                if granted["input"]:
                    input_q.put(command)
            elif op == "close":
                break
    finally:
        glib_loop.quit()
        input_q.put(None)
        worker.join(timeout=3)
        stream.close()
        portal.close()
        try:
            os.close(granted["fd"])
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
