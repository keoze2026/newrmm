"""Phase 4 tools against a real agent: terminal, file transfer, clipboard.

Connects to the relay as an operator would, drives each tool over the real
session transport, and checks the endpoint actually did the work - a file that
lands on disk, a command whose output comes back, a clipboard that changes.

    python tests/e2e/p4_tools.py          # relay must be running on :8000
"""
import asyncio
import base64
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
AGENT = [sys.executable, "-m", "rmm_agent", "join", "--relay", WS,
         "--synthetic", "--no-tray", "--no-input", "--auto-consent", "--fps", "4"]

results: list[tuple[bool, str]] = []


def step(name, ok, extra=""):
    results.append((bool(ok), name))
    print(("PASS  " if ok else "FAIL  ") + name + (f"\n      {extra}" if extra and not ok else ""))


async def collect(socket, want, timeout=12.0, until=None):
    """Gather JSON messages of a given type until `until` says stop."""
    got = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw = await asyncio.wait_for(socket.recv(), timeout=deadline - time.monotonic())
        except (asyncio.TimeoutError, ValueError):
            break
        if isinstance(raw, bytes):
            continue
        message = json.loads(raw)
        if message.get("type") != want:
            continue
        got.append(message)
        if until is None or until(message, got):
            break
    return got


async def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="rmm-p4-"))

    async with httpx.AsyncClient(base_url=BASE, timeout=15) as http:
        token = (await http.post("/auth/login", json={
            "email": "admin@example.com", "password": "ChangeMe123!"})).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        session = (await http.post("/sessions", json={"mode": "attended"},
                                   headers=headers)).json()
        code = session["code"]

        agent = subprocess.Popen(
            AGENT + ["--code", code],
            cwd="agent", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, start_new_session=True,
        )
        try:
            # Wait for the agent to attach and consent.
            for _ in range(40):
                await asyncio.sleep(0.5)
                live = (await http.get(f"/sessions/{session['id']}", headers=headers)).json()
                if live["guest_connected"]:
                    break
            step("the agent joined the session", live["guest_connected"], str(live["consent_state"]))
            if not live["guest_connected"]:
                return 1

            async with websockets.connect(f"{WS}/ws/operator/{code}?token={token}",
                                          max_size=None) as op:

                # ---------------------------------------------------- terminal
                await op.send(json.dumps({"type": "terminal", "action": "open",
                                          "cols": 100, "rows": 30}))
                opened = await collect(op, "terminal", 10,
                                       lambda m, _: m.get("action") == "opened")
                step("the terminal opens on the endpoint",
                     any(m.get("action") == "opened" for m in opened), str(opened))

                marker = "RMM_TERMINAL_OK_4711"
                await op.send(json.dumps({"type": "terminal", "action": "input",
                                          "data": f"echo {marker}\n"}))
                out = await collect(op, "terminal", 12,
                                    lambda m, got: marker in "".join(
                                        x.get("data", "") for x in got if x.get("action") == "output"))
                text = "".join(m.get("data", "") for m in out if m.get("action") == "output")
                step("a command runs and its output comes back", marker in text,
                     repr(text[-200:]))

                # Set a variable in one command and read it back in the next.
                # The second command's echo does not contain the value, so a
                # match proves the shell really kept state.
                await op.send(json.dumps({"type": "terminal", "action": "input",
                                          "data": "RMM_STATE=kept_across_commands\n"}))
                await asyncio.sleep(0.6)
                await op.send(json.dumps({"type": "terminal", "action": "input",
                                          "data": 'echo "state is $RMM_STATE"\n'}))
                out = await collect(op, "terminal", 12,
                                    lambda m, got: "state is kept_across_commands" in "".join(
                                        x.get("data", "") for x in got if x.get("action") == "output"))
                text = "".join(m.get("data", "") for m in out if m.get("action") == "output")
                step("the shell keeps state between commands",
                     "state is kept_across_commands" in text, repr(text[-200:]))

                await op.send(json.dumps({"type": "terminal", "action": "close"}))
                closed = await collect(op, "terminal", 8,
                                       lambda m, _: m.get("action") == "closed")
                step("the terminal closes", any(m.get("action") == "closed" for m in closed))

                # ------------------------------------------------------- files
                await op.send(json.dumps({"type": "files", "action": "list",
                                          "path": str(workdir)}))
                listed = await collect(op, "files", 10, lambda m, _: m.get("action") == "list")
                step("an empty directory lists cleanly",
                     listed and listed[0].get("entries") == [] and not listed[0].get("error"),
                     str(listed))

                # Send a file to the endpoint.
                payload = os.urandom(400_000)
                target = workdir / "sent-to-endpoint.bin"
                chunk = 256 * 1024
                for offset in range(0, len(payload), chunk):
                    block = payload[offset:offset + chunk]
                    await op.send(json.dumps({
                        "type": "files", "action": "put", "path": str(target),
                        "data": base64.b64encode(block).decode(),
                        "final": offset + chunk >= len(payload),
                    }))
                received = await collect(op, "files", 20,
                                         lambda m, _: m.get("action") in ("received", "error"))
                landed = target.exists() and target.read_bytes() == payload
                step("a file sent to the endpoint lands byte-for-byte on disk", landed,
                     str(received))

                # Retrieve a file from the endpoint.
                source = workdir / "from-endpoint.txt"
                source.write_text("retrieved from the endpoint\n" * 500)
                await op.send(json.dumps({"type": "files", "action": "get",
                                          "path": str(source)}))
                chunks = await collect(op, "files", 20,
                                       lambda m, _: m.get("action") == "chunk" and m.get("final"))
                data = b"".join(base64.b64decode(m["data"])
                                for m in chunks if m.get("action") == "chunk")
                step("a file retrieved from the endpoint arrives intact",
                     data == source.read_bytes(), f"{len(data)} vs {source.stat().st_size}")

                await op.send(json.dumps({"type": "files", "action": "list",
                                          "path": str(workdir)}))
                listed = await collect(op, "files", 10, lambda m, _: m.get("action") == "list")
                names = {e["name"] for e in listed[0]["entries"]} if listed else set()
                step("both files now show in the listing",
                     {"sent-to-endpoint.bin", "from-endpoint.txt"} <= names, str(names))

                await op.send(json.dumps({"type": "files", "action": "get",
                                          "path": str(workdir / "does-not-exist")}))
                errors = await collect(op, "files", 10,
                                       lambda m, _: m.get("action") == "error")
                step("a missing file reports an error rather than hanging", bool(errors))

                await op.send(json.dumps({"type": "files", "action": "list",
                                          "path": "/root/definitely-not-readable"}))
                listed = await collect(op, "files", 10, lambda m, _: m.get("action") == "list")
                step("an unreadable directory reports an error rather than crashing",
                     listed and bool(listed[0].get("error")), str(listed))

                # --------------------------------------------------- clipboard
                phrase = f"clipboard-sync-{int(time.time())}"
                await op.send(json.dumps({"type": "clipboard", "action": "set",
                                          "text": phrase}))
                acked = await collect(op, "clipboard", 12,
                                      lambda m, _: m.get("action") == "set")
                step("the endpoint clipboard accepts text from the operator",
                     acked and acked[0].get("ok"), str(acked))

                await op.send(json.dumps({"type": "clipboard", "action": "get"}))
                back = await collect(op, "clipboard", 12,
                                     lambda m, _: m.get("action") == "text")
                step("reading the endpoint clipboard returns what was written",
                     back and back[0].get("text") == phrase, str(back))
        finally:
            agent.terminate()
            try:
                agent.wait(timeout=10)
            except subprocess.TimeoutExpired:
                agent.kill()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} Phase 4 tool checks passed")
    return 0 if passed == len(results) else 1


raise SystemExit(asyncio.run(main()))
