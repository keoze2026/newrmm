"""Acceptance section 8: the agent reconnects after a drop.

    "Endpoint agent stays connected across long sessions and reconnects
     automatically after drops."

The backoff has existed since Phase 2 and nothing ever exercised it. This
restarts the relay out from under a running agent - every socket goes away at
once, which is what a network blip or a relay redeploy looks like from the
endpoint - and checks the agent comes back by itself and streams again, with
nobody touching the endpoint.

    python tests/e2e/p6_reconnect.py      # relay must be running on :8000
"""
import asyncio
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import websockets

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[2]

results: list[tuple[bool, str]] = []


def step(name, ok, extra=""):
    results.append((bool(ok), name))
    print(("PASS  " if ok else "FAIL  ") + name + (f"\n      {extra}" if extra else ""))


def relay_pids() -> list[int]:
    found = subprocess.run(
        ["pgrep", "-f", "[u]vicorn app.main"], capture_output=True, text=True
    )
    return [int(line) for line in found.stdout.split() if line.isdigit()]


def start_relay(log_dir: str) -> None:
    """Start the relay detached, with its output going to a file.

    Capturing a child's output through a pipe makes the caller wait until every
    process holding that pipe exits - and a relay never does - so the relay is
    given a file instead and left running on its own.
    """
    out = open(Path(log_dir) / "reconnect-relay.log", "ab")
    subprocess.Popen(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "uvicorn", "app.main:app",
         "--host", "0.0.0.0", "--port", "8000"],
        cwd=str(ROOT / "relay"),
        env={**os.environ, "LOG_DIR": log_dir},
        stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


async def relay_healthy(timeout=60.0) -> bool:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=5) as probe:
        while time.monotonic() < deadline:
            try:
                if (await probe.get(f"{BASE}/health")).status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False


async def guest_connected(session_id: str, headers: dict) -> bool:
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as http:
        try:
            live = (await http.get(f"/sessions/{session_id}", headers=headers)).json()
        except Exception:
            return False
    return bool(live.get("guest_connected"))


async def wait_for_guest(session_id, headers, want: bool, timeout=60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await guest_connected(session_id, headers) == want:
            return True
        await asyncio.sleep(0.5)
    return False


async def login() -> str:
    async with httpx.AsyncClient(base_url=BASE, timeout=20) as http:
        response = await http.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "ChangeMe123!"},
        )
    return response.json()["access_token"]


async def count_frames(token: str, code: str, seconds=4.0) -> int:
    """Attach as an operator would and count the frames that arrive."""
    frames = 0
    try:
        async with websockets.connect(
            f"{WS}/ws/operator/{code}?token={token}", max_size=None
        ) as op:
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    message = await asyncio.wait_for(
                        op.recv(), timeout=max(0.1, deadline - time.monotonic())
                    )
                except (asyncio.TimeoutError, ValueError):
                    break
                if isinstance(message, bytes):
                    frames += 1
    except Exception:
        pass
    return frames


async def main() -> int:
    log_path = Path(tempfile.mkstemp(prefix="rmm-reconnect-", suffix=".log")[1])
    log_file = log_path.open("w")

    def agent_log() -> str:
        log_file.flush()
        try:
            return log_path.read_text()
        except OSError:
            return ""

    token = await login()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(base_url=BASE, timeout=20) as http:
        session = (await http.post("/sessions", json={"mode": "attended"},
                                   headers=headers)).json()
    code, session_id = session["code"], session["id"]

    agent = subprocess.Popen(
        [sys.executable, "-m", "rmm_agent", "join", "--relay", WS, "--code", code,
         "--synthetic", "--no-tray", "--no-input", "--auto-consent",
         "--blank-no-input-block", "--blank-watchdog", "15", "--fps", "5"],
        cwd=str(ROOT / "agent"), stdout=log_file, stderr=subprocess.STDOUT,
        text=True, start_new_session=True,
    )

    try:
        step("the agent joined", await wait_for_guest(session_id, headers, True))
        before = await count_frames(token, code)
        step("frames arrive before the drop", before >= 2, f"{before} frames")

        # Drop every socket at once by restarting the relay. From the endpoint
        # this is indistinguishable from the network going away.
        marker = len(agent_log())
        pids = relay_pids()
        step("the relay was running", bool(pids), str(pids))
        for pid in pids:
            os.kill(pid, signal.SIGTERM)
        await asyncio.sleep(3)
        step("the connection was dropped", not await relay_healthy(timeout=5))

        start_relay(str(log_path.parent))
        step("the relay came back", await relay_healthy())

        # A new token: the old relay process is gone, though the secret is the
        # same, so this is really about the relay being ready to answer.
        token = await login()
        headers = {"Authorization": f"Bearer {token}"}

        came_back = await wait_for_guest(session_id, headers, True, timeout=90)
        step("the agent reconnected without being touched", came_back,
             agent_log()[marker:][-400:])

        after = await count_frames(token, code)
        step("frames arrive again after the reconnect", after >= 2, f"{after} frames")

        step("the agent survived rather than exiting", agent.poll() is None)

        reconnect_log = agent_log()[marker:]
        step("the agent recorded the drop and the retry",
             "reconnecting" in reconnect_log or "connection lost" in reconnect_log,
             reconnect_log[-400:] or "nothing logged")
    finally:
        if agent.poll() is None:
            agent.terminate()
            try:
                agent.wait(timeout=10)
            except subprocess.TimeoutExpired:
                agent.kill()
        log_file.close()
        log_path.unlink(missing_ok=True)

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} reconnect checks passed")
    return 0 if passed == len(results) else 1


raise SystemExit(asyncio.run(main()))
