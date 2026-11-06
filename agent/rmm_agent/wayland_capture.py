"""Decodes the PipeWire stream a Wayland portal session hands back into
plain RGB frames, the same shape ScreenCapture expects from the X11 native
module: (bytes, width, height), packed RGB, top row first.

There is no pure-Python way to speak PipeWire's own buffer-negotiation
protocol (SPA formats, DMA-BUF vs shared memory) safely, and hand-writing
that against libpipewire's C API with no way to test it against a real
compositor here is exactly the kind of thing that fails in subtle,
hard-to-diagnose ways. GStreamer's `pipewiresrc` element already does that
negotiation correctly - it is the same element most other Wayland-portal
screen tools build on - so this just builds a small pipeline around it and
pulls finished frames out of an appsink.
"""
import logging
import threading

log = logging.getLogger(__name__)

_gst_initialised = False
_gst_lock = threading.Lock()


def available() -> bool:
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # noqa: F401

        return True
    except Exception as exc:
        log.info("GStreamer (PyGObject Gst) not available; Wayland capture is disabled (%s)", exc)
        return False


class WaylandCapture:
    """Pulls frames from an already-started wayland_portal.PortalSession."""

    def __init__(self, portal) -> None:
        self._portal = portal
        self._pipeline = None
        self._sink = None
        self.ok = False

        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except Exception as exc:
            log.warning("GStreamer unavailable; cannot decode the Wayland stream (%s)", exc)
            return

        self._Gst = Gst
        global _gst_initialised
        with _gst_lock:
            if not _gst_initialised:
                Gst.init(None)
                _gst_initialised = True

        try:
            description = (
                f"pipewiresrc fd={portal.pipewire_fd} path={portal.node_id} "
                "do-timestamp=true ! videoconvert ! video/x-raw,format=RGB ! "
                "appsink name=sink emit-signals=false max-buffers=1 drop=true sync=false"
            )
            self._pipeline = Gst.parse_launch(description)
            self._sink = self._pipeline.get_by_name("sink")
            self._pipeline.set_state(Gst.State.PLAYING)
            self.ok = True
        except Exception as exc:
            log.warning("could not start the GStreamer pipewire pipeline: %s", exc)
            self._teardown()

    def grab(self, timeout_s: float = 2.0) -> tuple[bytes, int, int]:
        if not self.ok:
            raise RuntimeError("the Wayland capture pipeline is not running")
        Gst = self._Gst
        sample = self._sink.try_pull_sample(int(timeout_s * Gst.SECOND))
        if sample is None:
            raise RuntimeError("no frame arrived from the Wayland portal stream")
        caps = sample.get_caps().get_structure(0)
        width = caps.get_value("width")
        height = caps.get_value("height")
        buf = sample.get_buffer()
        ok, mapping = buf.map(Gst.MapFlags.READ)
        if not ok:
            raise RuntimeError("could not map the captured frame's buffer")
        try:
            data = bytes(mapping.data[: width * height * 3])
        finally:
            buf.unmap(mapping)
        return data, width, height

    def _teardown(self) -> None:
        if self._pipeline is not None:
            try:
                self._pipeline.set_state(self._Gst.State.NULL)
            except Exception:
                pass
            self._pipeline = None
        self._sink = None
        self.ok = False

    def close(self) -> None:
        """Tears down only the GStreamer pipeline. The portal session is
        shared with InputInjector and is owned (and closed) by whoever built
        it - session.py - not by this capture wrapper."""
        self._teardown()
