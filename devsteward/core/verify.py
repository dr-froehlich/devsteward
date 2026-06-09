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

import re
import shlex
import subprocess
import sys

from .model import Step

# A leading ``python``/``python3`` token in an acceptance command. REQ authors write
# ``python -m pytest …``, but the engine's runtime env may have no bare ``python`` on PATH
# (only ``python3``, with pytest living in a venv). We rebind that token to the interpreter
# running steward so the tests run under the same environment the engine installs into —
# turning an env-shape mismatch (exit 127, ``python: not found``) back into a real result.
_PY_PREFIX = re.compile(r"^(\s*)(python3?)(\s)")


def _resolve_interpreter(cmd: str) -> str:
    """Rebind a leading bare ``python``/``python3`` to ``sys.executable``."""
    return _PY_PREFIX.sub(
        lambda m: f"{m.group(1)}{shlex.quote(sys.executable)}{m.group(3)}", cmd, count=1
    )


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
                    _resolve_interpreter(cmd),
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
