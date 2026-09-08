"""Phase 5: the privacy blank, verified against real screen capture.

The spec's P5 checkpoint on Linux is "guest-lock verified on Linux; agent stays
online across toggles". So this drives a real agent capturing the real desktop
and checks the frames the operator receives actually go black when the blank is
on, come back when it is off, and that the agent survives the toggling.

Your screen goes black for a few seconds while this runs. Local input is NOT
blocked here - that path is checked separately in test_privacy_input_block.py,
in a throwaway process with a hard watchdog, so a failure cannot lock the
machine.

    python tests/e2e/p5_privacy_blank.py       # relay must be running on :8000
"""
import asyncio
import io
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import websockets
from PIL import Image

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"

results: list[tuple[bool, str]] = []


def step(name, ok, extra=""):
    results.append((bool(ok), name))
    print(("PASS  " if ok else "FAIL  ") + name + (f"\n      {extra}" if extra else ""))


def brightness(jpeg: bytes) -> float:
    """Mean luminance 0-255 of a frame."""
    image = Image.open(io.BytesIO(jpeg)).convert("L").resize((64, 64))
    pixels = list(image.convert("L").tobytes())
    return sum(pixels) / len(pixels)


async def sample_frames(socket, count=4, timeout=15.0) -> list[bytes]:
    frames: list[bytes] = []
    deadline = time.monotonic() + timeout
    while len(frames) < count and time.monotonic() < deadline:
        try:
            message = await asyncio.wait_for(socket.recv(), timeout=deadline - time.monotonic())
        except (asyncio.TimeoutError, ValueError):
            break
        if isinstance(message, bytes):
            frames.append(message)
    return frames


async def wait_for_blank_state(socket, want_active: bool, timeout=20.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            message = await asyncio.wait_for(socket.recv(), timeout=deadline - time.monotonic())
        except (asyncio.TimeoutError, ValueError):
            return None
        if isinstance(message, bytes):
            continue
        payload = json.loads(message)
        if payload.get("type") == "blank" and payload.get("action") == "state":
            if bool(payload.get("active")) == want_active:
                return payload
    return None


async def main() -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=20) as http:
        token = (await http.post("/auth/login", json={
            "email": "admin@example.com", "password": "ChangeMe123!"})).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        session = (await http.post("/sessions", json={"mode": "attended"},
                                   headers=headers)).json()
        code = session["code"]

        # Log to a file so the agent's output can be read while it is running,
        # rather than only after it has been killed.
        log_path = Path(tempfile.mkstemp(prefix="rmm-p5-", suffix=".log")[1])
        log_file = log_path.open("w")
        agent = subprocess.Popen(
            [sys.executable, "-m", "rmm_agent", "join", "--relay", WS, "--code", code,
             "--no-tray", "--no-input", "--auto-consent",
             "--blank-no-input-block", "--blank-watchdog", "45",
             "--fps", "5", "--quality", "45"],
            cwd="agent", stdout=log_file, stderr=subprocess.STDOUT,
            text=True, start_new_session=True,
        )

        def agent_log() -> str:
            log_file.flush()
            try:
                return log_path.read_text()
            except OSError:
                return ""
        try:
            live = {}
            for _ in range(50):
                await asyncio.sleep(0.5)
                live = (await http.get(f"/sessions/{session['id']}", headers=headers)).json()
                if live.get("guest_connected"):
                    break
            step("the agent joined with real screen capture", live.get("guest_connected"))
            if not live.get("guest_connected"):
                return 1

            async with websockets.connect(f"{WS}/ws/operator/{code}?token={token}",
                                          max_size=None) as op:
                # --------------------------------------------- before blanking
                frames = await sample_frames(op)
                step("the operator receives frames of the desktop", len(frames) >= 2,
                     f"{len(frames)} frames")
                if not frames:
                    return 1
                desktop = brightness(frames[-1])
                step("the desktop is not already black", desktop > 8,
                     f"mean luminance {desktop:.1f}")

                # ------------------------------------------------- blank on
                await op.send(json.dumps({"type": "blank", "on": True}))
                state = await wait_for_blank_state(op, want_active=True)
                step("the endpoint reports the blank is on", state is not None, str(state))
                if state is None:
                    return 1
                step("the endpoint reports guest-lock, not capture-exclusion",
                     state.get("mode") == "guest-lock",
                     f"mode={state.get('mode')} (Linux has no universal capture-exclusion)")

                await asyncio.sleep(1.5)
                blanked_frames = await sample_frames(op, count=4)
                step("the agent keeps streaming while blanked", len(blanked_frames) >= 2,
                     f"{len(blanked_frames)} frames")
                blanked = brightness(blanked_frames[-1]) if blanked_frames else 255
                step("the captured screen is black while blanked", blanked < 6,
                     f"mean luminance {blanked:.1f} (was {desktop:.1f})")

                # ------------------------------------------------ blank off
                await op.send(json.dumps({"type": "blank", "on": False}))
                state = await wait_for_blank_state(op, want_active=False)
                step("the endpoint reports the blank is off", state is not None, str(state))

                await asyncio.sleep(1.5)
                restored_frames = await sample_frames(op, count=4)
                restored = brightness(restored_frames[-1]) if restored_frames else 0
                step("the desktop comes back when the blank is released",
                     restored > 8, f"mean luminance {restored:.1f}")

                # --------------------------------- agent survives toggling
                ok = True
                for _ in range(3):
                    await op.send(json.dumps({"type": "blank", "on": True}))
                    ok = ok and await wait_for_blank_state(op, True) is not None
                    await op.send(json.dumps({"type": "blank", "on": False}))
                    ok = ok and await wait_for_blank_state(op, False) is not None
                step("the blank survives repeated toggling", ok)

                still = (await http.get(f"/sessions/{session['id']}", headers=headers)).json()
                step("the agent stays online across the toggles",
                     still.get("guest_connected") is True and agent.poll() is None)

                final = await sample_frames(op, count=2)
                step("frames still flow after all the toggling", len(final) >= 1)

                # --------------------- a blank must not outlive its session
                await op.send(json.dumps({"type": "blank", "on": True}))
                await wait_for_blank_state(op, True)
                mark = len(agent_log())

            # The operator socket is closed; now end the session outright, with
            # the blank still on and the agent still running.
            await http.patch(f"/sessions/{session['id']}", json={"state": "ended"},
                             headers=headers)

            released = False
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                # Only what the agent logged AFTER the blank was switched on
                # counts, or earlier toggling would pass this by accident.
                if "releasing the privacy blank" in agent_log()[mark:]:
                    released = True
                    break
                await asyncio.sleep(0.5)

            step("the blank is released when the session ends, not left up",
                 released, agent_log()[mark:][-400:] or "no new agent output")

            # Ending the session should retire the agent cleanly, not leave it
            # reconnecting forever to a session that no longer exists.
            exited = False
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if agent.poll() is not None:
                    exited = True
                    break
                await asyncio.sleep(0.5)
            step("the agent shuts down cleanly instead of reconnecting forever",
                 exited and agent.returncode == 0,
                 f"exited={exited} returncode={agent.returncode}")
            step("the agent said why it stopped",
                 "the session is over" in agent_log()[mark:],
                 agent_log()[mark:][-300:])
        finally:
            if agent.poll() is None:
                agent.terminate()
                try:
                    agent.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    agent.kill()
            try:
                log_file.close()
                log_path.unlink(missing_ok=True)
            except OSError:
                pass

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} privacy blank checks passed")
    return 0 if passed == len(results) else 1


raise SystemExit(asyncio.run(main()))
