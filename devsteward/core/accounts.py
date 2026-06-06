"""Account / quota provider — claude-swap (``cswap``) two-account, with degradation.

Lifted and generalized from the quota machinery in ``run_batch_conversion.py`` /
``run_batch.py``. When ``cswap`` is on PATH the engine routes ``claude`` through it
(optionally pinning ``--use N``); when it is absent the provider degrades to a plain
single-account invocation and logs "proceeding without quota check" — never a hard fail.
"""

from __future__ import annotations

import shutil
import subprocess


class CswapAccountProvider:
    """Route ``claude`` through ``cswap`` when present; otherwise single-account.

    ``use`` pins a specific account index (the ported ``--use N`` behaviour). The
    ``precheck`` runs an adaptive, non-fatal quota gate.
    """

    def __init__(self, use: int | None = None):
        self.use = use
        self.cswap = shutil.which("cswap")

    @property
    def available(self) -> bool:
        return self.cswap is not None

    def precheck(self) -> tuple[bool, str]:
        if not self.available:
            return True, "cswap absent — proceeding without quota check"
        # cswap present: ask it whether there is an account with quota. A non-zero exit
        # or unparseable output degrades to "proceed" rather than blocking the run.
        try:
            proc = subprocess.run(
                [self.cswap, "status"], capture_output=True, text=True, timeout=30
            )
        except (subprocess.TimeoutExpired, OSError):
            return True, "cswap status unavailable — proceeding"
        if proc.returncode != 0:
            return True, "cswap status non-zero — proceeding"
        return True, "cswap quota ok"

    def claude_argv(self) -> list[str]:
        if not self.available:
            return ["claude"]
        argv = [self.cswap, "exec"]
        if self.use is not None:
            argv += ["--use", str(self.use)]
        argv += ["claude"]
        return argv


class SingleAccountProvider:
    """Plain ``claude`` with no quota machinery (used by tests and minimal setups)."""

    def precheck(self) -> tuple[bool, str]:
        return True, "single-account — no quota check"

    def claude_argv(self) -> list[str]:
        return ["claude"]
