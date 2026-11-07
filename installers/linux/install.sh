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

install_packages() {
    if command -v apt-get >/dev/null 2>&1; then
        echo "Debian/Ubuntu family (apt) detected"
        apt-get update
        apt-get install -y --no-install-recommends \
            libx11-6 libxext6 libxrandr2 libxfixes3 x11-xserver-utils \
            python3-gi gir1.2-glib-2.0 gir1.2-gstreamer-1.0 \
            gstreamer1.0-plugins-base gstreamer1.0-pipewire
        apt-get install -y --no-install-recommends python3-tk gir1.2-appindicator3-0.1 || true
    elif command -v dnf >/dev/null 2>&1; then
        echo "Fedora/RHEL family (dnf) detected"
        dnf install -y \
            libX11 libXext libXrandr libXfixes xorg-x11-server-utils \
            python3-gobject glib2 gstreamer1 gstreamer1-plugins-base gstreamer1-plugin-pipewire
        dnf install -y python3-tkinter libappindicator-gtk3 || true
    elif command -v pacman >/dev/null 2>&1; then
        echo "Arch family (pacman) detected"
        pacman -Sy --noconfirm \
            libx11 libxext libxrandr libxfixes xorg-xset \
            python-gobject glib2 gstreamer gst-plugins-base gst-plugin-pipewire
        pacman -S --noconfirm --needed tk libappindicator-gtk3 || true
    elif command -v zypper >/dev/null 2>&1; then
        echo "openSUSE family (zypper) detected"
        zypper --non-interactive install \
            libX11-6 libXext6 libXrandr2 libXfixes3 xorg-x11-server-utils \
            python3-gobject typelib-1_0-Gst-1_0 gstreamer-plugins-base gstreamer-plugin-pipewire
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

install_packages || echo "WARNING: continuing without confirmed native dependencies - see above." >&2

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
ExecStart=/usr/bin/rmm-agent enrol --device-id ${RMM_DEVICE_ID} --secret ${RMM_SECRET} --relay ${RMM_RELAY}
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

echo
echo "rmm-agent installed to /usr/bin/rmm-agent."
echo "  Attended:   rmm-agent join --relay wss://<host>/api --code <CODE>"
echo "  Unattended: put RMM_DEVICE_ID, RMM_SECRET and RMM_RELAY in"
echo "              ~/.config/rmm-agent/env, then"
echo "              systemctl --user enable --now rmm-agent"
