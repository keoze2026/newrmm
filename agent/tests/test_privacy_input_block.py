"""The guest-lock's input block, checked without risking the machine.

Blocking local input is the half of the guest-lock that matters: a black screen
someone can still type behind is not a lock. But a test that grabs the keyboard
and then fails would leave this machine unusable, so the grab happens in a
throwaway subprocess with a hard watchdog, and the subprocess is killed
outright if it overruns.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Runs in its own process: grabs input, reports what it managed, releases.
CHILD = """
import json, sys, time
sys.path.insert(0, %r)
from rmm_agent import privacy

blank = privacy.PrivacyBlank(watchdog_seconds=3.0)
result = {}
try:
    state = blank.enable(block_input=True)
    result["enabled"] = state["active"]
    result["mode"] = state["mode"]
    result["input_blocked"] = state["input_blocked"]
    # The watchdog must release it even if nothing else does.
    deadline = time.monotonic() + 10
    while blank.active and time.monotonic() < deadline:
        time.sleep(0.2)
    result["released_by_watchdog"] = not blank.active
finally:
    blank.disable()
    result["input_released"] = not blank.state()["input_blocked"]
print("RESULT " + json.dumps(result))
""" % str(ROOT)


def test_the_guest_lock_blocks_input_and_always_releases_it():
    process = subprocess.run(
        [sys.executable, "-c", CHILD],
        capture_output=True, text=True, timeout=45,
    )
    line = next(
        (l for l in process.stdout.splitlines() if l.startswith("RESULT ")), None
    )
    assert line, f"the child did not report:\nstdout={process.stdout}\nstderr={process.stderr}"

    import json

    result = json.loads(line[len("RESULT "):])
    assert result["enabled"] is True, result
    assert result["mode"] == "guest-lock", result
    assert result["input_blocked"] is True, "local input was not blocked"
    assert result["released_by_watchdog"] is True, "the watchdog did not release the lock"
    assert result["input_released"] is True, "the input block was left in place"
