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
from enum import Enum
from typing import Callable


class BudgetVerdict(str, Enum):
    """What the budget oracle says *right now* — one non-waiting probe (REQ-080).

    ``precheck`` collapses clauder's verdict to ``(ok, reason)``, which is all a step-start
    gate needs but not enough to corroborate an ambiguous session death (REQ-080 Decision 2)
    or to tell a **degraded** gate from a genuine ``proceed`` (Decision 6). This enum is that
    finer read; :meth:`ClauderAccountProvider.budget_verdict` produces it.
    """

    #: clauder says the budget is out — ``wait`` (75) or ``unsatisfiable`` (69).
    EXHAUSTED = "exhausted"
    #: clauder says there is budget — ``proceed``/``switch`` (0).
    AVAILABLE = "available"
    #: there is **no oracle**: clauder is absent from PATH, or the gate call failed/timed
    #: out and the provider degraded open. Never a budget claim — the absence of one.
    NO_ORACLE = "no-oracle"


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

    An optional ``pin=N`` (REQ-061) narrows the gate to ``clauder gate --pin N``: clauder
    then judges admission on account N alone and performs any switch to N, so the operator
    can drain N's 7-day budget before it resets. The provider only forwards N — it reads no
    usage and adds no fallback (clauder REQ-006 owns the pinned switch). With ``pin`` omitted
    the invocation is the combined-budget gate unchanged.

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
        pin: int | None = None,
        announce: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        poll_seconds: int = 60,
        run: Callable[..., subprocess.CompletedProcess] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        self.threshold = _normalize_threshold(threshold)
        # REQ-061: optional account pin. When set, every gate is `clauder gate --pin N`;
        # clauder judges admission on account N alone (so the operator can drain N's 7d
        # window before it resets). DevSteward only forwards N — it interprets nothing and
        # adds no fallback (clauder REQ-006 owns the pinned switch). When None, the gate is
        # the REQ-058 combined-budget invocation, byte-for-byte unchanged.
        self.pin = pin
        self.announce = announce or (lambda _msg: None)
        self.should_stop = should_stop or (lambda: False)
        # Fallback poll cadence for a ``wait`` verdict that carries no ``wait_seconds``.
        self.poll_seconds = poll_seconds
        self._run = run or subprocess.run
        self._sleep = sleep or time.sleep
        self.clauder = shutil.which("clauder")
        # REQ-080 Decision 5: how many times :meth:`precheck` has actually *slept* on a
        # ``wait`` verdict. The executor's consecutive-limit guard reads it across a precheck
        # to tell "the budget window genuinely moved" from "clauder keeps saying proceed and
        # sessions keep dying instantly" — a real gate wait resets the streak.
        self.wait_count = 0

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
        optional and must never hard-fail a run — and marks the body ``degraded: True``.
        :meth:`precheck` ignores that flag (rc 0 admits either way, unchanged); only
        :meth:`budget_verdict` reads it, because a fabricated ``proceed`` is the *absence*
        of an oracle, not a budget claim, and REQ-080 Decision 6 must not resume on it. A
        malformed JSON body still honours the exit code; the missing fields just fall back
        to their defaults."""
        argv = [self.clauder, "gate", "--threshold", f"{self.threshold:g}"]
        if self.pin is not None:
            argv += ["--pin", str(self.pin)]  # REQ-061: judge admission on account N alone
        argv.append("--json")
        try:
            proc = self._run(argv, capture_output=True, text=True, timeout=self._TIMEOUT)
        except (subprocess.SubprocessError, OSError):
            return 0, {
                "decision": "proceed",
                "reason": "clauder gate unavailable — proceeding",
                "degraded": True,
            }
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
                self.wait_count += 1  # REQ-080 D5: the guard's "the window moved" signal
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

    def budget_verdict(self) -> tuple[BudgetVerdict, str]:
        """Probe the budget oracle **once**, without waiting (REQ-080).

        The read-only sibling of :meth:`precheck`: same ``clauder gate`` chokepoint, same
        verdict mapping, but it never sleeps, never re-gates, and never admits anything — it
        just reports what clauder says right now. The executor uses it at the *moment a
        session dies*, for two questions ``precheck``'s ``(ok, reason)`` cannot answer:

        * **Corroborate an ambiguous death** (Decision 2): an ``Outcome.ERROR`` that missed
          the runtime's limit markers but coincides with an ``EXHAUSTED`` verdict is a limit
          interruption, not a code error. This keeps the runtime signal primary (REQ-016) and
          spends the *oracle the engine already trusts* on the ambiguity, instead of chasing
          every future wording of the limit message into ``_LIMIT_MARKERS``.
        * **Is there an oracle at all** (Decision 6): ``NO_ORACLE`` means auto-resume must not
          engage — without clauder there is no honest signal for when the budget clears, and
          the engine will not blind-poll. Note this is *not* ``ok=False``: the run still
          proceeds through ``precheck``'s open degradation; it simply will not ride out a
          limit.

        Waiting is emphatically **not** this method's job — that machinery already exists in
        :meth:`precheck` and is reached by the run loop's next iteration (Decision 3)."""
        if not self.available:
            return BudgetVerdict.NO_ORACLE, "clauder absent — no budget oracle"
        rc, info = self._gate()
        reason = info.get("reason") or ""
        if info.get("degraded"):
            return BudgetVerdict.NO_ORACLE, "clauder gate unavailable — no budget oracle"
        if rc in (self._EXIT_WAIT, self._EXIT_UNSATISFIABLE):
            verdict = "wait" if rc == self._EXIT_WAIT else "unsatisfiable"
            return BudgetVerdict.EXHAUSTED, f"clauder: {verdict}" + (
                f" ({reason})" if reason else ""
            )
        decision = info.get("decision") or ("proceed" if rc == 0 else f"exit {rc}")
        return BudgetVerdict.AVAILABLE, f"clauder: {decision}" + (
            f" ({reason})" if reason else ""
        )

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
