"""Phase 1 acceptance test, driven through the real console in Google Chrome.

Spec section 7, P1 checkpoint:
  "Operator can log in; a session record is created and appears in the console;
   audit log records it."
"""
import os
import re
import sys
from playwright.sync_api import expect, sync_playwright

# Defaults target the Vite dev server; point CONSOLE_URL at the deployed stack
# to run the same checks against nginx.
CONSOLE = os.environ.get("CONSOLE_URL", "http://localhost:5173")
EMAIL = os.environ.get("CONSOLE_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("CONSOLE_PASSWORD", "ChangeMe123!")
SHOTS = sys.argv[1]

results = []


def step(name, fn):
    try:
        fn()
        results.append((True, name))
        print(f"PASS  {name}")
    except Exception as exc:
        results.append((False, name))
        print(f"FAIL  {name}\n      {exc}")


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(CONSOLE)

    # 1. The console refuses entry until an operator authenticates.
    step("login page is shown to an anonymous visitor",
         lambda: expect(page.get_by_role("heading", name="Operator sign in")).to_be_visible())
    page.screenshot(path=f"{SHOTS}/01-login.png")

    # 2. Wrong credentials are rejected with a visible error.
    def bad_login():
        page.fill("#email", EMAIL)
        page.fill("#password", "definitely-wrong")
        page.click("button[type=submit]")
        expect(page.get_by_role("alert")).to_contain_text("Invalid email or password")

    step("wrong password is rejected", bad_login)
    page.screenshot(path=f"{SHOTS}/02-login-rejected.png")

    # 3. Correct credentials sign the operator in.
    def good_login():
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        expect(page.get_by_role("heading", name="Sessions")).to_be_visible(timeout=10000)
        expect(page.get_by_text(EMAIL)).to_be_visible()

    step("operator logs in", good_login)
    page.screenshot(path=f"{SHOTS}/03-signed-in.png")

    # 4. The relay health indicator is live in the shell.
    step("relay reports healthy in the console",
         lambda: expect(page.get_by_text(re.compile(r"relay ok"))).to_be_visible(timeout=10000))

    # 5. Creating a session shows its code and lists the record.
    created_code = {}

    def create_session():
        page.get_by_role("button", name="New attended session").click()
        code_el = page.locator("div.font-mono.text-3xl")
        expect(code_el).to_be_visible(timeout=10000)
        code = code_el.inner_text().strip()
        assert len(code) == 8, f"expected an 8-character code, got {code!r}"
        created_code["code"] = code
        # The same code must appear as a row in the session table.
        expect(page.locator("tbody tr", has_text=code)).to_have_count(1)
        expect(page.locator("tbody tr", has_text=code)).to_contain_text("pending")

    step("session is created and appears in the console", create_session)
    page.screenshot(path=f"{SHOTS}/04-session-created.png")

    # 6. The session survives a reload - it is a database record, not UI state.
    def persists():
        page.reload()
        expect(page.get_by_role("heading", name="Sessions")).to_be_visible(timeout=10000)
        expect(page.locator("tbody tr", has_text=created_code["code"])).to_have_count(1)

    step("session record persists across a page reload", persists)

    # 7. State transition works from the console.
    def activate():
        row = page.locator("tbody tr", has_text=created_code["code"])
        row.get_by_role("button", name="Mark active").click()
        expect(page.locator("tbody tr", has_text=created_code["code"])).to_contain_text("active")

    step("session can be marked active", activate)
    page.screenshot(path=f"{SHOTS}/05-session-active.png")

    # 8. Every one of those actions is in the audit log.
    def audit():
        page.get_by_role("link", name="Audit log").click()
        expect(page.get_by_role("heading", name="Audit log")).to_be_visible(timeout=10000)
        body = page.locator("tbody")
        expect(body).to_contain_text("auth.login.failed")
        expect(body).to_contain_text("auth.login.success")
        expect(body).to_contain_text("session.created")
        expect(body).to_contain_text("session.state_changed")
        expect(body).to_contain_text(created_code["code"])

    step("audit log records the login, the session and the state change", audit)
    page.screenshot(path=f"{SHOTS}/06-audit-log.png")

    # 9. Device enrollment shows the secret once.
    def devices():
        page.get_by_role("link", name="Devices").click()
        expect(page.get_by_role("heading", name="Devices")).to_be_visible(timeout=10000)
        page.fill("#device-name", "Reception PC")
        page.select_option("#device-os", "windows")
        page.get_by_role("button", name="Enroll device").click()
        expect(page.get_by_text("Enrollment secret")).to_be_visible(timeout=10000)
        expect(page.locator("tbody tr", has_text="Reception PC")).to_have_count(1)

    step("device enrolls and the secret is shown once", devices)
    page.screenshot(path=f"{SHOTS}/07-device-enrolled.png")

    # 10. Signing out returns to the login page.
    def logout():
        page.get_by_role("button", name="Sign out").click()
        expect(page.get_by_role("heading", name="Operator sign in")).to_be_visible(timeout=10000)

    step("operator signs out", logout)

    browser.close()

passed = sum(1 for ok, _ in results if ok)
print(f"\n{passed}/{len(results)} browser checks passed")
sys.exit(0 if passed == len(results) else 1)
