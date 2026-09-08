"""Phase 2 session-flow checks against a live relay.

Covers the consent gate and unattended device authentication - the parts of
Phase 2 that a browser test cannot reach, because they are about what the relay
refuses to do.

    python tests/e2e/p2_session_flow.py        # relay must be on :8000
"""
import asyncio
import json
import sys

import httpx
import websockets

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"
results = []

def step(name, ok, extra=""):
    results.append((ok, name))
    print(("PASS  " if ok else "FAIL  ") + name + (f"\n      {extra}" if extra and not ok else ""))

async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as http:
        token = (await http.post("/auth/login", json={"email": "admin@example.com", "password": "ChangeMe123!"})).json()["access_token"]
        H = {"Authorization": f"Bearer {token}"}

        async def make():
            return (await http.post("/sessions", json={"mode": "attended"}, headers=H)).json()

        async def get(sid):
            return (await http.get(f"/sessions/{sid}", headers=H)).json()

        # ---- 1. attach without answering consent: nothing is shared
        s = await make()
        async with websockets.connect(f"{WS}/ws/guest/{s['code']}") as g:
            await g.send(json.dumps({"host_name": "test-endpoint", "system_info": {"os": "Windows"}, "monitors": [], "agent_version": "0.2.0"}))
            await asyncio.sleep(0.8)
            after = await get(s["id"])
            step("attaching does not join the session until consent is answered",
                 after["consent_state"] == "pending" and after["guest_connected"] is False and after["state"] == "pending",
                 str(after))
            step("the endpoint's details are reported on attach",
                 after["host_name"] == "test-endpoint" and after["agent_version"] == "0.2.0", str(after))

            # ---- 2. frames sent before consent are dropped by the relay
            got = []
            async def operator():
                async with websockets.connect(f"{WS}/ws/operator/{s['code']}?token={token}") as o:
                    try:
                        while True:
                            msg = await asyncio.wait_for(o.recv(), timeout=1.2)
                            if isinstance(msg, bytes):
                                got.append(msg)
                    except asyncio.TimeoutError:
                        pass
            task = asyncio.create_task(operator())
            await asyncio.sleep(0.4)
            for _ in range(5):
                await g.send(b"\xff\xd8\xff" + b"not-a-real-frame" * 20)
                await asyncio.sleep(0.05)
            await task
            step("frames sent before consent never reach the operator", got == [], f"{len(got)} frames leaked")

            # ---- 3. granting consent joins the session
            await g.send(json.dumps({"type": "consent", "granted": True}))
            await asyncio.sleep(0.8)
            after = await get(s["id"])
            step("granting consent joins the session and makes it active",
                 after["consent_state"] == "granted" and after["guest_connected"] is True and after["state"] == "active",
                 str(after))

            # ---- 4. frames now flow
            got2 = []
            async def operator2():
                async with websockets.connect(f"{WS}/ws/operator/{s['code']}?token={token}") as o:
                    try:
                        while len(got2) < 3:
                            msg = await asyncio.wait_for(o.recv(), timeout=2.0)
                            if isinstance(msg, bytes):
                                got2.append(msg)
                    except asyncio.TimeoutError:
                        pass
            task = asyncio.create_task(operator2())
            await asyncio.sleep(0.4)
            for _ in range(6):
                await g.send(b"\xff\xd8\xff" + b"frame-payload" * 20)
                await asyncio.sleep(0.08)
            await task
            step("frames reach the operator once consent is granted", len(got2) >= 3, f"got {len(got2)}")

        # ---- 5. consent denied
        s2 = await make()
        async with websockets.connect(f"{WS}/ws/guest/{s2['code']}") as g:
            await g.send(json.dumps({"host_name": "denier", "system_info": {}, "monitors": []}))
            await asyncio.sleep(0.4)
            await g.send(json.dumps({"type": "consent", "granted": False}))
            await asyncio.sleep(0.8)
        after = await get(s2["id"])
        step("denying consent leaves the session unjoined",
             after["consent_state"] == "denied" and after["guest_connected"] is False, str(after))

        logs = (await http.get(f"/sessions/{s2['id']}/logs", headers=H)).json()
        actions = [e["action"] for e in logs]
        step("the denial is on the audit trail", "session.consent_denied" in actions, str(actions))

        logs1 = (await http.get(f"/sessions/{s['id']}/logs", headers=H)).json()
        a1 = [e["action"] for e in logs1]
        step("attach, consent and join are all audited",
             {"session.guest_attached", "session.consent_granted", "session.guest_joined"} <= set(a1), str(a1))

        # ---- 6. unattended sessions demand device credentials
        dev = (await http.post("/devices", json={"name": "Bench Windows", "os": "windows"}, headers=H)).json()
        s3 = (await http.post("/sessions", json={"mode": "unattended", "device_id": dev["id"]}, headers=H)).json()
        refused = False
        try:
            async with websockets.connect(f"{WS}/ws/guest/{s3['code']}") as g:
                await g.send(json.dumps({"host_name": "impostor", "system_info": {}, "monitors": []}))
                await asyncio.wait_for(g.recv(), timeout=2)
        except Exception:
            refused = True
        step("an unattended session refuses a guest with no device credentials", refused)

        accepted = False
        try:
            url = f"{WS}/ws/guest/{s3['code']}?device_id={dev['id']}&secret={dev['enrollment_secret']}"
            async with websockets.connect(url) as g:
                await g.send(json.dumps({"host_name": "Bench Windows", "system_info": {"os": "Windows"}, "monitors": []}))
                await asyncio.sleep(0.6)
                accepted = (await get(s3["id"]))["host_name"] == "Bench Windows"
        except Exception:
            accepted = False
        step("the enrolled device is accepted with its secret", accepted)

        bad = False
        try:
            url = f"{WS}/ws/guest/{s3['code']}?device_id={dev['id']}&secret=wrong-secret"
            async with websockets.connect(url) as g:
                await g.send(json.dumps({"host_name": "x", "system_info": {}, "monitors": []}))
                await asyncio.wait_for(g.recv(), timeout=2)
        except Exception:
            bad = True
        step("a wrong device secret is refused", bad)

        # ---- 7. device presence socket
        online = False
        async with websockets.connect(f"{WS}/ws/device/{dev['id']}?secret={dev['enrollment_secret']}") as d:
            await d.send(json.dumps({"type": "heartbeat"}))
            await asyncio.sleep(0.6)
            devices = (await http.get("/devices", headers=H)).json()
            online = any(x["id"] == dev["id"] and x["status"] == "online" for x in devices)
        step("an enrolled device reports itself online", online)
        await asyncio.sleep(0.8)
        devices = (await http.get("/devices", headers=H)).json()
        step("the device goes offline when its socket drops",
             any(x["id"] == dev["id"] and x["status"] == "offline" for x in devices))

asyncio.run(main())
passed = sum(1 for ok, _ in results if ok)
print(f"\n{passed}/{len(results)} Phase 2 flow checks passed")
sys.exit(0 if passed == len(results) else 1)
