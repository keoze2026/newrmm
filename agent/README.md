# Endpoint agent

The production endpoint agent is Phase 2 work: enrolment, screen capture, input
injection, tray presence and the consent surface, packaged per OS.

## `dev_guest.py` — development guest

`dev_guest.py` is a stand-in that joins a session and streams a screen, so the
operator console's live behaviour can be exercised and tested for real today.
It is **not** the Phase 2 agent: no installer, no tray, no consent surface, no
unattended enrolment, and it has only ever been run on Linux.

```bash
# Real screen of this machine
python agent/dev_guest.py --code ABCD1234

# Generated test image - no display needed, safe on a headless box
python agent/dev_guest.py --code ABCD1234 --synthetic

# Log operator input instead of injecting it (what the test suite uses, so a
# test run never takes over the real mouse and keyboard)
python agent/dev_guest.py --code ABCD1234 --synthetic --no-input
```

Options: `--url` (relay WebSocket base, default `ws://localhost:8000`),
`--fps`, `--quality`.

## Protocol it speaks

Connects to `ws://<relay>/ws/guest/<CODE>` and sends one JSON hello:

```json
{"host_name": "...", "system_info": {...}, "monitors": [{"index": 0, "label": "...", "width": 0, "height": 0}]}
```

Then binary JPEG frames, continuously. It receives JSON control messages:

| Message | Meaning |
| --- | --- |
| `{"type":"input","kind":"mouse","action":"move\|down\|up","x":0..1,"y":0..1,"button":"left"}` | Pointer, in normalised coordinates |
| `{"type":"input","kind":"key","action":"down\|up","key":"a"}` | Keyboard |
| `{"type":"input","kind":"scroll","dx":0,"dy":0}` | Wheel |
| `{"type":"monitor","index":0}` | Switch captured display |
| `{"type":"blank","on":true}` | Privacy blank |

Coordinates are normalised 0..1 so the guest lands on the right pixel no matter
how the operator's canvas is scaled or letterboxed.
