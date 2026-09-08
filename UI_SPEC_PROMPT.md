# UI SPEC PROMPT — Operator Console (exact)

Fresh, greenfield build — do NOT import or depend on any previous codebase.
Reproduce this console **exactly** (same look and behaviour), as an improved
implementation. It must look and behave identically whether the connected
endpoint is Windows, macOS, or Linux.

**Style:** single-page web app (no reloads). Light theme. Primary blue #2F6FE4,
deep navy #1F3A5F, near-white background #F7F9FC, subtle grey borders,
Inter/system font.

**Login:** centered card, "RMM Console" title, subtitle "Sign in to your
monitoring server". Fields: **Email + Password only** (no server field).
Full-width "Sign in". Footer: "The first account registered on a server becomes
the admin." Enter submits; invalid credentials show an inline error.

**Main layout — four columns, left → right:**
1. **Icon rail** (~74px): brand logo tile at top; a "Support" nav item (icon +
   label), highlighted when active; a notification bell and a circular
   user-initial avatar pinned at the bottom.
2. **Section panel** (~300px): large "Support" heading; subtitle "Provide
   on-demand support for any device on the internet."; full-width blue
   **Create +** button; a "My Sessions" row with a live count.
3. **Session list** (fixed width): header "My Sessions" + toolbar
   **Join · Edit · Delete · More**; a select-all checkbox with a dropdown caret;
   a rounded "Search My Sessions" box; then rows. Each row: session name (bold),
   "Host: <name>", a checkbox, and a **person──line──person** connection
   indicator that turns green when the guest is connected, grey when not.
   Selecting a row fills the detail panel.
4. **Detail panel** (fills remaining width): a **vertical icon tab strip** on its
   left edge — Session, System info, History, Chat, Terminal, Files, Tools,
   Download, Logs, Locate — active tab has a blue left-border and blue icon;
   inactive icons grey. Selected session content beside it.

**Session tab (default):**
- "Name:" in an editable field with a pencil affordance. **Edit renames the
  session; the join code is never editable.**
- "Invite via:" with two tabs — **Code** (default) and **Link**.
- Code view: card reading "Direct guest to:" + the join URL centered, then
  "And instruct to type in the code:" + the code shown large and bold; copy button.
- Link view: the shareable https join link, read-only, with a copy button.
- Centered blue **Join** button (enabled once the guest has joined).
- Hourglass waiting line: "Your guest has not joined yet…" → "Your guest has
  joined." When joined, a small **LIVE preview** of the guest screen appears;
  clicking it (or Join) opens the full viewer.

**Other tabs:** System info (hostname, OS+version, user, IP, CPU, cores, memory,
agent version, status, last seen); History (past sessions: start, kind, status,
duration); Logs (audit trail for the machine); Terminal / Files / Download
(launch into the active session; clear "available once your guest joins" state
otherwise); Chat / Tools / Locate present in the strip, labelled clearly if not
yet implemented.

**Full-screen remote viewer (opens on Join):**
- Top bar: machine name + live status dot, and a live **fps · kbps** readout.
- Toolbar (right): **Controlling/View-only toggle, Terminal, Files, Screenshot,
  Monitor switcher, Zoom in, Zoom out, Annotate (pen) + Clear, Send file
  (upload), Get file (download), Fullscreen, End (X)**.
- The guest screen renders on a canvas that scales to fill the viewer preserving
  aspect ratio, with **1:1 cursor mapping** (clicks land on the correct point even
  when letterboxed).
- Full mouse + keyboard control when "Controlling" is on; Terminal and Files open
  as panels within the viewer. Blank (eye-slash) toggles the guest privacy screen.

Match this precisely — layout, labels, order, and behaviour. Full detail is in
Appendix A of the Engineering Specification.
