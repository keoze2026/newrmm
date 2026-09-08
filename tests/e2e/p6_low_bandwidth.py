"""Acceptance section 8: usable on a constrained link.

    "Live view sustains a smooth frame rate and responsive control on a normal
     broadband link; remains usable on ~1 Mbps."

Section 10 names the mitigation: "Changed-region streaming, adaptive
quality/frame-rate." This measures both against a real agent capturing the real
desktop, and checks the stream actually fits inside a 1 Mbps budget rather than
assuming it does.

    python tests/e2e/p6_low_bandwidth.py     # relay must be running on :8000
"""
import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import websockets

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"

KEYFRAME = 0x00
TILE_FRAME = 0x01

BUDGET_KBPS = 1000  # "~1 Mbps"

results: list[tuple[bool, str]] = []


def step(name, ok, extra=""):
    results.append((bool(ok), name))
    print(("PASS  " if ok else "FAIL  ") + name + (f"\n      {extra}" if extra else ""))


class Meter:
    """Counts what the operator actually receives."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.bytes = 0
        self.frames = 0
        self.keyframes = 0
        self.empty = 0
        self.tiles = 0

    def record(self, payload: bytes) -> None:
        self.bytes += len(payload)
        self.frames += 1
        if not payload:
            return
        if payload[0] == KEYFRAME:
            self.keyframes += 1
        elif payload[0] == TILE_FRAME and len(payload) >= 7:
            count = int.from_bytes(payload[5:7], "little")
            self.tiles += count
            if count == 0:
                self.empty += 1

    @property
    def elapsed(self) -> float:
        return max(0.001, time.monotonic() - self.started)

    @property
    def kbps(self) -> float:
        return self.bytes * 8 / self.elapsed / 1000

    @property
    def fps(self) -> float:
        return self.frames / self.elapsed


async def measure(socket, seconds: float) -> Meter:
    meter = Meter()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            message = await asyncio.wait_for(socket.recv(), timeout=deadline - time.monotonic())
        except (asyncio.TimeoutError, ValueError):
            break
        if isinstance(message, bytes):
            meter.record(message)
    return meter


async def run_agent(code: str, extra: list[str], log: Path) -> subprocess.Popen:
    handle = log.open("w")
    return subprocess.Popen(
        [sys.executable, "-m", "rmm_agent", "join", "--relay", WS, "--code", code,
         "--no-tray", "--no-input", "--auto-consent", *extra],
        cwd="agent", stdout=handle, stderr=subprocess.STDOUT, text=True,
        start_new_session=True,
    )


async def wait_for_guest(http, headers, session) -> bool:
    for _ in range(50):
        await asyncio.sleep(0.5)
        live = (await http.get(f"/sessions/{session['id']}", headers=headers)).json()
        if live.get("guest_connected"):
            return True
    return False


async def main() -> int:
    log_dir = Path(tempfile.mkdtemp(prefix="rmm-p6-"))

    async with httpx.AsyncClient(base_url=BASE, timeout=20) as http:
        token = (await http.post("/auth/login", json={
            "email": "admin@example.com", "password": "ChangeMe123!"})).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # ------------------------------------------------ a normal link
        session = (await http.post("/sessions", json={"mode": "attended"},
                                   headers=headers)).json()
        agent = await run_agent(session["code"], ["--fps", "10", "--quality", "60"],
                                log_dir / "broadband.log")
        try:
            if not await wait_for_guest(http, headers, session):
                step("the agent joined", False)
                return 1
            step("the agent joined, capturing the real desktop", True)

            async with websockets.connect(
                f"{WS}/ws/operator/{session['code']}?token={token}", max_size=None
            ) as op:
                await asyncio.sleep(1.0)
                broadband = await measure(op, 6.0)

            step("frames arrive on a normal link",
                 broadband.frames >= 20, f"{broadband.frames} frames in 6s")
            step("a still desktop is not re-sent every frame",
                 broadband.keyframes < broadband.frames / 4,
                 f"{broadband.keyframes} keyframes out of {broadband.frames} frames")
            print(f"      broadband: {broadband.fps:.1f} fps, {broadband.kbps:.0f} kbps, "
                  f"{broadband.keyframes} keyframes, {broadband.empty} unchanged, "
                  f"{broadband.tiles} tiles")
        finally:
            agent.terminate()
            try:
                agent.wait(timeout=10)
            except subprocess.TimeoutExpired:
                agent.kill()

        # ------------------------------------------- a ~1 Mbps budget
        session = (await http.post("/sessions", json={"mode": "attended"},
                                   headers=headers)).json()
        agent = await run_agent(
            session["code"],
            ["--fps", "10", "--quality", "60", "--budget-kbps", str(BUDGET_KBPS)],
            log_dir / "constrained.log",
        )
        try:
            if not await wait_for_guest(http, headers, session):
                step("the agent joined under a bandwidth budget", False)
                return 1
            step("the agent joined under a bandwidth budget", True)

            async with websockets.connect(
                f"{WS}/ws/operator/{session['code']}?token={token}", max_size=None
            ) as op:
                # Let the rate controller settle before measuring.
                await asyncio.sleep(2.0)
                constrained = await measure(op, 10.0)

            print(f"      constrained: {constrained.fps:.1f} fps, {constrained.kbps:.0f} kbps, "
                  f"{constrained.keyframes} keyframes, {constrained.empty} unchanged")

            step("the stream fits inside a 1 Mbps link",
                 constrained.kbps <= BUDGET_KBPS,
                 f"{constrained.kbps:.0f} kbps against a {BUDGET_KBPS} kbps budget")

            step("it is still a live stream, not a slideshow",
                 constrained.fps >= 4, f"{constrained.fps:.1f} fps")

            step("frames keep arriving for the whole measurement",
                 constrained.frames >= 40, f"{constrained.frames} frames in 10s")
        finally:
            agent.terminate()
            try:
                agent.wait(timeout=10)
            except subprocess.TimeoutExpired:
                agent.kill()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} low-bandwidth checks passed")
    return 0 if passed == len(results) else 1


raise SystemExit(asyncio.run(main()))
