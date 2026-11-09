#!/usr/bin/env bash
# Universal Linux install - any distro, any package manager, X11 or Wayland.
#
#   ./installers/linux/install.sh
#
# The .deb (build_deb.sh) only covers Debian-family systems. This covers the
# rest (Fedora/RHEL, Arch, openSUSE) with the same binary, installing each
# distro's own names for the same native libraries - the X11 ones every
# platform here has always needed, plus PyGObject + GStreamer's pipewire
# plugin, which is the only way this agent can capture or inject input on a
# real Wayland session (Wayland blocks the X11 path for both by design - see
# agent/rmm_agent/wayland_portal.py). Installing these is not optional
# bonus behaviour: without them, a Wayland session silently falls back to a
# black-screen X11 capture, which is the whole bug this script exists to
# stop happening depending on which distro someone is on.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BINARY="$ROOT/agent/dist/rmm-agent-linux"
[[ -f "$BINARY" ]] || BINARY="$ROOT/agent/dist/rmm-agent"
if [[ ! -f "$BINARY" ]]; then
    echo "No agent binary found. Build it first: cd agent && python build.py" >&2
    exit 1
fi
if [[ "$(id -u)" -ne 0 ]]; then
    echo "Run this with sudo - it installs system packages and writes to /usr." >&2
    exit 1
fi

# Every required step ends in `|| return 1`: this function is called as an
# `if` condition, and bash switches `set -e` off inside such a call, so a
# failed install used to carry on silently - the exact failure this script
# exists to prevent.
install_packages() {
    if command -v apt-get >/dev/null 2>&1; then
        echo "Debian/Ubuntu family (apt) detected"
        apt-get update || return 1
        apt-get install -y --no-install-recommends \
            libx11-6 libxext6 libxrandr2 libxfixes3 x11-xserver-utils \
            python3 python3-gi gir1.2-glib-2.0 gir1.2-gstreamer-1.0 \
            gstreamer1.0-plugins-base gstreamer1.0-pipewire || return 1
        apt-get install -y --no-install-recommends python3-tk gir1.2-appindicator3-0.1 || true
    elif command -v dnf >/dev/null 2>&1; then
        echo "Fedora/RHEL family (dnf) detected"
        dnf install -y \
            libX11 libXext libXrandr libXfixes \
            python3 python3-gobject glib2 gstreamer1 gstreamer1-plugins-base \
            pipewire-gstreamer || return 1
        # xrandr (the Linux privacy blank dims with it) is its own package on
        # current Fedora and part of xorg-x11-server-utils on older RHEL.
        dnf install -y xrandr || dnf install -y xorg-x11-server-utils || return 1
        dnf install -y python3-tkinter libappindicator-gtk3 || true
    elif command -v pacman >/dev/null 2>&1; then
        echo "Arch family (pacman) detected"
        # No -y: refreshing the database without upgrading (-Sy) is the
        # partial upgrade Arch warns can break the system.
        if ! pacman -S --noconfirm --needed \
                libx11 libxext libxrandr libxfixes xorg-xrandr \
                python python-gobject glib2 gstreamer gst-plugins-base gst-plugin-pipewire; then
            echo "pacman could not install the packages; run 'pacman -Syu' first, then this again." >&2
            return 1
        fi
        # libappindicator-gtk3 is not in Arch's repositories (AUR only); the
        # tray uses Ayatana's, which is.
        pacman -S --noconfirm --needed tk libayatana-appindicator || true
    elif command -v zypper >/dev/null 2>&1; then
        echo "openSUSE family (zypper) detected"
        zypper --non-interactive install \
            libX11-6 libXext6 libXrandr2 libXfixes3 xrandr \
            python3 python3-gobject typelib-1_0-GLib-2_0 typelib-1_0-Gio-2_0 \
            typelib-1_0-Gst-1_0 gstreamer-plugins-base gstreamer-plugin-pipewire || return 1
        zypper --non-interactive install python3-tk typelib-1_0-AppIndicator3-0_1 || true
    else
        echo "No known package manager (apt/dnf/pacman/zypper) found." >&2
        echo "Install these yourself before running the agent on Wayland:" >&2
        echo "  X11: libx11, libxext, libxrandr, libxfixes, an xset/xrandr CLI" >&2
        echo "  Wayland: PyGObject (gi), GLib and GStreamer GObject-Introspection" >&2
        echo "           typelibs, GStreamer's pipewire plugin" >&2
        return 1
    fi
}

PACKAGES_OK=1
if ! install_packages; then
    PACKAGES_OK=0
    echo "WARNING: the required packages did not all install - see above." >&2
fi

# Wayland desktops are shared through rmm_agent/wayland_helper.py running
# under this machine's own python3. Check that python3 really has what the
# helper needs, rather than trusting the package names above.
WAYLAND_OK=1
if ! python3 - <<'PYCHECK'
import gi
gi.require_version("Gio", "2.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gio, Gst
Gst.init(None)
for element in ("pipewiresrc", "videoconvert", "appsink"):
    assert Gst.ElementFactory.find(element), f"GStreamer element {element} is missing"
PYCHECK
then
    WAYLAND_OK=0
fi

install -d /usr/lib/rmm-agent /usr/bin /usr/share/applications /usr/lib/systemd/user
install -m 0755 "$BINARY" /usr/lib/rmm-agent/rmm-agent

cat > /usr/bin/rmm-agent <<'EOF'
#!/bin/sh
exec /usr/lib/rmm-agent/rmm-agent "$@"
EOF
chmod 0755 /usr/bin/rmm-agent

cat > /usr/share/applications/rmm-agent.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Remote Support
Comment=Join a remote support session
Exec=/usr/bin/rmm-agent start
Icon=preferences-desktop-remote-desktop
Terminal=false
Categories=Network;RemoteAccess;
Keywords=remote;support;help;
EOF

# Same two user units the .deb installs (installers/linux/build_deb.sh) -
# unattended access and resume-after-restart. Neither is enabled here either:
# that stays a decision someone makes, same reasoning as the .deb.
cat > /usr/lib/systemd/user/rmm-agent.service <<'EOF'
[Unit]
Description=Remote support endpoint agent (unattended)
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
# RMM_SECRET reaches the agent through the environment (EnvironmentFile),
# never the command line, which every user on the machine can read.
ExecStart=/usr/bin/rmm-agent enrol --device-id ${RMM_DEVICE_ID} --relay ${RMM_RELAY}
EnvironmentFile=%h/.config/rmm-agent/env
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
EOF

cat > /usr/lib/systemd/user/rmm-agent-resume.service <<'EOF'
[Unit]
Description=Remote support agent (rejoins the session it was started with)
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/rmm-agent resume
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
EOF

# Login entry every desktop runs (see build_deb.sh for why the service alone
# never came back on XFCE, MATE, LXQt or Cinnamon).
mkdir -p /etc/xdg/autostart
cat > /etc/xdg/autostart/rmm-agent-login.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Remote Support (rejoin at login)
Comment=Brings the remote support agent back after a restart, if it was running
Exec=/usr/bin/rmm-agent login
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF

echo
echo "rmm-agent installed to /usr/bin/rmm-agent."
echo "  Attended:   rmm-agent join --relay wss://<host>/api --code <CODE>"
echo "  Unattended: put RMM_DEVICE_ID, RMM_SECRET and RMM_RELAY in"
echo "              ~/.config/rmm-agent/env, then"
echo "              systemctl --user enable --now rmm-agent"

if [[ "$WAYLAND_OK" -ne 1 ]]; then
    echo >&2
    echo "ERROR: python3 cannot load PyGObject + GStreamer's pipewire plugin." >&2
    echo "       X11 desktops will work, but a Wayland desktop cannot be shared" >&2
    echo "       until they are installed (see the messages above)." >&2
    exit 1
fi
if [[ "$PACKAGES_OK" -ne 1 ]]; then
    exit 1
fi
echo "Checked: X11 and Wayland desktops can both be shared."
