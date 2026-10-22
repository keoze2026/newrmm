"""Turning a consented session into an always-on device.

The person chose "Always allow" in the consent window. The agent asks the relay
to make this session a standing one for this computer and keeps the credentials
the relay hands back. From then on the computer stays online by itself, starts
again after a restart or sleep, and joins when an operator opens that session,
without asking again.
"""
import json
import logging
import socket
import time
import urllib.error
import urllib.request

from rmm_agent import sysinfo
from rmm_agent.config import Enrolment
from rmm_agent.launcher import to_http

log = logging.getLogger(__name__)


def enrol(relay_url: str, code: str, attempts: int = 5, wait: float = 1.0) -> Enrolment | None:
    """Enrol this computer through its live session. None if it did not work."""
    body = json.dumps(
        {"code": code, "name": socket.gethostname(), "os": sysinfo.platform_key()}
    ).encode()
    url = f"{to_http(relay_url)}/connector/enrol"

    for attempt in range(attempts):
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode())
            enrolment = Enrolment(data["device_id"], data["secret"], relay_url)
            enrolment.save()
            log.info("this computer is now enrolled as device %s", data["device_id"])
            return enrolment
        except urllib.error.HTTPError as exc:
            # 409: the relay has not recorded the consent yet. It follows the
            # consent message by a moment, so try again.
            if exc.code == 409 and attempt < attempts - 1:
                time.sleep(wait)
                continue
            log.warning("could not enrol this computer (%s)", exc.code)
            return None
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            log.warning("could not enrol this computer: %s", exc)
            return None
    return None
