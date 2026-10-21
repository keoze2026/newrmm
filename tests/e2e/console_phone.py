"""The operator console on a phone-sized screen.

Appendix A fixes the desktop layout; on a narrow screen the console shows one
pane at a time. This drives the real console at 390 px wide and checks that
nothing overflows, that a session can be created, opened and left, and that
the remote viewer's controls - including the one that closes it - are on screen.

    python tests/e2e/console_phone.py

Expects the relay on :8000 and the console on CONSOLE_URL.
"""
import os
import subprocess
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

CONSOLE = os.environ.get("CONSOLE_URL", "http://localhost:5173")
RELAY = "http://127.0.0.1:8000"
EMAIL = os.environ.get("CONSOLE_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("CONSOLE_PASSWORD", "ChangeMe123!")
WIDTH, HEIGHT = 390, 844

failures = 0


def step(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures += 1


def overflows(page) -> bool:
    return page.evaluate("document.documentElement.scrollWidth > window.innerWidth")


SIZES = [(320, 568), (360, 740), (390, 844), (844, 390), (600, 900)]

MEASURE = """() => ({
  overflow: document.documentElement.scrollWidth > window.innerWidth,
  clipped: [...document.querySelectorAll('button,a,input')].filter(e => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && (r.right > window.innerWidth + 1 || r.left < -1);
  }).map(e => (e.innerText || e.placeholder || e.title || e.tagName).slice(0, 20)),
})"""


def sweep(browser) -> None:
    """Login, join and console at every phone size, portrait and sideways."""
    for width, height in SIZES:
        context = browser.new_context(viewport={"width": width, "height": height},
                                      is_mobile=True, has_touch=True, device_scale_factor=2)
        page = context.new_page()
        for name, path in (("login", "/login"), ("join page", "/join")):
            page.goto(CONSOLE + path)
            page.wait_for_timeout(500)
            found = page.evaluate(MEASURE)
            step(f"{name} fits at {width}x{height}", not found["overflow"] and not found["clipped"],
                 str(found["clipped"]) if found["clipped"] else "")
        page.goto(CONSOLE + "/")
        page.wait_for_timeout(500)
        if page.locator('input[type="email"]').count():
            page.fill('input[type="email"]', EMAIL)
            page.fill('input[type="password"]', PASSWORD)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
        found = page.evaluate(MEASURE)
        step(f"console fits at {width}x{height}", not found["overflow"] and not found["clipped"],
             str(found["clipped"]) if found["clipped"] else "")
        context.close()


def main() -> int:
    token = httpx.post(f"{RELAY}/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
    session = httpx.post(f"{RELAY}/sessions", json={"mode": "attended"},
                         headers={"Authorization": f"Bearer {token}"}).json()
    agent = subprocess.Popen(
        [sys.executable, "-m", "rmm_agent", "join", "--relay", "ws://127.0.0.1:8000",
         "--code", session["code"], "--synthetic", "--no-tray", "--no-input", "--auto-consent"],
        cwd="agent", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(10)  # the console learns the guest has joined on its next refresh
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            sweep(browser)
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
            page.goto(CONSOLE)
            page.fill('input[type="email"]', EMAIL)
            page.fill('input[type="password"]', PASSWORD)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)

            step("the session list fits the screen", not overflows(page))
            create = page.get_by_role("button", name="Create +")
            step("Create is reachable on the list screen", create.count() >= 1 and create.first.is_visible())

            page.wait_for_timeout(6000)
            page.get_by_text(session["code"]).first.click()
            page.wait_for_timeout(1500)
            back = page.get_by_text("‹ Sessions")
            step("opening a session shows it, with a way back", back.count() == 1 and back.first.is_visible())
            step("the session detail fits the screen", not overflows(page))

            page.mouse.click(222, 507)  # the detail panel's Join button
            page.wait_for_timeout(3000)
            end = page.get_by_test_id("viewer-end")
            box = end.bounding_box() if end.count() else None
            step("the viewer opens", end.count() == 1)
            step("the button that closes the viewer is on screen",
                 bool(box) and box["x"] >= 0 and box["x"] + box["width"] <= WIDTH,
                 f"{box}")
            step("the viewer fits the screen", not overflows(page))
            end.click()
            page.wait_for_timeout(500)

            page.get_by_text("‹ Sessions").click()
            page.wait_for_timeout(500)
            step("going back returns to the list", page.get_by_role("button", name="Create +").first.is_visible())
            browser.close()
    finally:
        agent.terminate()
    print(f"\n{'all' if not failures else 'not all'} phone checks passed ({failures} failed)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
