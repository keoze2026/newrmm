#!/usr/bin/env bash
# Build the native macOS capture module. Run this on a Mac with Xcode installed.
#
#   ./build.sh
#
# Produces libRMMCapture.dylib beside this script, which rmm_capture_macos.py
# loads with ctypes.
set -euo pipefail

cd "$(dirname "$0")"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This module builds only on macOS - it needs ScreenCaptureKit." >&2
    exit 2
fi

if ! command -v swift >/dev/null; then
    echo "swift not found. Install Xcode or the Command Line Tools." >&2
    exit 2
fi

swift build -c release

built="$(swift build -c release --show-bin-path)/libRMMCapture.dylib"
if [[ ! -f "$built" ]]; then
    echo "build finished but $built is missing" >&2
    exit 1
fi

cp "$built" ./libRMMCapture.dylib
echo "built: $(pwd)/libRMMCapture.dylib"
echo
echo "Screen Recording permission is required, and macOS only applies it after"
echo "the agent is restarted. Check it with: python -m rmm_agent status"
