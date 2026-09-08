# BUILD PROMPT — Remote Desktop & Support Platform

Paste this into a fresh Claude Code session. It instructs Claude to build the
system phase by phase, using the Engineering Specification as the guide and
testing that the system works at the end of every phase.

> **Companion document:** the full spec (`Remote_Desktop_Platform_Specification.docx`)
> is the authoritative guide — architecture, feature set, per-platform approach,
> milestones with test checkpoints, acceptance criteria, security model, risks.
> Follow it. This prompt is the working method.

---

## GROUND RULES (read first)

- This is a **fresh, greenfield build** — a **better version** of an existing tool. Do NOT import from, copy files from, or depend on any previous codebase. Build clean.
- **Keep the exact same UI** described in this prompt and in Appendix A of the specification — same layout, labels, order, and behaviour. Same look; better engineering underneath.
- Every reference here is to *this new project's own* files (e.g. its own `PROJECT_STATUS.md`), never to any prior program.
- Must work identically on **Windows, macOS, and Linux** endpoints.

## PROMPT

Build a self-hosted, cross-platform **Remote Desktop & Support Platform**. Follow
the attached Engineering Specification as the authoritative guide. Work in phases;
do NOT skip ahead.

**What it is:** an operator connects from a browser console, through a relay
server, to an endpoint agent installed on a remote machine — to view the screen
and control mouse/keyboard. Support attended sessions (short code + link) and
unattended access. Must work fully on **Windows, macOS, and Linux** endpoints.

**Stack:**
- Console: React + TypeScript + Vite + Tailwind
- Relay server: Python + FastAPI, WebSockets over TLS, Redis (pub/sub), PostgreSQL + SQLAlchemy
- Agent: Python core (asyncio, websockets); capture via `mss`, input via `pynput`, tray via `pystray`; packaged per-OS with PyInstaller
- Native capture module for the privacy-blank feature: **Rust** on Windows (Windows.Graphics.Capture via the `windows-capture` binding, exposed to Python); Swift/Obj-C (ScreenCaptureKit) on macOS; C (PipeWire/X11) on Linux
- Deploy: Docker Compose + nginx; CI: GitHub Actions building signed per-OS installers

**Features:** attended + unattended sessions, live screen view, remote control,
multi-monitor switch, file transfer (both ways), remote terminal, clipboard sync,
screenshot/zoom/annotate, privacy blank screen, tray + session consent, audit log.

**Security:** TLS everywhere, authenticated operators, per-device hashed secrets,
visible endpoint consent, no capture outside an active session, full audit trail.

**How I want you to work:**

1. Before coding each phase, give me a short plan and WAIT for my approval.

2. Build in these phases, and **after each phase, TEST that the system actually
   works and show me the result before moving on** — on a real machine for the
   platform in question:
   - **P1 Foundation** — relay, auth, session model, audit log, console shell.
     *Test: operator logs in; a session record is created and shown; audit logs it.*
   - **P2 Core session (Windows)** — enroll/connect, live capture, remote control,
     tray/consent. *Test: a Windows endpoint connects, streams live, is controllable.*
   - **P3 Cross-platform core** — same on macOS and Linux.
     *Test: connect→live→control passes on a real macOS and a real Linux machine.*
   - **P4 Tools** — file transfer, terminal, clipboard, multi-monitor,
     screenshot/zoom/annotate, all OSes. *Test: each tool works on all three; core
     session still passes (regression).*
   - **P5 Privacy blank** — native capture-exclusion (Rust) on Windows, sharing-type
     on macOS, guest-lock on Linux. *Test: guest screen black + operator stays LIVE
     and in control for 10+ min; agent stays online across on/off toggles.*
   - **P6 Hardening & release** — security review, low-bandwidth tuning, persistent
     file logging, signed installers, deployment. *Test: full acceptance suite on all
     three OSes; installers install clean; deployed build verified live.*

3. Keep changes scoped to the current phase. Do NOT touch working code from earlier
   phases except to fix a regression the tests catch.

4. Maintain a `PROJECT_STATUS.md`: after every change, record what changed, what
   works, what doesn't, and how to revert. READ it before making any claim about
   what works.

5. Use git tags/branches so any phase can be rolled back cleanly. Make a restore
   point before risky work.

6. Be honest about limits. If something needs infrastructure we don't have (e.g. a
   Microsoft-signed kernel driver), say so instead of guessing — and NEVER claim a
   platform works without testing it there. A per-platform fix ships to that platform
   only.

Start with **Phase 1**: give me the plan, wait for my go, then build it and show me
the passing test.
