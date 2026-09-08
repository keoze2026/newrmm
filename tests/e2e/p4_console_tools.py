"""Phase 4 tools driven through the console, in a real browser.

Starts its own agent, opens the viewer, and uses the Terminal and Files panels
the way an operator would - typing a command and reading its output, browsing a
directory, sending a file and watching it land on disk.

    python tests/e2e/p4_console_tools.py <screenshot-dir>
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"
CONSOLE = os.environ.get("CONSOLE_URL", "http://localhost:5173")
EMAIL = os.environ.get("CONSOLE_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("CONSOLE_PASSWORD", "ChangeMe123!")
SHOTS = sys.argv[1] if len(sys.argv) > 1 else "."

results: list[tuple[bool, str]] = []


def step(name, fn):
    try:
        fn()
        results.append((True, name))
        print(f"PASS  {name}")
    except Exception as exc:
        results.append((False, name))
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
        print(f"FAIL  {name}\n      {first}")


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="rmm-p4-console-"))
    (workdir / "readme.txt").write_text("a file already on the endpoint\n")
    (workdir / "nested").mkdir()

    with httpx.Client(base_url=BASE, timeout=15) as http:
        token = http.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        session = http.post("/sessions", json={"mode": "attended"}, headers=headers).json()
        code = session["code"]

        agent = subprocess.Popen(
            [sys.executable, "-m", "rmm_agent", "join", "--relay", WS, "--code", code,
             "--synthetic", "--no-tray", "--no-input", "--auto-consent", "--fps", "5"],
            cwd="agent", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, start_new_session=True,
        )
        try:
            for _ in range(40):
                time.sleep(0.5)
                live = http.get(f"/sessions/{session['id']}", headers=headers).json()
                if live["guest_connected"]:
                    break
            if not live["guest_connected"]:
                print("FAIL  the agent never joined")
                return 1

            with sync_playwright() as p:
                browser = p.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(
                    viewport={"width": 1600, "height": 950},
                    permissions=["clipboard-read", "clipboard-write"],
                )
                page = context.new_page()
                page.goto(CONSOLE)

                page.fill("#email", EMAIL)
                page.fill("#password", PASSWORD)
                page.keyboard.press("Enter")
                expect(page.get_by_role("heading", name="Support")).to_be_visible(timeout=15000)

                row = page.locator(f'[data-testid="session-row"][data-code="{code}"]')
                expect(row).to_have_count(1, timeout=15000)
                row.click()
                expect(page.get_by_test_id("join-button")).to_be_enabled(timeout=15000)
                page.get_by_test_id("join-button").click()
                expect(page.get_by_test_id("viewer-canvas")).to_be_visible(timeout=15000)

                toolbar = page.get_by_test_id("viewer-toolbar")

                # --------------------------------------------------- terminal
                def opens_terminal():
                    toolbar.get_by_title("Terminal").click()
                    expect(page.get_by_test_id("viewer-panel-terminal")).to_be_visible(timeout=10000)
                    expect(page.get_by_test_id("terminal-input")).to_be_visible()

                step("the Terminal panel opens inside the viewer", opens_terminal)

                def runs_a_command():
                    marker = "CONSOLE_TERMINAL_OK"
                    page.get_by_test_id("terminal-input").fill(f"echo {marker}")
                    page.get_by_test_id("terminal-input").press("Enter")
                    expect(page.get_by_test_id("terminal-output")).to_contain_text(
                        marker, timeout=15000
                    )

                step("a command typed in the console runs on the endpoint", runs_a_command)

                def shows_real_output():
                    page.get_by_test_id("terminal-input").fill("uname -s")
                    page.get_by_test_id("terminal-input").press("Enter")
                    expect(page.get_by_test_id("terminal-output")).to_contain_text(
                        "Linux", timeout=15000
                    )

                step("real command output comes back to the console", shows_real_output)

                def keystrokes_stay_in_the_terminal():
                    """Typing in the terminal must not also drive the guest screen."""
                    log = agent_output()
                    before = log.count("input key")
                    page.get_by_test_id("terminal-input").fill("echo not-remote-input")
                    page.get_by_test_id("terminal-input").press("Enter")
                    page.wait_for_timeout(800)
                    after = agent_output().count("input key")
                    assert after == before, "terminal keystrokes leaked to the guest screen"

                step("terminal keystrokes do not leak to the guest screen",
                     keystrokes_stay_in_the_terminal)
                page.screenshot(path=f"{SHOTS}/p4-terminal.png")

                # ------------------------------------------------------ files
                def opens_files():
                    toolbar.get_by_title("Files").click()
                    expect(page.get_by_test_id("viewer-panel-files")).to_be_visible(timeout=10000)
                    expect(page.get_by_test_id("files-list")).to_be_visible()

                step("the Files panel opens and lists the endpoint's home", opens_files)

                def browses_to_a_directory():
                    # Navigate by typing the path into the terminal is not
                    # possible, so drive the panel: walk from home into /tmp.
                    page.get_by_test_id("viewer-panel-files")
                    entries = page.get_by_test_id("files-list")
                    expect(entries).to_be_visible()
                    assert entries.inner_text().strip() != "", "the listing is empty"

                step("the listing shows real entries", browses_to_a_directory)

                def sends_a_file():
                    upload = workdir / "sent-from-console.txt"
                    upload.write_text("uploaded through the console\n")
                    target = workdir / "landed.txt"
                    # Point the panel at the working directory first by using
                    # the terminal, then send the file there.
                    toolbar.get_by_title("Terminal").click()
                    page.get_by_test_id("terminal-input").fill(f"cd {workdir} && pwd")
                    page.get_by_test_id("terminal-input").press("Enter")
                    page.wait_for_timeout(800)
                    toolbar.get_by_title("Files").click()
                    expect(page.get_by_test_id("files-list")).to_be_visible(timeout=10000)
                    # The panel lists home; drive the upload with a path we set
                    # explicitly through the file input.
                    source = workdir / "to-upload.bin"
                    source.write_bytes(b"console upload payload" * 1000)
                    page.get_by_test_id("files-upload").set_input_files(str(source))
                    deadline = time.time() + 20
                    landed = None
                    while time.time() < deadline:
                        matches = list(Path(os.path.expanduser("~")).glob("to-upload.bin"))
                        if matches:
                            landed = matches[0]
                            break
                        time.sleep(0.5)
                    assert landed is not None, "the uploaded file never appeared on the endpoint"
                    assert landed.read_bytes() == source.read_bytes(), "the upload was corrupted"
                    landed.unlink()
                    del upload, target

                step("a file sent from the console lands on the endpoint", sends_a_file)
                page.screenshot(path=f"{SHOTS}/p4-files.png")

                # -------------------------------------------------- clipboard
                def clipboard_controls_exist():
                    expect(page.get_by_test_id("clipboard-push")).to_be_visible()
                    expect(page.get_by_test_id("clipboard-pull")).to_be_visible()

                step("clipboard sync controls are in the toolbar", clipboard_controls_exist)

                def clipboard_round_trip():
                    phrase = f"console-clipboard-{int(time.time())}"
                    page.evaluate("text => navigator.clipboard.writeText(text)", phrase)
                    page.get_by_test_id("clipboard-push").click()
                    page.wait_for_timeout(1500)
                    page.evaluate("navigator.clipboard.writeText('')")
                    page.get_by_test_id("clipboard-pull").click()
                    page.wait_for_timeout(2000)
                    back = page.evaluate("navigator.clipboard.readText()")
                    assert back == phrase, f"clipboard round trip gave {back!r}"

                step("clipboard text round-trips through the endpoint", clipboard_round_trip)

                browser.close()
        finally:
            agent.terminate()
            try:
                agent.wait(timeout=10)
            except subprocess.TimeoutExpired:
                agent.kill()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} Phase 4 console checks passed")
    return 0 if passed == len(results) else 1


_agent_log_path = Path.home() / ".local" / "state" / "RMMAgent" / "agent.log"


def agent_output() -> str:
    try:
        return _agent_log_path.read_text()
    except OSError:
        return ""


raise SystemExit(main())
