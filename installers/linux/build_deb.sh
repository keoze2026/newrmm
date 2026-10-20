#!/usr/bin/env bash
# Build a .deb for the endpoint agent.
#
#   ./installers/linux/build_deb.sh [version]
#
# Section 8: "Every platform build is reproducible from CI and installs without
# manual steps." A bare executable does not install; this does.
#
# Installs the agent to /usr/lib/rmm-agent, a launcher at /usr/bin/rmm-agent, a
# desktop entry, and a systemd *user* service for unattended endpoints - which
# is the auto-start mechanism section 5 names for Linux. The service is not
# enabled by installing: an agent that starts watching a machine the moment a
# package lands is not something to do quietly.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="${1:-0.2.0}"
# CI passes the git ref name, which on a branch push is "main" rather than a
# version, and dpkg rejects a version that does not start with a digit.
case "$VERSION" in
    [0-9]*) ;;
    *) echo "'$VERSION' is not a version number; using 0.2.0" >&2; VERSION="0.2.0" ;;
esac
ARCH="$(dpkg --print-architecture)"
PACKAGE="rmm-agent"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

BINARY="$ROOT/agent/dist/rmm-agent-linux"
[[ -f "$BINARY" ]] || BINARY="$ROOT/agent/dist/rmm-agent"
if [[ ! -f "$BINARY" ]]; then
    echo "No agent binary found. Build it first: cd agent && python build.py" >&2
    exit 1
fi

install -d "$STAGE/DEBIAN" \
           "$STAGE/usr/lib/$PACKAGE" \
           "$STAGE/usr/bin" \
           "$STAGE/usr/share/applications" \
           "$STAGE/usr/lib/systemd/user"

install -m 0755 "$BINARY" "$STAGE/usr/lib/$PACKAGE/rmm-agent"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PACKAGE
Version: $VERSION
Section: net
Priority: optional
Architecture: $ARCH
Maintainer: Remote Desktop & Support Platform
Depends: libx11-6, libxext6, libxrandr2
Recommends: python3-tk, gir1.2-appindicator3-0.1
Description: Remote support endpoint agent
 Joins a support session, asks the person at the keyboard for consent, then
 streams the screen and applies the operator's mouse and keyboard.
 .
 Nothing is captured before consent is granted, a tray indicator is shown for
 the whole session, and every session is recorded on the server's audit trail.
EOF

cat > "$STAGE/usr/bin/rmm-agent" <<'EOF'
#!/bin/sh
exec /usr/lib/rmm-agent/rmm-agent "$@"
EOF
chmod 0755 "$STAGE/usr/bin/rmm-agent"

cat > "$STAGE/usr/share/applications/rmm-agent.desktop" <<EOF
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

# Unattended access. Deliberately not enabled by the package: enabling it is
# `systemctl --user enable --now rmm-agent`, a decision someone makes.
cat > "$STAGE/usr/lib/systemd/user/rmm-agent.service" <<'EOF'
[Unit]
Description=Remote support endpoint agent (unattended)
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/rmm-agent enrol --device-id ${RMM_DEVICE_ID} --secret ${RMM_SECRET} --relay ${RMM_RELAY}
EnvironmentFile=%h/.config/rmm-agent/env
Restart=on-failure
RestartSec=10

[Install]
WantedBy=graphical-session.target
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    echo "rmm-agent installed."
    echo "  Attended:   rmm-agent join --relay wss://<host>/api --code <CODE>"
    echo "  Unattended: put RMM_DEVICE_ID, RMM_SECRET and RMM_RELAY in"
    echo "              ~/.config/rmm-agent/env, then"
    echo "              systemctl --user enable --now rmm-agent"
fi
exit 0
EOF
chmod 0755 "$STAGE/DEBIAN/postinst"

cat > "$STAGE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
# Stop the unattended service before the files go, so it does not linger
# pointing at a binary that no longer exists.
if [ "$1" = "remove" ] || [ "$1" = "upgrade" ]; then
    for user_bus in /run/user/*/bus; do
        [ -S "$user_bus" ] || continue
        uid="$(basename "$(dirname "$user_bus")")"
        su -s /bin/sh -c "XDG_RUNTIME_DIR=/run/user/$uid systemctl --user stop rmm-agent" \
            "$(id -nu "$uid" 2>/dev/null || echo root)" 2>/dev/null || true
    done
fi
exit 0
EOF
chmod 0755 "$STAGE/DEBIAN/prerm"

OUT="$ROOT/agent/dist/${PACKAGE}_${VERSION}_${ARCH}.deb"
fakeroot dpkg-deb --build "$STAGE" "$OUT" >/dev/null
echo "built: $OUT"
dpkg-deb --info "$OUT" | sed -n '1,12p'
