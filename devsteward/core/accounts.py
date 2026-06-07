"""Account / quota provider — claude-swap (``cswap``) two-account, with degradation.

The quota machinery is generalized from ``run_batch_conversion.py`` / ``run_batch.py``,
but **claude-swap 0.11 is a switcher, not a command wrapper**. It mutates the active
account in ``~/.claude.json`` via flags (``--switch-to N``, ``--status``, ``--list``);
afterwards you invoke plain ``claude``. There is no ``exec`` subcommand and no ``status``
positional, so the engine never wraps ``claude`` — it switches the account in
:meth:`precheck` and then launches ``claude`` directly.

When ``cswap`` is absent the provider degrades to a single-account invocation and logs
"proceeding without quota check". Every cswap interaction is non-fatal: a failed switch,
a non-zero ``--status``, a timeout, or a missing binary degrades to "proceed" — quota
machinery never hard-fails a run.
"""

from __future__ import annotations

import shutil
import subprocess


class CswapAccountProvider:
    """Switch the active account via ``cswap`` when present; otherwise single-account.

    ``use`` pins a specific account index: :meth:`precheck` activates it with
    ``cswap --switch-to <use>`` before the run. The status gate is ``cswap --status``.
    Both are adaptive and non-fatal — they observe quota state but never block.
    """

    _TIMEOUT = 30

    def __init__(self, use: int | None = None):
        self.use = use
        self.cswap = shutil.which("cswap")

    @property
    def available(self) -> bool:
        return self.cswap is not None

    def precheck(self) -> tuple[bool, str]:
        if not self.available:
            return True, "cswap absent — proceeding without quota check"
        # Pin-by-index: switch the active account first. A failed switch degrades to
        # "proceed" (run on whatever account is currently active) rather than blocking.
        if self.use is not None:
            ok, reason = self._switch_to(self.use)
            if not ok:
                return True, reason
        # Status gate. A non-zero exit, timeout, or OS error degrades to "proceed".
        try:
            proc = subprocess.run(
                [self.cswap, "--status"],
                capture_output=True,
                text=True,
                timeout=self._TIMEOUT,
            )
        except (subprocess.TimeoutExpired, OSError):
            return True, "cswap --status unavailable — proceeding"
        if proc.returncode != 0:
            return True, "cswap --status non-zero — proceeding"
        return True, "cswap account active"

    def _switch_to(self, account: int) -> tuple[bool, str]:
        """Activate account ``account`` via ``cswap --switch-to``. Non-fatal."""
        try:
            proc = subprocess.run(
                [self.cswap, "--switch-to", str(account)],
                capture_output=True,
                text=True,
                timeout=self._TIMEOUT,
            )
        except (subprocess.TimeoutExpired, OSError):
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
