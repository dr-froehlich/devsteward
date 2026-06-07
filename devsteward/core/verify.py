"""The verifier seam — owned by the engine, not by skills.

A step with named acceptance tests is only marked ``DONE`` when they run green. This is the
guarantee that keeps unattended automation honest: a model that *claims* success can't
advance the ledger past a red test.

The default :class:`CommandVerifier` runs each ``verify`` entry as a shell command (the
acceptance ``test:`` strings, e.g. ``pytest path::name``) and requires exit code 0. A step
that declares **no** tests marker-trusts (returns green) — fine for intermediate steps that
only advance the cursor, but a profile must not let the step that *delivers* the work pass
on trust. The REQ profile enforces exactly that in :class:`devsteward.profiles.req.verify.ReqVerifier`,
which refuses a ``land`` step with no tests. ``MarkerVerifier`` is the always-green fallback
for steps where no test could exist.
"""

from __future__ import annotations

import subprocess

from .model import Step


class CommandVerifier:
    """Run each of a step's ``verify`` commands; all must exit 0."""

    def __init__(self, cwd: str | None = None, timeout: float = 1800.0):
        self.cwd = cwd
        self.timeout = timeout

    def verify(self, step: Step) -> tuple[bool, str]:
        if not step.verify:
            # No acceptance tests declared: documented fallback is marker-trust.
            return True, "no acceptance tests declared (marker trust)"
        details: list[str] = []
        for cmd in step.verify:
            try:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=self.cwd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired:
                return False, f"timeout: {cmd}"
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
            details.append(f"[{proc.returncode}] {cmd}\n    " + "\n    ".join(tail))
            if proc.returncode != 0:
                return False, "\n".join(details)
        return True, "\n".join(details)


class MarkerVerifier:
    """Always-green fallback: trust that the step ran. Use only where no test exists."""

    def verify(self, step: Step) -> tuple[bool, str]:
        return True, "marker trust (no verification)"
