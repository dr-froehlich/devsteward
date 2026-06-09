"""Account / quota provider — claude-swap (``cswap``) numeric, visible, gate-and-rotate.

The quota machinery is the port REQ-001 always wanted: it mirrors the proven shapes in
``Theresa/run_batch.py`` (``usage_snapshot`` / ``pick_and_ensure_account``) **minus** the
adaptive cost-history gate (REQ-025 D4). **claude-swap 0.11 is a switcher, not a command
wrapper**: it mutates the active account in ``~/.claude.json`` via flags (``--switch-to N``,
``--list``), and afterwards you invoke plain ``claude``. There is no ``exec`` subcommand, so
the engine never wraps ``claude`` — it reads cswap's cached ``usage.json`` for per-slot
5h/7d budget, gates/rotates/waits in :meth:`precheck`, then launches ``claude`` directly.

Everything is optional and self-degrading (REQ-025 D9): when ``cswap`` is absent, or its
``usage.json`` is missing/unreadable, :meth:`precheck` proceeds on the **current** account
with the gate skipped and logs "proceeding without quota check". Every cswap interaction is
non-fatal: a failed switch, a missing file, a timeout — none ever hard-fails a run.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# cswap >= 0.11 stores its data under the XDG data dir; older builds used
# ~/.claude-swap-backup. Prefer whichever directory actually exists so a future move
# doesn't silently disable the quota check again (run_batch.py:72-81).
_CSWAP_DIRS = [
    Path.home() / ".local" / "share" / "claude-swap",
    Path.home() / ".claude-swap-backup",
]


def _cswap_data_dir() -> Path:
    return next((d for d in _CSWAP_DIRS if d.exists()), _CSWAP_DIRS[0])


@dataclass
class AccountUsage:
    """Per-slot quota snapshot, mirroring ``run_batch.AccountUsage`` exactly."""

    slot: int
    pct_5h: float
    pct_7d: float
    minutes_to_5h_reset: int
    clock_5h_reset: str


def _parse_countdown_to_minutes(s: str | None) -> int:
    """``"1d 2h 30m"`` → minutes (run_batch.py:169)."""
    if not s:
        return 0
    total = 0
    for unit, mult in (("d", 1440), ("h", 60), ("m", 1)):
        m = re.search(rf"(\d+)\s*{unit}", s)
        if m:
            total += int(m.group(1)) * mult
    return total


def usage_snapshot(
    data_dir: Path,
    *,
    force: bool = False,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[int, AccountUsage]:
    """Parse cswap's cached ``usage.json`` into per-slot 5h/7d% + reset countdown.

    Optionally refreshes the cache first via ``cswap --list`` (best-effort, ``NO_COLOR``,
    non-fatal). A **missing, unreadable, or malformed** ``usage.json`` returns ``{}`` — the
    degrade signal the caller turns into "proceed without quota check" (run_batch.py:191-223).
    """
    usage_cache = Path(data_dir) / "cache" / "usage.json"
    if force or not usage_cache.exists():
        try:
            run(
                ["cswap", "--list"],
                env={**os.environ, "NO_COLOR": "1"},
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.SubprocessError, OSError):
            pass  # non-fatal: fall through to read whatever is cached
    try:
        cache = json.loads(usage_cache.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[int, AccountUsage] = {}
    for slot_str, info in (cache.get("data", {}) or {}).items():
        if not isinstance(info, dict):
            continue
        h5 = info.get("five_hour") or {}
        d7 = info.get("seven_day") or {}
        try:
            slot = int(slot_str)
        except (TypeError, ValueError):
            continue
        out[slot] = AccountUsage(
            slot=slot,
            pct_5h=float(h5.get("pct", 0.0)),
            pct_7d=float(d7.get("pct", 0.0)),
            minutes_to_5h_reset=_parse_countdown_to_minutes(h5.get("countdown")),
            clock_5h_reset=h5.get("clock", "") or "",
        )
    return out


def _normalize_threshold(t: float) -> float:
    """Accept a fraction (``0.70``) or a percent (``70``); normalise to **percent**."""
    return t * 100.0 if t <= 1 else float(t)


class CswapAccountProvider:
    """Switch/gate the active account via ``cswap`` when present; else single-account.

    The fixed gate (default 70%, fraction or percent) never tightens adaptively (D4). With
    no pin the provider stays on the current account until it saturates, then switches to the
    lowest-7d below-threshold account (D2); with ``use=N`` it pins to slot N and waits for
    N's own reset rather than swapping (D6). When all eligible accounts are saturated it waits
    interruptibly for the soonest reset (D3); a stop requested during the wait is the only
    thing that ends the run early. Every decision is announced (D5).
    """

    _TIMEOUT = 30

    def __init__(
        self,
        use: int | None = None,
        *,
        threshold: float = 70.0,
        announce: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        poll_seconds: int = 60,
        data_dir: Path | None = None,
        run: Callable[..., subprocess.CompletedProcess] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        self.use = use
        self.threshold = _normalize_threshold(threshold)
        self.announce = announce or (lambda _msg: None)
        self.should_stop = should_stop or (lambda: False)
        self.poll_seconds = poll_seconds
        self.data_dir = Path(data_dir) if data_dir is not None else _cswap_data_dir()
        self._run = run or subprocess.run
        self._sleep = sleep or time.sleep
        self.cswap = shutil.which("cswap")

    @property
    def available(self) -> bool:
        return self.cswap is not None

    # -- snapshot / active slot ------------------------------------------------

    def _snapshot(self, *, force: bool = False) -> dict[int, AccountUsage]:
        return usage_snapshot(self.data_dir, force=force, run=self._run)

    def _active_slot(self) -> int:
        try:
            seq = json.loads((self.data_dir / "sequence.json").read_text())
            return int(seq["activeAccountNumber"])
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return 0

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep up to ``seconds`` in short chunks, polling :attr:`should_stop` between them
        so a stop is honored promptly rather than after a possibly hours-long wait
        (run_batch.py:122 fix b — the original plain ``sleep`` ignored Ctrl-C until it returned)."""
        remaining = seconds
        while remaining > 0:
            if self.should_stop():
                return
            chunk = min(5.0, remaining)
            self._sleep(chunk)
            remaining -= chunk

    # -- the gate-and-rotate loop ----------------------------------------------

    def precheck(self) -> tuple[bool, str]:
        """Gate, rotate, and wait until the active account is below the threshold.

        Returns ``(ok, reason)``. ``ok=False`` happens **only** when a stop was requested
        (D3): quota saturation waits through the reset, it never ends the run.
        """
        if not self.available:
            msg = "cswap absent — proceeding without quota check"
            self.announce(msg)
            return True, msg

        gate = self.threshold
        force = False  # after a quota wait, force-refresh cswap's cache so saturation lifts
        while True:
            if self.should_stop():
                return False, "stop requested"
            snap = self._snapshot(force=force)
            if not snap:
                msg = "usage snapshot empty — proceeding without quota check"
                self.announce(msg)
                return True, msg
            active = self._active_slot()

            if self.use is not None:
                done, result = self._gate_pinned(snap, active, gate)
            else:
                done, result = self._gate_rotate(snap, active, gate)
            if done:
                return result
            # The only not-done path is a quota wait; re-poll the live cache next loop.
            force = True

    def _gate_pinned(
        self, snap: dict[int, AccountUsage], active: int, gate: float
    ) -> tuple[bool, tuple[bool, str] | None]:
        """Pin to ``self.use``: switch to it, then wait for **its own** reset when saturated
        — never swap to another slot (D6/AC4). Returns ``(done, result)``."""
        target = self.use
        if active != target:
            self._switch_to(target)  # non-fatal; the snapshot's slot is the source of truth
        u = snap.get(target)
        if u is None:
            msg = f"slot #{target} not in snapshot — proceeding without quota check"
            self.announce(msg)
            return True, (True, msg)
        if u.pct_5h < gate:
            msg = f"quota ok (#{target}: 5h {u.pct_5h:.0f}% / 7d {u.pct_7d:.0f}%) — pinned"
            self.announce(msg)
            return True, (True, msg)
        wait_min = max(u.minutes_to_5h_reset, 1)
        self.announce(
            f"#{target} saturated (5h {u.pct_5h:.0f}%); pinned — waiting ~{wait_min}m "
            f"for reset at {u.clock_5h_reset or '?'}"
        )
        self._interruptible_sleep(wait_min * 60)
        return False, None

    def _gate_rotate(
        self, snap: dict[int, AccountUsage], active: int, gate: float
    ) -> tuple[bool, tuple[bool, str] | None]:
        """Stay on the current account while below the gate; else switch to the lowest-7d
        below-threshold slot; else wait for the soonest reset (D2/AC2). Returns
        ``(done, result)``."""
        summary = ", ".join(
            f"#{u.slot}: 5h {u.pct_5h:.0f}% / 7d {u.pct_7d:.0f}%"
            for u in sorted(snap.values(), key=lambda x: x.slot)
        )
        below = [u for u in snap.values() if u.pct_5h < gate]
        if below:
            if active in {u.slot for u in below}:
                msg = f"quota ok ({summary}) — staying on #{active}"
                self.announce(msg)
                return True, (True, msg)
            target = min(below, key=lambda u: u.pct_7d)
            self.announce(f"quota ({summary}) — switching to #{target.slot} (lower 7d)")
            self._switch_to(target.slot)
            return True, (True, f"switched to #{target.slot} (lower 7d)")

        soonest = min(snap.values(), key=lambda u: u.minutes_to_5h_reset or 10**9)
        wait_min = max(soonest.minutes_to_5h_reset, 1)
        self.announce(
            f"all saturated ({summary}); waiting for #{soonest.slot} to reset at "
            f"{soonest.clock_5h_reset or '?'} (~{wait_min}m)"
        )
        self._interruptible_sleep(wait_min * 60)
        return False, None

    def _switch_to(self, account: int) -> tuple[bool, str]:
        """Activate account ``account`` via ``cswap --switch-to``. Non-fatal."""
        try:
            proc = self._run(
                [self.cswap, "--switch-to", str(account)],
                capture_output=True,
                text=True,
                timeout=self._TIMEOUT,
            )
        except (subprocess.SubprocessError, OSError):
            return False, f"cswap --switch-to {account} unavailable — proceeding"
        if proc.returncode != 0:
            return False, f"cswap --switch-to {account} failed — proceeding"
        return True, f"switched to cswap account {account}"

    def claude_argv(self) -> list[str]:
        # cswap 0.11 is a switcher: it has already mutated the active account in
        # precheck(), so the launch is always plain ``claude`` — never a wrapped command.
        return ["claude"]


class SingleAccountProvider:
    """Plain ``claude`` with no quota machinery (used by tests and minimal setups)."""

    def precheck(self) -> tuple[bool, str]:
        return True, "single-account — no quota check"

    def claude_argv(self) -> list[str]:
        return ["claude"]
