"""Endpoint agent CLI.

    python -m rmm_agent join --relay ws://relay.example:8000 --code ABCD1234
    python -m rmm_agent enrol --relay ws://relay.example:8000 \
        --device-id <uuid> --secret <enrolment-secret>
    python -m rmm_agent status
"""
import argparse
import asyncio
import logging
import signal
import sys
import threading

from rmm_agent import __version__, background, launcher, platform_support, sysinfo
from rmm_agent import config
from rmm_agent.config import Enrolment, state_dir
from rmm_agent.device import hold_presence
from rmm_agent.logging_setup import configure
from rmm_agent import autostart, diagnostics
from rmm_agent.session import AgentSession
from rmm_agent.tray import Tray

log = logging.getLogger("rmm_agent")


def _run_with_tray(coroutine_factory, use_tray: bool, on_user_quit=None) -> int:
    """The tray owns the main thread, so the event loop runs beside it."""
    loop = asyncio.new_event_loop()
    result: dict[str, BaseException | None] = {"error": None}
    session_holder: dict[str, object] = {}

    def stop_everything() -> None:
        session = session_holder.get("session")
        if session is not None:
            loop.call_soon_threadsafe(session.request_stop)  # type: ignore[union-attr]

    def user_quit() -> None:
        # The person chose to end it, as opposed to the computer shutting down.
        if on_user_quit is not None:
            on_user_quit()
        stop_everything()

    tray = Tray(on_quit=user_quit) if use_tray else None

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

    try:
        def on_terminate(*_):
            # Between connection attempts there is no session to ask to stop,
            # so the request would be lost and `rmm-agent stop` would hang.
            if session_holder.get("session") is None:
                raise SystemExit(0)
            stop_everything()

        signal.signal(signal.SIGTERM, on_terminate)
    except (ValueError, OSError):
        pass  # not the main thread, or not supported here

    if tray is not None and tray.available:
        try:
            tray.run()  # blocks until the tray quits
        except KeyboardInterrupt:
            pass
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
    background.write_pid()
    try:
        return _join(args)
    finally:
        background.clear_pid()


def _join(args) -> int:
    diagnostics.heartbeat()
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
            on_over=lambda: autostart.forget(args.code),
            device_id=args.device_id,
            device_secret=args.secret,
            blank_watchdog=args.blank_watchdog,
            blank_blocks_input=args.blank_blocks_input,
        )
        holder["session"] = session
        await session.run_forever()

    return _run_with_tray(
        main, use_tray=args.tray, on_user_quit=lambda: autostart.forget(args.code)
    )


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


def cmd_start(args) -> int:
    """The friendly path: a window if one is needed, otherwise straight to consent.

    The people being helped are not going to open a terminal. A code that came
    with the download is used as it is; with none, a small window asks.
    """
    launcher.hide_console_if_owned()
    chosen = launcher.resolve(config.default_relay(), getattr(args, "code", "") or "")
    if chosen is None:
        return 0
    code, relay = chosen
    config.save_relay(relay)
    remembered = autostart.remember(relay, code)

    no_tray = bool(getattr(args, "no_tray", False))

    # Started from a terminal: hand over to a process that does not belong to
    # it, so closing the terminal or pressing Ctrl+C there does not end the
    # session. A double-click has no terminal, so it just carries on.
    if not getattr(args, "foreground", False) and background.launched_from_terminal():
        extra = ["join", "--relay", relay, "--code", code]
        if no_tray:
            extra.append("--no-tray")
        pid = background.spawn_detached(extra)
        print(f"RMM Agent is running in the background (process {pid}).")
        print("You can close this window. To stop it later: rmm-agent stop")
        if remembered:
            print("It will start again after you restart this computer, until you stop it.")
        return 0

    joined = argparse.Namespace(
        relay=relay, code=code, fps=12, quality=60, budget_kbps=0,
        device_id="", secret="", synthetic=False, tray=not no_tray, inject=True,
        auto_consent=False, blank_watchdog=0.0, blank_blocks_input=True,
    )
    try:
        return cmd_join(joined)
    except Exception as exc:
        log.exception("the session failed")
        launcher.show_error(f"Could not start the session.\n\n{exc}")
        return 1


def cmd_stop(_args) -> int:
    autostart.forget()  # stopping on purpose also means: do not start again
    if background.stop():
        print("RMM Agent stopped.")
        return 0
    print("RMM Agent is not running.")
    return 0


def cmd_resume(_args) -> int:
    """Rejoin the session remembered before the computer restarted."""
    remembered = autostart.saved()
    if remembered is None:
        return 0
    relay, code = remembered
    joined = argparse.Namespace(
        relay=relay, code=code, fps=12, quality=60, budget_kbps=0,
        device_id="", secret="", synthetic=False, tray=True, inject=True,
        auto_consent=False, blank_watchdog=0.0, blank_blocks_input=True,
    )
    return cmd_join(joined)


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
    running = background.running_pid()
    print(f"running       : {'yes, process ' + str(running) if running else 'no'}")

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

    start = sub.add_parser(
        "start", help="open the friendly window (what a double-click does)", parents=[common]
    )
    start.add_argument("--code", default="", help="a session code to use without asking")
    start.add_argument(
        "--foreground", action="store_true",
        help="stay in this terminal instead of running in the background",
    )
    start.add_argument("--no-tray", dest="no_tray", action="store_true")
    start.set_defaults(func=cmd_start)

    stop = sub.add_parser(
        "stop", help="stop the agent running in the background", parents=[common]
    )
    stop.set_defaults(func=cmd_stop)

    resume = sub.add_parser(
        "resume",
        help="rejoin the session remembered before a restart (used at login)",
        parents=[common],
    )
    resume.set_defaults(func=cmd_resume)

    join = sub.add_parser("join", help="join a session with its code", parents=[common])
    join.add_argument(
        "--relay", default=config.default_relay() or "ws://localhost:8000",
        help="relay WebSocket base URL (defaults to the server this agent was built for)",
    )
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
    if len(sys.argv) == 1:
        # A double-click: no arguments at all.
        configure(False)
        diagnostics.install()
        return cmd_start(argparse.Namespace(code=""))
    args = build_parser().parse_args()
    path = configure(args.verbose)
    diagnostics.install()
    log.debug("logging to %s", path)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
