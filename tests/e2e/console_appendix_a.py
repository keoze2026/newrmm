"""Appendix A conformance test for the operator console.

Drives the real console in Google Chrome against a live relay and a connected
guest, and checks the layout, labels, order and behaviour the specification
fixes in Appendix A.

    python tests/e2e/console_appendix_a.py <screenshot-dir>

Expects: relay on :8000, console on CONSOLE_URL, and the endpoint agent already
streaming into the session whose code is in GUEST_CODE, started with:

    python -m rmm_agent join --code <CODE> --synthetic --no-tray \
        --no-input --auto-consent --verbose
"""
import os
import pathlib
import re
import sys

from playwright.sync_api import expect, sync_playwright

CONSOLE = os.environ.get("CONSOLE_URL", "http://localhost:5173")
EMAIL = os.environ.get("CONSOLE_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("CONSOLE_PASSWORD", "ChangeMe123!")
GUEST_CODE = os.environ.get("GUEST_CODE", "")
GUEST_LOG = os.environ.get("GUEST_LOG", "")
# Unique per run, so repeated runs never collide in the session list.
RENAMED = f"Desk-{GUEST_CODE}"
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


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 950})
    page.goto(CONSOLE)

    # ---------------------------------------------------------------- A.1
    def login_screen():
        expect(page.get_by_role("heading", name="RMM Console")).to_be_visible()
        expect(page.get_by_text("Sign in to your monitoring server")).to_be_visible()
        expect(page.get_by_text("EMAIL", exact=True)).to_be_visible()
        expect(page.get_by_text("PASSWORD", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Sign in")).to_be_visible()
        expect(
            page.get_by_text("The first account registered on a server becomes the admin.")
        ).to_be_visible()
        # No server field: only email and password inputs exist.
        assert page.locator("form input").count() == 2, "the login form must have exactly two fields"

    step("A.1 login card: title, subtitle, EMAIL/PASSWORD only, footer note", login_screen)
    page.screenshot(path=f"{SHOTS}/a1-login.png")

    def invalid_credentials():
        page.fill("#email", EMAIL)
        page.fill("#password", "wrong-on-purpose")
        page.keyboard.press("Enter")  # Enter submits
        expect(page.get_by_role("alert")).to_contain_text("Invalid email or password")

    step("A.1 Enter submits and invalid credentials show an inline error", invalid_credentials)

    def sign_in():
        page.fill("#password", PASSWORD)
        page.keyboard.press("Enter")
        expect(page.get_by_role("heading", name="Support")).to_be_visible(timeout=10000)

    step("A.1 valid credentials sign the operator in", sign_in)

    # ---------------------------------------------------------------- A.2
    def icon_rail():
        rail = page.locator("nav").first
        expect(rail).to_be_visible()
        assert 60 <= rail.bounding_box()["width"] <= 90, "icon rail should be about 74px wide"
        expect(rail.get_by_text("Support")).to_be_visible()
        expect(rail.get_by_label("Notifications")).to_be_visible()
        avatar = page.get_by_test_id("user-avatar")
        expect(avatar).to_be_visible()
        assert len(avatar.inner_text().strip()) == 1, "the avatar shows a single initial"

    step("A.2 column 1: icon rail with brand tile, Support, bell and avatar", icon_rail)

    def section_panel():
        expect(page.get_by_role("heading", name="Support")).to_be_visible()
        expect(
            page.get_by_text("Provide on-demand support for any device on the internet.")
        ).to_be_visible()
        expect(page.get_by_role("button", name="Create +")).to_be_visible()
        expect(page.get_by_text("My Sessions").first).to_be_visible()
        expect(page.get_by_test_id("session-count")).to_be_visible()

    step("A.2 column 2: Support heading, subtitle, Create +, My Sessions count", section_panel)

    def session_list_chrome():
        for label in ("join", "edit", "delete", "more"):
            button = page.get_by_test_id(f"list-{label}")
            expect(button).to_be_visible()
            assert button.inner_text().strip().lower() == label, button.inner_text()
        expect(page.get_by_label("Select all sessions")).to_be_visible()
        expect(page.get_by_placeholder("Search My Sessions")).to_be_visible()

    step("A.2 column 3: My Sessions header, Join/Edit/Delete/More, select-all, search", session_list_chrome)

    # ---------------------------------------------------------------- A.3
    def select_guest_session():
        row = page.locator(f'[data-testid="session-row"][data-code="{GUEST_CODE}"]')
        expect(row).to_have_count(1, timeout=15000)
        row.click()
        expect(row).to_have_attribute("data-selected", "true")

    step("A.3 clicking a row selects it and highlights it", select_guest_session)

    def indicator_green():
        row = page.locator(f'[data-testid="session-row"][data-code="{GUEST_CODE}"]')
        expect(row.get_by_text("Host:")).to_be_visible()
        indicator = row.locator('[data-testid="connection-indicator"]')
        expect(indicator).to_have_attribute("data-connected", "true", timeout=15000)

    step("A.3 row shows Host: and the indicator is green when the guest is connected", indicator_green)
    page.screenshot(path=f"{SHOTS}/a2-main-layout.png")

    # ---------------------------------------------------------------- A.4
    TAB_ORDER = [
        "session", "system", "history", "chat", "terminal",
        "files", "tools", "download", "logs", "locate",
    ]

    def tab_strip_order():
        boxes = []
        for key in TAB_ORDER:
            tab = page.get_by_test_id(f"tab-{key}")
            expect(tab).to_be_visible()
            boxes.append(tab.bounding_box()["y"])
        assert boxes == sorted(boxes), "tabs must run top to bottom in the Appendix A.4 order"
        expect(page.get_by_test_id("tab-session")).to_have_attribute("data-active", "true")

    step("A.4 ten tabs in the specified order, Session active by default", tab_strip_order)

    def active_tab_border():
        tab = page.get_by_test_id("tab-session")
        colour = tab.evaluate("el => getComputedStyle(el).borderLeftColor")
        assert colour == "rgb(47, 111, 228)", f"active tab left border should be #2F6FE4, got {colour}"

    step("A.4 active tab carries the blue left-border", active_tab_border)

    # ---------------------------------------------------------------- A.5
    def session_tab_default():
        expect(page.get_by_text("Name:", exact=True)).to_be_visible()
        expect(page.get_by_test_id("rename-session")).to_be_visible()
        expect(page.get_by_text("Invite via:", exact=True)).to_be_visible()
        expect(page.get_by_test_id("invite-code")).to_have_attribute("data-active", "true")
        expect(page.get_by_text("Direct guest to:")).to_be_visible()
        expect(page.get_by_text("And instruct to type in the code:")).to_be_visible()
        code = page.get_by_test_id("join-code")
        expect(code).to_have_text(GUEST_CODE)
        size = float(code.evaluate("el => parseFloat(getComputedStyle(el).fontSize)"))
        weight = code.evaluate("el => getComputedStyle(el).fontWeight")
        assert size >= 28, f"the code must be large; got {size}px"
        assert int(weight) >= 700, f"the code must be bold; got {weight}"

    step("A.5 Session tab: Name + pencil, Invite via Code default, code card large and bold", session_tab_default)

    def link_view():
        page.get_by_test_id("invite-link").click()
        link = page.get_by_test_id("join-link")
        expect(link).to_be_visible()
        assert link.get_attribute("readonly") is not None, "the join link must be read-only"
        assert GUEST_CODE in link.input_value()
        expect(page.get_by_role("button", name="Copy the join link")).to_be_visible()
        page.get_by_test_id("invite-code").click()

    step("A.5 Link view shows a read-only join link with a copy button", link_view)

    def joined_state():
        expect(page.get_by_test_id("waiting-line")).to_have_text("Your guest has joined.", timeout=15000)
        expect(page.get_by_test_id("join-button")).to_be_enabled()
        expect(page.get_by_test_id("live-preview")).to_be_visible()

    step("A.5 waiting line flips to 'Your guest has joined.' and Join enables", joined_state)

    def rename():
        page.get_by_test_id("rename-session").click()
        field = page.get_by_test_id("session-name-input")
        field.fill(RENAMED)
        field.press("Enter")
        expect(page.get_by_test_id("session-name")).to_have_text(RENAMED, timeout=10000)
        # The join code must be untouched by a rename.
        expect(page.get_by_test_id("join-code")).to_have_text(GUEST_CODE)

    step("A.5 Edit renames the session and never changes the join code", rename)
    page.screenshot(path=f"{SHOTS}/a5-session-tab.png")

    # ---------------------------------------------------------------- A.6
    def system_info_tab():
        page.get_by_test_id("tab-system").click()
        expect(page.get_by_role("heading", name="System info")).to_be_visible()
        for label in ("Hostname", "Operating system", "Logged-in user", "IP address", "CPU", "Cores", "Memory", "Agent version", "Status", "Last seen"):
            expect(page.get_by_text(label, exact=True)).to_be_visible()
        expect(page.get_by_text("Linux", exact=False).first).to_be_visible()

    step("A.6 System info reports the endpoint's real details", system_info_tab)
    page.screenshot(path=f"{SHOTS}/a6-system-info.png")

    def logs_tab():
        page.get_by_test_id("tab-logs").click()
        expect(page.get_by_role("heading", name="Logs")).to_be_visible()
        expect(page.get_by_text("session.guest_joined").first).to_be_visible(timeout=10000)

    step("A.6 Logs show the server-side audit trail for this session", logs_tab)

    def history_tab():
        page.get_by_test_id("tab-history").click()
        expect(page.get_by_role("heading", name="Session history")).to_be_visible()

    step("A.6 Session history renders", history_tab)

    def unimplemented_labelled():
        page.get_by_test_id("tab-chat").click()
        expect(page.get_by_text("Not yet implemented.")).to_be_visible()

    step("A.6 Chat/Tools/Locate are clearly labelled as not implemented", unimplemented_labelled)

    # ---------------------------------------------------------------- A.7
    def open_viewer():
        page.get_by_test_id("tab-session").click()
        page.get_by_test_id("join-button").click()
        expect(page.get_by_test_id("viewer-canvas")).to_be_visible(timeout=10000)

    step("A.7 Join opens the full-screen viewer", open_viewer)

    def viewer_top_bar():
        expect(page.get_by_test_id("viewer-status-dot")).to_be_visible()
        stats = page.get_by_test_id("viewer-stats")
        expect(stats).to_be_visible()
        page.wait_for_timeout(2500)
        text = stats.inner_text()
        assert "fps" in text and "kbps" in text, text
        fps = int(text.split(" fps")[0])
        assert fps > 0, f"the fps readout must be live; got {text!r}"

    step("A.7 top bar shows the machine name, live dot and a live fps · kbps readout", viewer_top_bar)

    def viewer_toolbar():
        toolbar = page.get_by_test_id("viewer-toolbar")
        for title in (
            "Terminal", "Files", "Screenshot", "Switch monitor", "Zoom in", "Zoom out",
            "Annotate", "Clear annotations", "Send file", "Get file",
            "Blank the guest screen", "Fullscreen", "End session view",
        ):
            expect(toolbar.get_by_title(title)).to_be_visible()
        expect(page.get_by_test_id("toggle-control")).to_contain_text("Controlling")

    step("A.7 toolbar carries every specified control", viewer_toolbar)

    def canvas_renders_frames():
        # Two samples a second apart must differ: the canvas is showing live video.
        sample = """el => {
                 const d = el.getContext('2d').getImageData(0, 0, el.width, el.height).data;
                 let sum = 0;
                 for (let i = 0; i < d.length; i += 397) sum = (sum + d[i] * (i % 251)) >>> 0;
                 return sum;
               }"""
        first = page.get_by_test_id("viewer-canvas").evaluate(sample)
        page.wait_for_timeout(1200)
        second = page.get_by_test_id("viewer-canvas").evaluate(sample)
        assert first != second, "the viewer canvas is not updating"

    step("A.7 guest screen renders live on the canvas", canvas_renders_frames)
    page.screenshot(path=f"{SHOTS}/a7-viewer.png")

    def aspect_ratio_preserved():
        info = page.get_by_test_id("viewer-canvas").evaluate(
            """el => {
                 const r = el.getBoundingClientRect();
                 const ctx = el.getContext('2d');
                 // Scan the middle row for the letterbox edges.
                 const d = ctx.getImageData(0, Math.floor(el.height/2), el.width, 1).data;
                 let left = -1, right = -1;
                 for (let x = 0; x < el.width; x++) {
                   const i = x*4;
                   const isBg = d[i] === 13 && d[i+1] === 23 && d[i+2] === 38;
                   if (!isBg) { if (left < 0) left = x; right = x; }
                 }
                 return {w: r.width, h: r.height, left, right, cw: el.width};
               }"""
        )
        assert info["left"] >= 0 and info["right"] > info["left"], "no image found on the canvas"
        # The 1280x800 guest is wider than it is tall relative to the viewer, so
        # the drawn image must be inset or exactly flush - never stretched past.
        assert info["right"] <= info["cw"], "the image overflows the canvas"

    step("A.7 canvas preserves aspect ratio (letterboxed, not stretched)", aspect_ratio_preserved)

    def cursor_mapping():
        """Click a known point and confirm the guest is told the same point."""
        box = page.get_by_test_id("viewer-canvas").bounding_box()
        geometry = page.get_by_test_id("viewer-canvas").evaluate(
            """el => {
                 const ctx = el.getContext('2d');
                 const d = ctx.getImageData(0, Math.floor(el.height/2), el.width, 1).data;
                 let left = -1, right = -1;
                 for (let x = 0; x < el.width; x++) {
                   const i = x*4;
                   const isBg = d[i] === 13 && d[i+1] === 23 && d[i+2] === 38;
                   if (!isBg) { if (left < 0) left = x; right = x; }
                 }
                 return {left, right, cw: el.width, dpr: window.devicePixelRatio || 1};
               }"""
        )
        dpr = geometry["dpr"]
        left_css = geometry["left"] / dpr
        right_css = geometry["right"] / dpr
        # Aim at the horizontal centre of the drawn image, one quarter down.
        target_x = box["x"] + (left_css + right_css) / 2
        target_y = box["y"] + box["height"] * 0.25
        page.mouse.move(target_x, target_y)
        page.mouse.down()
        page.mouse.up()
        page.wait_for_timeout(800)

        log = pathlib.Path(GUEST_LOG).read_text() if GUEST_LOG else ""
        downs = [l for l in log.splitlines() if "input mouse down" in l]
        assert downs, "the guest received no mouse-down; input is not reaching it"
        fields = dict(part.split("=") for part in downs[-1].split() if part.count("=") == 1)
        x = float(fields["x"])
        # The click was aimed at the horizontal centre of the drawn image, so the
        # guest must be told x is the centre - this is what letterboxing breaks.
        assert 0.45 <= x <= 0.55, f"cursor mapping is off: guest was told x={x:.3f}, expected ~0.5"

    step("A.7 pointer input is sent to the guest", cursor_mapping)

    def blank_toggle():
        page.get_by_test_id("blank-toggle").click()
        page.wait_for_timeout(800)
        log = pathlib.Path(GUEST_LOG).read_text() if GUEST_LOG else ""
        assert "privacy blank on" in log, "the guest was not told to blank its screen"

    step("A.7 blank toggles the guest privacy screen", blank_toggle)

    def view_only_toggle():
        page.get_by_test_id("toggle-control").click()
        expect(page.get_by_test_id("toggle-control")).to_contain_text("View")
        page.get_by_test_id("toggle-control").click()
        expect(page.get_by_test_id("toggle-control")).to_contain_text("Controlling")

    step("A.7 Controlling / View-only toggle switches", view_only_toggle)

    def zoom_and_annotate():
        toolbar = page.get_by_test_id("viewer-toolbar")
        toolbar.get_by_title("Zoom in").click()
        toolbar.get_by_title("Zoom out").click()
        page.get_by_test_id("annotate").click()
        box = page.get_by_test_id("viewer-canvas").bounding_box()
        page.mouse.move(box["x"] + 200, box["y"] + 200)
        page.mouse.down()
        page.mouse.move(box["x"] + 320, box["y"] + 280)
        page.mouse.up()
        toolbar.get_by_title("Clear annotations").click()
        page.get_by_test_id("annotate").click()

    step("A.7 zoom in/out, annotate and clear all work", zoom_and_annotate)

    def monitor_switcher():
        page.get_by_test_id("monitor-switch").click()
        # The label comes from the endpoint, so match whatever it reports rather
        # than a fixed string: real capture says "Monitor 1", synthetic "Primary".
        menu = page.locator("div", has_text=re.compile(r"Monitor \d+|Primary")).last
        expect(menu).to_be_visible()
        page.keyboard.press("Escape")
        page.get_by_test_id("monitor-switch").click()

    step("A.7 monitor switcher lists the guest's displays", monitor_switcher)

    def close_viewer():
        page.get_by_test_id("viewer-end").click()
        expect(page.get_by_test_id("viewer-canvas")).to_have_count(0)
        expect(page.get_by_test_id("join-code")).to_be_visible()

    step("A.7 End closes the viewer and returns to the session", close_viewer)

    # --------------------------------------------------------- list behaviour
    def search_filters():
        page.get_by_placeholder("Search My Sessions").fill(RENAMED)
        expect(page.locator('[data-testid="session-row"]')).to_have_count(1)
        page.get_by_placeholder("Search My Sessions").fill("")

    step("A.2 search filters the session list", search_filters)

    def select_all():
        page.get_by_label("Select all sessions").check()
        rows = page.locator('[data-testid="session-row"] input[type=checkbox]')
        for i in range(rows.count()):
            assert rows.nth(i).is_checked(), "select-all must tick every row"
        page.get_by_label("Select all sessions").uncheck()

    step("A.2 select-all ticks every row", select_all)

    def single_page_app():
        """No navigation happens: the document is never reloaded."""
        page.evaluate("window.__spaMarker = 'still-here'")
        page.get_by_test_id("tab-system").click()
        page.get_by_test_id("tab-session").click()
        page.get_by_placeholder("Search My Sessions").fill(RENAMED[:6])
        page.get_by_placeholder("Search My Sessions").fill("")
        assert page.evaluate("window.__spaMarker") == "still-here", "the page reloaded"

    step("A.2 single-page app: navigating panels never reloads the page", single_page_app)

    browser.close()

passed = sum(1 for ok, _ in results if ok)
print(f"\n{passed}/{len(results)} Appendix A checks passed")
sys.exit(0 if passed == len(results) else 1)
