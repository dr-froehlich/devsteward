"""Account / quota provider — delegate the budget gate to the external ``clauder`` CLI.

REQ-058: DevSteward no longer hand-rolls a per-account cswap gate. The sibling tool
**clauder** (`/home/peter/projects/clauder`) is the budget/account **policy layer** over
cswap: cswap stays the mechanism (credentials, raw usage, ``--switch-to``); clauder decides
*proceed / switch / wait* against the **combined** remaining budget of all accounts and tells
cswap when to switch. The engine treats clauder as an optional, black-box external tool — it
shells ``clauder gate`` at every step boundary, reads its JSON + exit code, and **never**
touches cswap or ``usage.json`` directly. This adds *no second account switcher*: the only
place a cswap switch can be serialised against a background ``clauder monitor`` is inside
clauder, so the engine presents exactly one indirect chokepoint (REQ-058 Decision 3).

``clauder gate --threshold T --json`` emits ``{decision, account, reason, wait_seconds,
partial}`` and exits 0 (``proceed``/``switch``), 75 (``wait``), or 69 (``unsatisfiable``).

Everything is optional and self-degrading: when ``clauder`` is absent from PATH, or a gate
invocation fails/times out, :meth:`precheck` proceeds with the gate skipped and logs
"proceeding without quota check". A flaky external tool never hard-fails a run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from typing import Callable


def _normalize_threshold(t: float) -> float:
    """Accept a fraction (``0.70``) or a percent (``70``); normalise to **percent**.

    clauder's ``--threshold`` is a percent, so this is the value passed straight through."""
    return t * 100.0 if t <= 1 else float(t)


class ClauderAccountProvider:
    """Delegate the per-step budget gate to the external ``clauder gate`` CLI (REQ-058).

    At each step boundary :meth:`precheck` shells ``clauder gate --threshold T --json`` and
    maps clauder's verdict (exit code, with the JSON for detail) onto the ``(ok, reason)``
    contract:

    * exit 0 (``proceed``/``switch``) → ``ok=True``; clauder has already performed any switch.
    * exit 75 (``wait``) → sleep ``wait_seconds`` interruptibly (honouring ``should_stop``),
      then **re-gate**; a stop requested during the wait returns ``ok=False``.
    * exit 69 (``unsatisfiable``) → ``ok=False`` — the run stops.

    All account interaction routes through this single ``clauder gate`` chokepoint: the
    provider issues no direct ``cswap`` call and reads no ``usage.json`` (Decision 3 — no
    second switcher). When ``clauder`` is not on PATH — or a gate invocation fails — the gate
    degrades to ``(True, "… proceeding without quota check")`` (Decision 4 — clauder is an
    optional external tool, discovered on PATH like cswap was). The engine never starts,
    stops, or supervises ``clauder monitor`` (Decision 2 — it runs out-of-band).
    """

    _TIMEOUT = 30
    # clauder's exit codes for a gate verdict (clauder/gate.py EXIT_CODES); proceed/switch = 0.
    _EXIT_WAIT = 75
    _EXIT_UNSATISFIABLE = 69

    def __init__(
        self,
        *,
        threshold: float = 70.0,
        announce: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        poll_seconds: int = 60,
        run: Callable[..., subprocess.CompletedProcess] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        self.threshold = _normalize_threshold(threshold)
        self.announce = announce or (lambda _msg: None)
        self.should_stop = should_stop or (lambda: False)
        # Fallback poll cadence for a ``wait`` verdict that carries no ``wait_seconds``.
        self.poll_seconds = poll_seconds
        self._run = run or subprocess.run
        self._sleep = sleep or time.sleep
        self.clauder = shutil.which("clauder")

    @property
    def available(self) -> bool:
        return self.clauder is not None

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep up to ``seconds`` in short chunks, polling :attr:`should_stop` between them
        so a stop is honored promptly rather than after a possibly hours-long wait."""
        remaining = seconds
        while remaining > 0:
            if self.should_stop():
                return
            chunk = min(5.0, remaining)
            self._sleep(chunk)
            remaining -= chunk

    def _gate(self) -> tuple[int, dict]:
        """Run ``clauder gate`` once; return ``(returncode, parsed_json)``.

        A launch failure / timeout degrades **open** (exit 0, ``proceed``) — clauder is
        optional and must never hard-fail a run. A malformed JSON body still honours the
        exit code; the missing fields just fall back to their defaults."""
        argv = [self.clauder, "gate", "--threshold", f"{self.threshold:g}", "--json"]
        try:
            proc = self._run(argv, capture_output=True, text=True, timeout=self._TIMEOUT)
        except (subprocess.SubprocessError, OSError):
            return 0, {"decision": "proceed", "reason": "clauder gate unavailable — proceeding"}
        try:
            info = json.loads(proc.stdout)
            if not isinstance(info, dict):
                info = {}
        except (json.JSONDecodeError, TypeError, ValueError):
            info = {}
        return proc.returncode, info

    def precheck(self) -> tuple[bool, str]:
        """Gate each step by delegating to ``clauder gate``; see the class docstring.

        Returns ``(ok, reason)``. ``ok=False`` happens only on a stop, or an
        ``unsatisfiable`` verdict (the combined budget cannot carry the job at all)."""
        if not self.available:
            msg = "clauder absent — proceeding without quota check"
            self.announce(msg)
            return True, msg

        while True:
            if self.should_stop():
                return False, "stop requested"
            rc, info = self._gate()
            reason = info.get("reason") or ""

            if rc == self._EXIT_WAIT:
                wait = info.get("wait_seconds")
                secs = wait if isinstance(wait, (int, float)) and wait > 0 else self.poll_seconds
                self.announce(
                    f"clauder: wait ~{int(secs)}s ({reason or 'budget saturated'}) — re-gating"
                )
                self._interruptible_sleep(secs)
                continue  # re-gate; a stop during the wait is caught at the top of the loop

            if rc == self._EXIT_UNSATISFIABLE:
                msg = f"clauder: unsatisfiable — stopping run ({reason or 'budget exhausted'})"
                self.announce(msg)
                return False, msg

            # rc == 0 (proceed/switch) — or any unexpected code: degrade open and admit.
            decision = info.get("decision") or ("proceed" if rc == 0 else f"exit {rc}")
            msg = f"clauder: {decision}" + (f" ({reason})" if reason else "")
            self.announce(msg)
            return True, msg

    def claude_argv(self) -> list[str]:
        # clauder, like cswap, is a switcher: it has already mutated the active account in
        # precheck(), so the launch is always plain ``claude`` — never a wrapped command.
        return ["claude"]


class SingleAccountProvider:
    """Plain ``claude`` with no quota machinery (used by tests and minimal setups)."""

    def precheck(self) -> tuple[bool, str]:
        return True, "single-account — no quota check"

    def claude_argv(self) -> list[str]:
        return ["claude"]
