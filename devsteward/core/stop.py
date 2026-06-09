"""The two-level graceful-stop seam the run/advance drivers own (REQ-025 D7).

A :class:`StopController` holds a stop flag plus the active ``claude`` child handle and
installs a SIGINT handler. The engine — not a skill — owns run lifecycle (the
ledger-contract principle), so the drivers create one controller per run, install it, and
thread its :meth:`should_stop` predicate into the account provider's interruptible waits and
the executor loop.

Two levels (ported from ``run_batch._sigint``/``_interruptible_sleep``):

* **1st Ctrl-C** — set the flag. The executor finishes the running step and then exits
  without starting the next; an in-progress quota wait ends at once (it polls the flag).
* **2nd Ctrl-C** — kill the active ``claude`` **process group** and exit ``130``.

Killing by process group is correct precisely because :func:`devsteward.core.claude.run_claude`
now spawns ``claude`` with ``start_new_session=True``, so the child leads its own group and a
parent SIGINT is **not** forwarded to it (the engine owns the signal).
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
import subprocess
from typing import Callable


class StopController:
    def __init__(self) -> None:
        self._flag = threading.Event()
        self._child: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # -- predicate / child registration ----------------------------------------

    def should_stop(self) -> bool:
        return self._flag.is_set()

    def request_stop(self) -> None:
        self._flag.set()

    def register_child(self, proc: subprocess.Popen) -> None:
        """Record the active ``claude`` child so a 2nd Ctrl-C can kill its group.

        Shaped as an ``on_spawn`` callback so :mod:`devsteward.core.claude` stays ignorant of
        the controller (no import cycle)."""
        with self._lock:
            self._child = proc

    def clear_child(self) -> None:
        with self._lock:
            self._child = None

    # -- signal handling -------------------------------------------------------

    def install(self) -> None:
        """Install the SIGINT handler. Best-effort: ``signal.signal`` only works on the main
        thread, so a non-main-thread caller (e.g. a test harness) silently keeps the default."""
        try:
            signal.signal(signal.SIGINT, self._on_sigint)
        except ValueError:
            pass

    def _on_sigint(self, *_args) -> None:
        if self._flag.is_set():
            # 2nd Ctrl-C: kill the running child's process group and force-quit.
            with self._lock:
                proc = self._child
            if proc is not None and proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            sys.exit(130)
        # 1st Ctrl-C: finish the current step, then stop.
        self._flag.set()

    # -- interruptible wait ----------------------------------------------------

    def interruptible_sleep(self, seconds: float) -> None:
        """Sleep up to ``seconds``, returning early as soon as the stop flag is set."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._flag.is_set():
                return
            time.sleep(min(5.0, max(0.0, deadline - time.monotonic())))
