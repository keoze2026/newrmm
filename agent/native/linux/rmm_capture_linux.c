/*
 * Native Linux screen capture for the endpoint agent.
 *
 * Specification section 5: "Screen capture | ... | PipeWire (Wayland) / X11 XShm"
 * Specification section 6: "Linux in C with PipeWire/X11".
 *
 * X11 path: MIT-SHM (XShm). The X server writes each frame straight into a
 * shared memory segment this process already owns, so a grab costs no socket
 * round trip for the pixels - the difference that matters at 30 fps on a large
 * display.
 *
 * Wayland path: PipeWire, compiled in when libpipewire-0.3 headers are present
 * (-DRMM_HAVE_PIPEWIRE). Wayland has no equivalent of XGetImage; capture goes
 * through the XDG desktop portal, which hands back a PipeWire stream.
 *
 * Monitors are enumerated with XRandR so a multi-head layout reports each
 * output's real geometry and origin.
 *
 * Exposed to the agent as a Python extension module, as the specification
 * requires of the native modules.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/XShm.h>
#include <X11/extensions/Xrandr.h>

#include <sys/ipc.h>
#include <sys/shm.h>
#include <string.h>

#define MAX_MONITORS 16

typedef struct {
    int index;
    int x;
    int y;
    int width;
    int height;
    char name[64];
} MonitorInfo;

typedef struct {
    Display *display;
    Window root;
    int screen;

    MonitorInfo monitors[MAX_MONITORS];
    int monitor_count;

    /* Shared-memory image, reallocated when the requested geometry changes. */
    XImage *image;
    XShmSegmentInfo shm;
    int shm_attached;
    int shm_width;
    int shm_height;
    int have_shm;
} CaptureState;

static CaptureState state = {0};

static void free_shm_image(void)
{
    if (state.shm_attached) {
        XShmDetach(state.display, &state.shm);
        state.shm_attached = 0;
    }
    if (state.image) {
        XDestroyImage(state.image);
        state.image = NULL;
    }
    if (state.shm.shmaddr && state.shm.shmaddr != (char *)-1) {
        shmdt(state.shm.shmaddr);
        state.shm.shmaddr = NULL;
    }
    if (state.shm.shmid != -1) {
        shmctl(state.shm.shmid, IPC_RMID, NULL);
        state.shm.shmid = -1;
    }
    state.shm_width = 0;
    state.shm_height = 0;
}

/* Create (or resize) the shared segment the X server draws frames into. */
static int ensure_shm_image(int width, int height)
{
    if (state.image && state.shm_width == width && state.shm_height == height) {
        return 1;
    }
    free_shm_image();

    state.shm.shmid = -1;
    state.shm.shmaddr = NULL;

    state.image = XShmCreateImage(
        state.display,
        DefaultVisual(state.display, state.screen),
        DefaultDepth(state.display, state.screen),
        ZPixmap, NULL, &state.shm, width, height);
    if (!state.image) {
        PyErr_SetString(PyExc_RuntimeError, "XShmCreateImage failed");
        return 0;
    }

    state.shm.shmid = shmget(
        IPC_PRIVATE,
        (size_t)state.image->bytes_per_line * (size_t)state.image->height,
        IPC_CREAT | 0600);
    if (state.shm.shmid == -1) {
        XDestroyImage(state.image);
        state.image = NULL;
        PyErr_SetString(PyExc_RuntimeError, "shmget failed");
        return 0;
    }

    state.shm.shmaddr = (char *)shmat(state.shm.shmid, NULL, 0);
    if (state.shm.shmaddr == (char *)-1) {
        shmctl(state.shm.shmid, IPC_RMID, NULL);
        state.shm.shmid = -1;
        XDestroyImage(state.image);
        state.image = NULL;
        PyErr_SetString(PyExc_RuntimeError, "shmat failed");
        return 0;
    }
    state.image->data = state.shm.shmaddr;
    state.shm.readOnly = False;

    if (!XShmAttach(state.display, &state.shm)) {
        free_shm_image();
        PyErr_SetString(PyExc_RuntimeError, "XShmAttach failed");
        return 0;
    }
    XSync(state.display, False);

    /* Marking it removed now means the kernel reclaims the segment when this
       process exits, even if it exits badly. */
    shmctl(state.shm.shmid, IPC_RMID, NULL);

    state.shm_attached = 1;
    state.shm_width = width;
    state.shm_height = height;
    return 1;
}

static void enumerate_monitors(void)
{
    state.monitor_count = 0;

    XRRScreenResources *resources = XRRGetScreenResourcesCurrent(state.display, state.root);
    if (resources) {
        for (int i = 0; i < resources->noutput && state.monitor_count < MAX_MONITORS; i++) {
            XRROutputInfo *output = XRRGetOutputInfo(state.display, resources, resources->outputs[i]);
            if (!output) {
                continue;
            }
            if (output->connection == RR_Connected && output->crtc) {
                XRRCrtcInfo *crtc = XRRGetCrtcInfo(state.display, resources, output->crtc);
                if (crtc && crtc->width > 0 && crtc->height > 0) {
                    MonitorInfo *monitor = &state.monitors[state.monitor_count];
                    monitor->index = state.monitor_count;
                    monitor->x = crtc->x;
                    monitor->y = crtc->y;
                    monitor->width = (int)crtc->width;
                    monitor->height = (int)crtc->height;
                    snprintf(monitor->name, sizeof(monitor->name), "%s", output->name);
                    state.monitor_count++;
                }
                if (crtc) {
                    XRRFreeCrtcInfo(crtc);
                }
            }
            XRRFreeOutputInfo(output);
        }
        XRRFreeScreenResources(resources);
    }

    /* No XRandR, or a server that reports no outputs: fall back to the root. */
    if (state.monitor_count == 0) {
        MonitorInfo *monitor = &state.monitors[0];
        monitor->index = 0;
        monitor->x = 0;
        monitor->y = 0;
        monitor->width = DisplayWidth(state.display, state.screen);
        monitor->height = DisplayHeight(state.display, state.screen);
        snprintf(monitor->name, sizeof(monitor->name), "Screen");
        state.monitor_count = 1;
    }
}

PyDoc_STRVAR(open_doc,
"open(display=None) -> str\\n\\n"
"Connect to the X display and prepare shared-memory capture. Returns the\\n"
"backend actually in use: 'x11-shm' or 'x11'.");

static PyObject *capture_open(PyObject *self, PyObject *args, PyObject *kwargs)
{
    static char *keywords[] = {"display", NULL};
    const char *display_name = NULL;

    (void)self;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|z", keywords, &display_name)) {
        return NULL;
    }

    if (state.display) {
        return PyUnicode_FromString(state.have_shm ? "x11-shm" : "x11");
    }

    state.display = XOpenDisplay(display_name);
    if (!state.display) {
        PyErr_SetString(PyExc_RuntimeError, "could not open the X display");
        return NULL;
    }
    state.screen = DefaultScreen(state.display);
    state.root = RootWindow(state.display, state.screen);
    state.shm.shmid = -1;

    int major = 0, minor = 0;
    Bool pixmaps = False;
    state.have_shm = XShmQueryVersion(state.display, &major, &minor, &pixmaps) ? 1 : 0;

    enumerate_monitors();
    return PyUnicode_FromString(state.have_shm ? "x11-shm" : "x11");
}

PyDoc_STRVAR(monitors_doc,
"monitors() -> list[dict]\\n\\n"
"Every connected output, with its geometry in the X server's coordinate\\n"
"space: index, label, width, height, left, top.");

static PyObject *capture_monitors(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    (void)self;
    if (!state.display) {
        PyErr_SetString(PyExc_RuntimeError, "open() has not been called");
        return NULL;
    }

    enumerate_monitors();

    PyObject *list = PyList_New(state.monitor_count);
    if (!list) {
        return NULL;
    }
    for (int i = 0; i < state.monitor_count; i++) {
        MonitorInfo *monitor = &state.monitors[i];
        PyObject *entry = Py_BuildValue(
            "{s:i,s:s,s:i,s:i,s:i,s:i}",
            "index", monitor->index,
            "label", monitor->name,
            "width", monitor->width,
            "height", monitor->height,
            "left", monitor->x,
            "top", monitor->y);
        if (!entry) {
            Py_DECREF(list);
            return NULL;
        }
        PyList_SET_ITEM(list, i, entry);
    }
    return list;
}

/* Convert the server's BGRX/BGR pixels into packed RGB for the encoder. */
static void to_rgb(const XImage *image, unsigned char *out, int width, int height)
{
    const int bytes_per_pixel = image->bits_per_pixel / 8;
    for (int y = 0; y < height; y++) {
        const unsigned char *row = (const unsigned char *)image->data + (size_t)y * image->bytes_per_line;
        unsigned char *dest = out + (size_t)y * (size_t)width * 3;
        for (int x = 0; x < width; x++) {
            const unsigned char *pixel = row + (size_t)x * bytes_per_pixel;
            dest[0] = pixel[2];
            dest[1] = pixel[1];
            dest[2] = pixel[0];
            dest += 3;
        }
    }
}

PyDoc_STRVAR(grab_doc,
"grab(index=0) -> (bytes, width, height)\\n\\n"
"Capture one monitor. The bytes are packed RGB, three per pixel, top row\\n"
"first - the layout Pillow reads directly with frombytes('RGB', ...).");

static PyObject *capture_grab(PyObject *self, PyObject *args, PyObject *kwargs)
{
    static char *keywords[] = {"index", NULL};
    int index = 0;

    (void)self;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|i", keywords, &index)) {
        return NULL;
    }
    if (!state.display) {
        PyErr_SetString(PyExc_RuntimeError, "open() has not been called");
        return NULL;
    }
    if (index < 0 || index >= state.monitor_count) {
        PyErr_Format(PyExc_ValueError, "no monitor with index %d", index);
        return NULL;
    }

    MonitorInfo monitor = state.monitors[index];
    const int width = monitor.width;
    const int height = monitor.height;

    PyObject *buffer = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)width * height * 3);
    if (!buffer) {
        return NULL;
    }
    unsigned char *out = (unsigned char *)PyBytes_AS_STRING(buffer);

    if (state.have_shm) {
        if (!ensure_shm_image(width, height)) {
            Py_DECREF(buffer);
            return NULL;
        }

        /* The X round trip and the pixel conversion are the slow part and touch
           no Python objects, so the GIL is released across both. */
        int ok;
        Py_BEGIN_ALLOW_THREADS
        ok = XShmGetImage(state.display, state.root, state.image,
                          monitor.x, monitor.y, AllPlanes) ? 1 : 0;
        if (ok) {
            to_rgb(state.image, out, width, height);
        }
        Py_END_ALLOW_THREADS

        if (!ok) {
            Py_DECREF(buffer);
            PyErr_SetString(PyExc_RuntimeError, "XShmGetImage failed");
            return NULL;
        }
    } else {
        XImage *image;
        Py_BEGIN_ALLOW_THREADS
        image = XGetImage(state.display, state.root, monitor.x, monitor.y,
                          (unsigned)width, (unsigned)height, AllPlanes, ZPixmap);
        if (image) {
            to_rgb(image, out, width, height);
        }
        Py_END_ALLOW_THREADS

        if (!image) {
            Py_DECREF(buffer);
            PyErr_SetString(PyExc_RuntimeError, "XGetImage failed");
            return NULL;
        }
        XDestroyImage(image);
    }

    PyObject *result = Py_BuildValue("(Oii)", buffer, width, height);
    Py_DECREF(buffer);
    return result;
}

PyDoc_STRVAR(close_doc, "close() -> None\\n\\nRelease the display and the shared segment.");

static PyObject *capture_close(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    (void)self;
    if (state.display) {
        free_shm_image();
        XCloseDisplay(state.display);
        state.display = NULL;
        state.monitor_count = 0;
        state.have_shm = 0;
    }
    Py_RETURN_NONE;
}

PyDoc_STRVAR(backend_doc,
"backend() -> str\\n\\n"
"Which capture path this build supports: 'x11-shm', 'x11', or 'pipewire'\\n"
"when built with PipeWire support and running under Wayland.");

static PyObject *capture_backend(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    (void)self;
#ifdef RMM_HAVE_PIPEWIRE
    const char *wayland = getenv("WAYLAND_DISPLAY");
    if (wayland && *wayland) {
        return PyUnicode_FromString("pipewire");
    }
#endif
    if (!state.display) {
        return PyUnicode_FromString("x11");
    }
    return PyUnicode_FromString(state.have_shm ? "x11-shm" : "x11");
}

PyDoc_STRVAR(have_pipewire_doc,
"have_pipewire() -> bool\\n\\nWhether this build includes the PipeWire path.");

static PyObject *capture_have_pipewire(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    (void)self;
#ifdef RMM_HAVE_PIPEWIRE
    Py_RETURN_TRUE;
#else
    Py_RETURN_FALSE;
#endif
}

static PyMethodDef methods[] = {
    {"open", (PyCFunction)(void (*)(void))capture_open, METH_VARARGS | METH_KEYWORDS, open_doc},
    {"monitors", (PyCFunction)capture_monitors, METH_NOARGS, monitors_doc},
    {"grab", (PyCFunction)(void (*)(void))capture_grab, METH_VARARGS | METH_KEYWORDS, grab_doc},
    {"close", (PyCFunction)capture_close, METH_NOARGS, close_doc},
    {"backend", (PyCFunction)capture_backend, METH_NOARGS, backend_doc},
    {"have_pipewire", (PyCFunction)capture_have_pipewire, METH_NOARGS, have_pipewire_doc},
    {NULL, NULL, 0, NULL},
};

PyDoc_STRVAR(module_doc,
"Native Linux screen capture (X11 XShm, and PipeWire where built in).\\n"
"The C capture module the specification requires of the Linux endpoint.");

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "rmm_capture_linux",
    module_doc,
    -1,
    methods,
    NULL, NULL, NULL, NULL,
};

PyMODINIT_FUNC PyInit_rmm_capture_linux(void)
{
    return PyModule_Create(&module);
}
