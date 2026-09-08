# Security review

Phase 6 lists a security review; this is it. Reviewed against section 9 of the
specification:

> All traffic encrypted (TLS); operators authenticated; per-device secrets
> stored hashed. The endpoint always shows a visible presence indicator and
> notifies the user when a session starts. No input capture or screen capture
> occurs outside an active, consented session. Full audit log of connects,
> disconnects, sessions and administrative actions.

Each finding below says what was wrong, what was done, and where the test is.
Findings still open are listed as open, not quietly dropped.

---

## Fixed

### 1. Nothing was rate limited — HIGH

Three routes are reachable without any credential, and each is worth guessing at:

| Route | What guessing it gets you |
| --- | --- |
| `POST /auth/login` | An operator password, and with it every session and device |
| `GET /connector/session/{code}` | Whether a session code is live — the cheapest way to hunt for one |
| `WS /ws/guest/{code}` | Joining a stranger's session, since the code is the whole credential |

Nothing throttled any of them. A script could grind at the login endpoint as
fast as the network allowed.

**Fixed.** `app/services/ratelimit.py`: 10 login attempts and 20 code probes per
minute per caller, counted in Redis so the limit holds across relay instances
and falling back to memory when Redis is down — a single instance stays
protected rather than failing open. The guest WebSocket is limited too, closing
with 4429 since it cannot return a 429.

*Tests:* `relay/tests/test_security.py::test_password_guessing_is_throttled`,
`::test_session_code_probing_is_throttled`.

### 2. A placeholder JWT secret would run in production — HIGH

`jwt_secret` defaulted to `change-me-in-production`. Deployed without setting
it, anyone who has read this repository can mint a valid operator token and take
over every session.

**Fixed.** The relay refuses to start when the secret is still a placeholder and
the environment is not `development`, naming the fix in the error
(`openssl rand -hex 32`).

### 3. Ending a session did not disconnect the endpoint — HIGH

Found earlier, during Phase 5, and worth recording here because it is a section
9 violation: marking a session `ended` left the agent connected and streaming,
so capture continued outside a consented session.

**Fixed.** The relay hangs up on both halves, and the agent retires rather than
reconnecting to a session that is over.

*Tests:* `relay/tests/test_session_console.py::test_ending_a_session_hangs_up_on_the_endpoint`,
`tests/e2e/p5_privacy_blank.py`.

### 4. A privacy blank could lock someone out of their own machine — HIGH

The guest lock blacked the screen and suppressed local input with no time limit
and no escape. A failure left the machine unusable — this actually happened
during testing and needed a power cycle.

**Fixed.** Every blank has a watchdog whether or not one is requested, Escape is
never suppressed and releases the lock, the overlay says so on screen, and a
blank is released when its session ends.

*Tests:* `agent/tests/test_privacy.py`, `agent/tests/test_privacy_input_block.py`.

---

## Reviewed and sound

- **Passwords and device secrets** are Argon2 hashes. The enrolment secret is
  returned exactly once, at creation, and never appears in any listing.
  *Test:* `test_device_secrets_are_never_returned_after_enrolment`.
- **The audit trail is append-only in the database.** A trigger rejects UPDATE
  and DELETE, so immutability holds regardless of which client connects, and the
  API exposes no write route. *Tests:* `test_audit_log_is_append_only`,
  `test_the_audit_trail_cannot_be_altered_through_the_api`.
- **Consent is enforced by the relay, not only by the agent.** Frames arriving
  before a decision is recorded are dropped, so a modified agent still cannot
  stream without consent on the trail. *Test:* `tests/e2e/p2_session_flow.py`.
- **Presence cannot be faked.** A session row put into the state a compromised
  agent would want still reports the guest as absent unless consent was granted.
  *Test:* `test_presence_requires_consent_even_if_the_row_says_connected`.
- **Unattended endpoints authenticate per device**, and a wrong secret is
  refused. *Test:* `tests/e2e/p2_session_flow.py`.
- **The guest endpoint leaks nothing.** `/connector/session/{code}` returns only
  the code, name and whether a guest has joined — never the operator, the device
  or the session id. *Test:* `test_the_connector_never_reveals_another_session`.
- **Session codes carry about 40 bits** (8 characters, 31-character alphabet)
  and avoid visually ambiguous characters because the code is read aloud. That
  is adequate *because* guessing is now rate limited; it would not be otherwise.
  *Test:* `test_session_codes_have_enough_entropy`.
- **Operator input cannot reach the guest from a text field**, so a password
  typed into the console's terminal panel is not also typed onto the endpoint's
  screen. *Test:* `tests/e2e/p4_console_tools.py`.

---

## Open

### Session codes never expire — MEDIUM

A pending session stays joinable indefinitely. A code shared over chat months
ago still works. It should expire after a short window, and be single-use once a
guest has joined.

### TLS is configured but has never been run — MEDIUM

`infra/nginx-tls.conf` and the compose overlay exist and are correct as written,
but no deployment has used them. Section 9 requires encrypted transport, and
until a deployment actually serves TLS this is unverified. Agents must use
`wss://`; nothing currently stops an operator pointing one at `ws://`.

### The remote terminal is a full shell as the endpoint user — BY DESIGN

Section 4 asks for "a shell on the endpoint", so this is the feature, not a
flaw. Worth stating plainly: an operator with a session has the same access as
the person sitting at the machine. It is bounded by consent, the tray indicator
and the audit trail rather than by permissions.

### File transfer reaches anything the endpoint user can — BY DESIGN

Paths are resolved before use, so no traversal trick reaches beyond what that
user could already open themselves. Same bound as the terminal.

### Unsigned builds — MEDIUM

Section 11 assumes code-signing certificates can be procured; they have not
been. The Windows build triggers SmartScreen and macOS Gatekeeper refuses an
unsigned download outright. CI signs automatically once the certificates are
added as repository secrets.

### No account lockout or password policy — LOW

Rate limiting slows guessing but nothing locks an account after repeated
failures, and no policy governs password strength. The seeded default
(`ChangeMe123!`) is documented as a development credential and must be changed
before deployment.

### Windows and macOS endpoints are unverified — MEDIUM

Both agents now build in CI, but neither has run. The consent surface, tray
indicator and privacy blank are unproven on those platforms, and all three are
security-relevant.
