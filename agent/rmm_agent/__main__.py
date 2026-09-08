"""Endpoint agent CLI.

    python -m rmm_agent join --relay ws://relay.example:8000 --code ABCD1234
    python -m rmm_agent enrol --relay ws://relay.example:8000 \
        --device-id <uuid> --secret <enrolment-secret>
    python -m rmm_agent status
"""
import argparse
import asyncio
import logging
import sys
import threading

from rmm_agent import __version__, platform_support, sysinfo
from rmm_agent.config import Enrolment, state_dir
from rmm_agent.device import hold_presence
from rmm_agent.logging_setup import configure
from rmm_agent.session import AgentSession
from rmm_agent.tray import Tray

log = logging.getLogger("rmm_agent")


def _run_with_tray(coroutine_factory, use_tray: bool) -> int:
    """The tray owns the main thread, so the event loop runs beside it."""
    loop = asyncio.new_event_loop()
    result: dict[str, BaseException | None] = {"error": None}
    session_holder: dict[str, object] = {}

    def stop_everything() -> None:
        session = session_holder.get("session")
        if session is not None:
            loop.call_soon_threadsafe(session.request_stop)  # type: ignore[union-attr]

    tray = Tray(on_quit=stop_everything) if use_tray else None

    def worker() -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coroutine_factory(tray, session_holder))
        except BaseException as exc:  # reported on the main thread
            result["error"] = exc
        finally:
            if tray is not None:
                tray.stop()

    thread = threading.Thread(target=worker, name="agent-loop", daemon=True)
    thread.start()

    if tray is not None and tray.available:
        tray.run()  # blocks until the tray quits
        stop_everything()
        thread.join(timeout=15)
    else:
        # No tray to hold the main thread, so the event loop is the whole
        # program: wait for it rather than dropping out from under it.
        try:
            while thread.is_alive():
                thread.join(timeout=0.5)
        except KeyboardInterrupt:
            stop_everything()
            thread.join(timeout=15)

    error = result["error"]
    if error is not None and not isinstance(error, (KeyboardInterrupt, SystemExit)):
        log.error("agent stopped: %s", error)
        return 1
    return 0


def cmd_join(args) -> int:
    async def main(tray, holder):
        session = AgentSession(
            args.relay,
            args.code,
            tray=tray,
            fps=args.fps,
            quality=args.quality,
            budget_kbps=args.budget_kbps,
            synthetic=args.synthetic,
            inject=args.inject,
            auto_consent=args.auto_consent,
            device_id=args.device_id,
            device_secret=args.secret,
            blank_watchdog=args.blank_watchdog,
            blank_blocks_input=args.blank_blocks_input,
        )
        holder["session"] = session
        await session.run_forever()

    return _run_with_tray(main, use_tray=args.tray)


def cmd_enrol(args) -> int:
    enrolment = Enrolment(device_id=args.device_id, secret=args.secret, relay_url=args.relay)
    path = enrolment.save()
    print(f"enrolled; credentials stored at {path}")

    if args.no_connect:
        return 0

    async def main(tray, holder):
        stop = asyncio.Event()
        holder["session"] = type("Stoppable", (), {"request_stop": stop.set})()
        if tray:
            tray.set_state("connected", "Enrolled — waiting for a session")
        await hold_presence(enrolment.relay_url, enrolment.device_id, enrolment.secret, stop)

    return _run_with_tray(main, use_tray=args.tray)


def cmd_status(_args) -> int:
    platform_support.prepare()
    info = sysinfo.collect()
    enrolment = Enrolment.load()
    print(f"agent version : {__version__}")
    print(f"platform      : {sysinfo.platform_key()} ({info['os']} {info['os_version']})")
    print(f"hostname      : {info['hostname']}")
    print(f"user          : {info['user']}")
    print(f"ip            : {info['ip']}")
    print(f"state dir     : {state_dir()}")
    print(f"enrolled      : {'yes, device ' + enrolment.device_id if enrolment else 'no'}")

    from rmm_agent.capture import ScreenCapture
    from rmm_agent.remote_input import InputInjector

    capture = ScreenCapture()
    print(f"capture       : {'synthetic (no display)' if capture.synthetic else 'screen'}")
    print(f"capture path  : {capture.backend}")
    for monitor in capture.monitors:
        print(f"  monitor {monitor['index']}   : {monitor['label']} "
              f"{monitor['width']}x{monitor['height']} "
              f"at {monitor.get('left', 0)},{monitor.get('top', 0)}")
    print(f"input         : {'available' if InputInjector().available else 'unavailable'}")
    print(f"tray          : {'available' if Tray(lambda: None).available else 'unavailable'}")
    print(f"clipboard     : {'available' if _clipboard_available() else 'unavailable'}")

    if platform_support.LINUX:
        print(f"session type  : {platform_support.session_type()}")
    if platform_support.MACOS:
        print(f"screen record : {_permission(platform_support.screen_recording_permission())}")
        print(f"accessibility : {_permission(platform_support.accessibility_permission())}")

    notes = platform_support.warnings()
    if notes:
        print()
        for note in notes:
            print(f"  ! {note}")
    return 0


def _permission(value) -> str:
    if value is True:
        return "granted"
    if value is False:
        return "NOT GRANTED"
    return "unknown"


def _clipboard_available() -> bool:
    from rmm_agent import clipboard

    return clipboard.available()


def build_parser() -> argparse.ArgumentParser:
    # --verbose is accepted either before or after the subcommand, because
    # argparse's default of "globals first" is a trap nobody expects.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--verbose", action="store_true", default=argparse.SUPPRESS,
        help="log at debug level",
    )

    parser = argparse.ArgumentParser(
        prog="rmm_agent", description=__doc__, parents=[common]
    )
    parser.set_defaults(verbose=False)
    sub = parser.add_subparsers(dest="command", required=True)

    join = sub.add_parser("join", help="join a session with its code", parents=[common])
    join.add_argument("--relay", default="ws://localhost:8000", help="relay WebSocket base URL")
    join.add_argument("--code", required=True)
    join.add_argument("--fps", type=int, default=12)
    join.add_argument("--quality", type=int, default=60)
    join.add_argument(
        "--budget-kbps", type=int, default=0,
        help="adapt quality and frame rate to this bandwidth budget (0 = off)",
    )
    join.add_argument("--device-id", default="", help="for an unattended session")
    join.add_argument("--secret", default="", help="for an unattended session")
    join.add_argument("--synthetic", action="store_true", help="stream a generated test image")
    join.add_argument("--no-tray", dest="tray", action="store_false", help="run without a tray icon")
    join.add_argument(
        "--no-input", dest="inject", action="store_false",
        help="log operator input instead of applying it (used by the tests)",
    )
    join.add_argument(
        "--blank-watchdog", type=float, default=0.0, metavar="SECONDS",
        help="release the privacy blank automatically after this long (0 = off)",
    )
    join.add_argument(
        "--blank-no-input-block", dest="blank_blocks_input", action="store_false",
        help="blank the screen without blocking local input - TESTING ONLY, so a "
             "test run cannot lock the machine it is running on",
    )
    join.add_argument(
        "--auto-consent", action="store_true",
        help="skip the consent prompt - TESTING ONLY, never for real use",
    )
    join.set_defaults(func=cmd_join)

    enrol = sub.add_parser(
        "enrol", help="store unattended credentials and stay reachable", parents=[common]
    )
    enrol.add_argument("--relay", default="ws://localhost:8000")
    enrol.add_argument("--device-id", required=True)
    enrol.add_argument("--secret", required=True)
    enrol.add_argument("--no-tray", dest="tray", action="store_false")
    enrol.add_argument("--no-connect", action="store_true", help="store credentials and exit")
    enrol.set_defaults(func=cmd_enrol)

    status = sub.add_parser(
        "status", help="report what this machine supports", parents=[common]
    )
    status.set_defaults(func=cmd_status)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    path = configure(args.verbose)
    log.debug("logging to %s", path)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
