"""The environment for programs the agent starts that are not part of it.

A packaged agent points the library search path at the copies of libraries it
carries. A system program started with that path loads the agent's copies
instead of its own and can fail outright: `systemctl` died with
"libcrypto.so.3: version `OPENSSL_3.4.0' not found", so the auto-start service
was never turned on. The operator's remote shell inherits the same path, so
commands run in it could fail the same way. PyInstaller keeps the original
value for exactly this.
"""
import os

_PATHS = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH")


def system_environment(base=None) -> dict:
    """A copy of the environment, with the library path put back as it was."""
    env = dict(os.environ if base is None else base)
    for name in _PATHS:
        original = env.pop(f"{name}_ORIG", None)
        if original is not None:
            env[name] = original
        else:
            env.pop(name, None)
    return env
