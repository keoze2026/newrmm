//! Native Windows screen capture for the endpoint agent.
//!
//! Specification section 5: "Screen capture | Windows.Graphics.Capture (native)"
//! and "Privacy blank | Capture-exclusion flag + native capture engine (Rust)".
//! Section 6: "Windows native module in RUST via the windows-capture /
//! Windows.Graphics.Capture binding, exposed to the agent as a Python module".
//!
//! Why this engine rather than a plain screen grab: the privacy blank puts a
//! black window over the guest's display and marks it `WDA_EXCLUDEFROMCAPTURE`.
//! The compositor then keeps that window out of Windows.Graphics.Capture
//! frames, so this module keeps delivering live frames of the desktop *behind*
//! the blank. A GDI/BitBlt grab of the screen has no such notion and would
//! hand back the black window, which is exactly the case the specification
//! calls out.
//!
//! Frames are produced on a capture thread by the OS and handed over as packed
//! RGB, matching the Linux module so the agent treats both the same way.

use std::panic::{self, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};

use windows_capture::capture::{Context, GraphicsCaptureApiHandler};
use windows_capture::frame::Frame;
use windows_capture::graphics_capture_api::InternalCaptureControl;
use windows_capture::monitor::Monitor;
use windows_capture::settings::{
    ColorFormat, CursorCaptureSettings, DirtyRegionSettings, DrawBorderSettings,
    MinimumUpdateIntervalSettings, SecondaryWindowSettings, Settings,
};

use windows::Win32::Graphics::Gdi::{GetMonitorInfoW, HMONITOR, MONITORINFO};

/// Top-left corner of a monitor in the virtual desktop.
///
/// windows-capture exposes the HMONITOR but no position accessor, and the
/// origin matters: operator input is mapped against it, so a second monitor
/// without one would put every click on the primary.
fn monitor_origin(monitor: &Monitor) -> (i32, i32) {
    let handle = HMONITOR(monitor.as_raw_hmonitor());
    let mut info = MONITORINFO {
        cbSize: std::mem::size_of::<MONITORINFO>() as u32,
        ..Default::default()
    };
    let ok = unsafe { GetMonitorInfoW(handle, &mut info) };
    if ok.as_bool() {
        (info.rcMonitor.left, info.rcMonitor.top)
    } else {
        (0, 0)
    }
}

/// The most recent frame, shared between the OS capture thread and Python.
#[derive(Default)]
struct LatestFrame {
    pixels: Vec<u8>,
    width: u32,
    height: u32,
    frames_seen: u64,
}

type Shared = Arc<Mutex<LatestFrame>>;

struct Handler {
    shared: Shared,
    stop: Arc<AtomicBool>,
}

impl GraphicsCaptureApiHandler for Handler {
    type Flags = (Shared, Arc<AtomicBool>);
    type Error = Box<dyn std::error::Error + Send + Sync>;

    fn new(context: Context<Self::Flags>) -> Result<Self, Self::Error> {
        let (shared, stop) = context.flags;
        Ok(Self { shared, stop })
    }

    /// Called by Windows for every frame it composites.
    fn on_frame_arrived(
        &mut self,
        frame: &mut Frame,
        control: InternalCaptureControl,
    ) -> Result<(), Self::Error> {
        // close() and a monitor switch both used to just drop this Session,
        // which never actually stopped the OS capture session or this
        // thread - every switch leaked one more of each, forever, for the
        // life of the process. This is the only place that can end the
        // capture: `stop()` must be called from inside this callback.
        if self.stop.load(Ordering::SeqCst) {
            control.stop();
            return Ok(());
        }

        let width = frame.width();
        let height = frame.height();

        let mut buffer = frame.buffer()?;
        // Rows are padded to the capture surface stride, so copy row by row
        // rather than assuming width * 4.
        let raw = buffer.as_nopadding_buffer()?;

        let mut rgb = Vec::with_capacity((width as usize) * (height as usize) * 3);
        // The surface is BGRA; the agent wants packed RGB.
        for chunk in raw.chunks_exact(4) {
            rgb.push(chunk[2]);
            rgb.push(chunk[1]);
            rgb.push(chunk[0]);
        }

        if let Ok(mut latest) = self.shared.lock() {
            latest.pixels = rgb;
            latest.width = width;
            latest.height = height;
            latest.frames_seen += 1;
        }
        Ok(())
    }

    fn on_closed(&mut self) -> Result<(), Self::Error> {
        Ok(())
    }
}

/// A running capture of one monitor.
struct Session {
    shared: Shared,
    stop: Arc<AtomicBool>,
    monitor_index: usize,
    _thread: std::thread::JoinHandle<()>,
}

impl Session {
    /// Tell the capture thread to stop. Does not block: the thread notices on
    /// its next frame callback (normally well under a second) and exits on
    /// its own; the OS capture session is released once it does. Not joined
    /// here on purpose - a stalled display (unplugged, asleep, DXGI lost)
    /// would otherwise turn this into a hang instead of the leak it replaces.
    fn signal_stop(&self) {
        self.stop.store(true, Ordering::SeqCst);
    }
}

static SESSION: Mutex<Option<Session>> = Mutex::new(None);

fn monitor_at(index: usize) -> PyResult<Monitor> {
    let monitors = Monitor::enumerate()
        .map_err(|e| PyRuntimeError::new_err(format!("could not enumerate monitors: {e}")))?;
    monitors
        .into_iter()
        .nth(index)
        .ok_or_else(|| PyValueError::new_err(format!("no monitor with index {index}")))
}

fn start_session(index: usize) -> PyResult<Session> {
    let monitor = monitor_at(index)?;
    let shared: Shared = Arc::new(Mutex::new(LatestFrame::default()));
    let stop = Arc::new(AtomicBool::new(false));
    let flags = (Arc::clone(&shared), Arc::clone(&stop));

    let settings = Settings::new(
        monitor,
        CursorCaptureSettings::WithCursor,
        // No yellow "you are being recorded" border: the endpoint already shows
        // a tray indicator and a consent surface of its own.
        DrawBorderSettings::WithoutBorder,
        SecondaryWindowSettings::Default,
        MinimumUpdateIntervalSettings::Default,
        DirtyRegionSettings::Default,
        ColorFormat::Bgra8,
        flags,
    );

    let thread = std::thread::spawn(move || {
        // A panic unwinding out of this thread - including one that started
        // inside on_frame_arrived, which Windows calls back into from its own
        // capture machinery on this same thread - would otherwise be an
        // uncatchable process abort with nothing logged anywhere: exactly the
        // "agent died with zero trace" symptom this project has been chasing.
        // Catching it here, at the entry point, turns that into a loggable,
        // recoverable thread exit instead.
        let outcome = panic::catch_unwind(AssertUnwindSafe(|| Handler::start(settings)));
        if let Err(payload) = outcome {
            let message = payload
                .downcast_ref::<&str>()
                .map(|s| s.to_string())
                .or_else(|| payload.downcast_ref::<String>().cloned())
                .unwrap_or_else(|| "unknown panic".to_string());
            eprintln!("rmm_capture_windows: capture thread panicked: {message}");
        }
    });

    Ok(Session {
        shared,
        stop,
        monitor_index: index,
        _thread: thread,
    })
}

/// Begin capturing a monitor. Returns the backend name.
#[pyfunction]
#[pyo3(signature = (index=0))]
fn open(index: usize) -> PyResult<String> {
    let mut guard = SESSION
        .lock()
        .map_err(|_| PyRuntimeError::new_err("capture state is poisoned"))?;

    if let Some(session) = guard.as_ref() {
        if session.monitor_index == index {
            return Ok("windows-graphics-capture".to_string());
        }
        // Switching monitors used to just drop the old Session here, leaking
        // its OS capture session and thread forever - on ordinary
        // multi-monitor use, not just shutdown.
        session.signal_stop();
    }
    *guard = Some(start_session(index)?);

    // Give the compositor a moment to deliver the first frame, so the caller's
    // first grab() is not an error.
    drop(guard);
    for _ in 0..50 {
        std::thread::sleep(Duration::from_millis(20));
        if let Ok(guard) = SESSION.lock() {
            if let Some(session) = guard.as_ref() {
                if let Ok(latest) = session.shared.lock() {
                    if latest.frames_seen > 0 {
                        break;
                    }
                }
            }
        }
    }
    Ok("windows-graphics-capture".to_string())
}

/// Every connected monitor, with geometry in the OS coordinate space.
#[pyfunction]
fn monitors(py: Python<'_>) -> PyResult<Py<PyList>> {
    let found = Monitor::enumerate()
        .map_err(|e| PyRuntimeError::new_err(format!("could not enumerate monitors: {e}")))?;

    let list = PyList::empty_bound(py);
    for (index, monitor) in found.iter().enumerate() {
        let entry = PyDict::new_bound(py);
        entry.set_item("index", index)?;
        entry.set_item(
            "label",
            monitor
                .name()
                .unwrap_or_else(|_| format!("Monitor {}", index + 1)),
        )?;
        entry.set_item("width", monitor.width().unwrap_or(0))?;
        entry.set_item("height", monitor.height().unwrap_or(0))?;
        let (left, top) = monitor_origin(monitor);
        entry.set_item("left", left)?;
        entry.set_item("top", top)?;
        list.append(entry)?;
    }
    Ok(list.into())
}

/// The most recent frame as (bytes, width, height), packed RGB.
#[pyfunction]
#[pyo3(signature = (index=0))]
fn grab(py: Python<'_>, index: usize) -> PyResult<(Py<PyBytes>, u32, u32)> {
    {
        let guard = SESSION
            .lock()
            .map_err(|_| PyRuntimeError::new_err("capture state is poisoned"))?;
        let restart = match guard.as_ref() {
            None => true,
            Some(session) => session.monitor_index != index,
        };
        drop(guard);
        if restart {
            open(index)?;
        }
    }

    let guard = SESSION
        .lock()
        .map_err(|_| PyRuntimeError::new_err("capture state is poisoned"))?;
    let session = guard
        .as_ref()
        .ok_or_else(|| PyRuntimeError::new_err("capture is not running"))?;
    let latest = session
        .shared
        .lock()
        .map_err(|_| PyRuntimeError::new_err("frame buffer is poisoned"))?;

    if latest.frames_seen == 0 || latest.pixels.is_empty() {
        return Err(PyRuntimeError::new_err("no frame has arrived yet"));
    }
    Ok((
        PyBytes::new_bound(py, &latest.pixels).into(),
        latest.width,
        latest.height,
    ))
}

/// Stop capturing and release the OS session.
#[pyfunction]
fn close() -> PyResult<()> {
    let mut guard = SESSION
        .lock()
        .map_err(|_| PyRuntimeError::new_err("capture state is poisoned"))?;
    if let Some(session) = guard.as_ref() {
        session.signal_stop();
    }
    *guard = None;
    Ok(())
}

/// Which capture path this module provides.
#[pyfunction]
fn backend() -> String {
    "windows-graphics-capture".to_string()
}

/// True: this engine keeps delivering frames of the desktop behind a window
/// marked WDA_EXCLUDEFROMCAPTURE, which is what the privacy blank relies on.
#[pyfunction]
fn honours_capture_exclusion() -> bool {
    true
}

#[pymodule]
fn rmm_capture_windows(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(open, module)?)?;
    module.add_function(wrap_pyfunction!(monitors, module)?)?;
    module.add_function(wrap_pyfunction!(grab, module)?)?;
    module.add_function(wrap_pyfunction!(close, module)?)?;
    module.add_function(wrap_pyfunction!(backend, module)?)?;
    module.add_function(wrap_pyfunction!(honours_capture_exclusion, module)?)?;
    Ok(())
}
