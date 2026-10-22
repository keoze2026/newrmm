"""Always-on: allow once, and the computer stays reachable with no prompt.

Drives a real agent and a real operator connection against a live relay:

  1. an attended session is joined and consented (test consent, no window);
  2. the session is enrolled as a standing device, as the agent does when the
     person chooses "Always allow";
  3. that attended agent is stopped, as if the computer had been switched off;
  4. `rmm-agent resume` starts, as it does at login, and must come online by
     itself with NO consent window;
  5. an operator opens the session: frames must arrive with no prompt;
  6. the operator leaves: the screen must stop being shared, but the device must
     stay online;
  7. the operator opens it again: frames arrive again.

    python tests/e2e/p7_always_on.py

Expects the relay on :8000. Uses a throwaway state folder so the real agent's
enrolment is never touched, and a generated screen.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import websockets

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"
failures = 0


def step(name: str, ok: bool, detail: str = "") -> bool:
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures += 1
    return ok


async def frames_for(socket, seconds: float) -> int:
    count = 0
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            message = await asyncio.wait_for(socket.recv(), timeout=end - time.monotonic())
        except asyncio.TimeoutError:
            break
        if isinstance(message, bytes):
            count += 1
    return count


def agent(args, state, log):
    env = dict(os.environ, XDG_STATE_HOME=state, PYTHONUNBUFFERED="1")
    return subprocess.Popen(
        [sys.executable, "-m", "rmm_agent", *args], cwd="agent", env=env,
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )


async def wait_for(check, seconds=20.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if await check():
            return True
        await asyncio.sleep(0.4)
    return False


async def main() -> int:
    state = tempfile.mkdtemp(prefix="rmm-p7-")
    log = open(Path(state) / "agents.log", "w")
    attended = device = None
    async with httpx.AsyncClient(base_url=BASE, timeout=20) as http:
        token = (await http.post("/auth/login", json={
            "email": "admin@example.com", "password": "ChangeMe123!"})).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        session = (await http.post("/sessions", json={"mode": "attended"}, headers=headers)).json()
        code = session["code"]

        async def get():
            return (await http.get(f"/sessions/{session['id']}", headers=headers)).json()

        try:
            # 1 ------------------------------------------------------ attended join
            attended = agent(["join", "--relay", WS, "--code", code, "--no-tray", "--no-input",
                              "--synthetic", "--auto-consent"], state, log)

            async def consented():
                s = await get()
                return s["guest_connected"] and s["consent_state"] == "granted"

            if not step("an attended agent joins and its person consents", await wait_for(consented)):
                return 1

            # 2 -------------------------------------------------------------- enrol
            enrolled = await http.post("/connector/enrol",
                                       json={"code": code, "name": "e2e laptop", "os": "linux"})
            step("choosing Always allow enrols the computer", enrolled.status_code == 201,
                 str(enrolled.status_code))
            if enrolled.status_code != 201:
                return 1
            creds = enrolled.json()
            now = await get()
            step("the session became a standing one with no expiry",
                 now["mode"] == "unattended" and now["device_id"] == creds["device_id"]
                 and now["expires_at"] is None)

            # 3 ------------------------------------------- the computer is switched off
            attended.terminate()
            attended.wait(timeout=15)
            attended = None
            folder = Path(state) / "RMMAgent"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "enrolment.json").write_text(json.dumps(
                {"device_id": creds["device_id"], "secret": creds["secret"], "relay_url": WS}))

            async def off():
                return not (await get())["guest_connected"]

            step("with the computer off, the session shows nobody connected", await wait_for(off))

            # 4 ------------------------------------------- it starts again, by itself
            device = agent(["resume", "--no-tray", "--synthetic"], state, log)

            async def online():
                return (await get())["device_online"] is True

            if not step("after a restart it comes online by itself, with no prompt",
                        await wait_for(online, 25)):
                return 1

            # 5 ---------------------------------------------- an operator opens it
            async with websockets.connect(f"{WS}/ws/operator/{code}?token={token}",
                                          max_size=None) as op:
                got = await frames_for(op, 10)
                step("opening it starts a session with no window to answer", got >= 3,
                     f"{got} frames")
                live = await get()
                step("the console now shows the guest joined", live["guest_connected"] is True)

            # 6 ------------------------------------------------ the operator leaves
            async def stopped():
                return not (await get())["guest_connected"]

            step("when the operator leaves, the screen stops being shared",
                 await wait_for(stopped, 15))
            step("and the computer is still online", (await get())["device_online"] is True)

            # 7 ---------------------------------------------------- and comes back
            async with websockets.connect(f"{WS}/ws/operator/{code}?token={token}",
                                          max_size=None) as op:
                got = await frames_for(op, 10)
                step("opening it again starts a new session", got >= 3, f"{got} frames")

            step("the agent kept running the whole time", device.poll() is None)
            return 1 if failures else 0
        finally:
            for process in (attended, device):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
            await http.delete(f"/sessions/{session['id']}", headers=headers)
            log.close()
            print(f"agent log: {Path(state) / 'agents.log'}")


if __name__ == "__main__":
    code = asyncio.run(main())
    print(f"\n{'all' if not failures else 'not all'} always-on checks passed ({failures} failed)")
    sys.exit(code)
