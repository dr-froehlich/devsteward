"""REQ-015 + REQ-028 + REQ-029 — the REQ profile's verifier: give the gate real teeth.

The generic :class:`~devsteward.core.verify.CommandVerifier` marker-trusts any step that
declares no tests. For the REQ workflow that is exactly the false-done hole: a delivering
step that carried no per-phase tests auto-passed, and a REQ that declared no acceptance
tests at all reached ``done`` without the engine ever running anything (an empty no-op once
landed this way).

After REQ-029 the REQ profile has one step per REQ — ``develop`` — and it is the delivering
gate: it carries the acceptance ``test:`` commands and the engine lands the REQ mechanically
only when it runs green. REQ-015 made *exit-0 ⇒ green*; REQ-028 sharpens what "green" means,
because exit-0 lies in four ways:

* **a skip exits 0** — a ``pytest.skip`` lands as a pass, so a "prove X" test that declines
  to run is indistinguishable from one that proved X. A named test that **skips** now fails
  the gate (skip ≠ green); skip stays legal in the *full suite*, just not load-bearing.
* **a typo'd / renamed / unowned test id collects nothing** — an empty selection read as
  green. A named test that **collects zero tests** now fails the gate.
* **the per-AC gate never runs the rest of the suite** — a known-broken behaviour could
  ship green. At land the engine now also runs the **full project suite** and requires it
  clean (suite skips stay legal).
* **the verifier shelled into a context without the venv** — ``127 pytest: not found`` read
  as "not yet verified". The land gate resolves the **project's configured environment**
  first; an unusable one is a hard, surfaced error (see :class:`NoUsableEnvError`).

Any non-``develop`` step (a generic or phase-less step) still passes on marker-trust
(REQ-015 Decision 2) — the sharpened semantics gate the delivering ``develop`` step.
"""

from __future__ import annotations

import subprocess

from ...core.model import Step
from ...core.verify import (
    CommandVerifier,
    NoUsableEnvError,
    _is_pytest_command,
    _pytest_outcome,
    _rebind_python,
    resolve_test_interpreter,
)


class ReqVerifier:
    """The develop gate: a REQ's named behaviour must observably run and pass.

    ``full_suite`` is the command for the project's whole test suite (AC3); ``None`` (the
    bare-constructor default) disables that gate so unit checks can isolate the named-test
    semantics — :func:`devsteward.build.build_verifier` threads the configured default
    (``python -m pytest``) for real runs. ``python`` is the optional configured interpreter
    (``verify.python``) the gate resolves the suite under (AC4).
    """

    def __init__(
        self,
        cwd: str | None = None,
        timeout: float = 1800.0,
        full_suite: str | None = None,
        python: str | None = None,
    ):
        self.cwd = cwd
        self.timeout = timeout
        self.full_suite = full_suite
        self.python = python
        self._inner = CommandVerifier(cwd=cwd, timeout=timeout)

    def verify(self, step: Step) -> tuple[bool, str]:
        # Non-delivering steps (none in the REQ profile after REQ-029, but a generic/phase-
        # less step may reach here) → marker-trust via the inner verifier; the guarantee is
        # enforced on the delivering ``develop`` gate.
        if step.phase != "develop":
            return self._inner.verify(step)

        if not step.verify:
            return (
                False,
                "develop step has no acceptance tests — a REQ cannot land on marker-trust; "
                "declare at least one runnable acceptance criterion the engine re-runs",
            )

        # AC4 — resolve the project's configured test environment before running anything;
        # an unusable env is a hard, surfaced error, never a silent pass-ahead to a 127.
        try:
            interpreter = resolve_test_interpreter(self.cwd, self.python)
        except NoUsableEnvError as exc:
            return False, f"no usable test environment: {exc}"

        details: list[str] = []
        for cmd in step.verify:
            ok, detail = self._gate_named(cmd, interpreter)
            details.append(detail)
            if not ok:
                return False, "\n".join(details)

        # AC3 — every named AC test passed; the rest of the suite must also be clean.
        ok, detail = self._gate_full_suite(interpreter)
        if detail:
            details.append(detail)
        if not ok:
            return False, "\n".join(details)
        return True, "\n".join(details)

    def _gate_named(self, cmd: str, interpreter: str) -> tuple[bool, str]:
        """A named acceptance test passes only if it collected and every test *passed*.

        AC1: a skip fails. AC2: zero collected fails. A non-pytest command (no per-test
        signal) falls back to exit-code semantics.
        """
        resolved = _rebind_python(cmd, interpreter)
        if not _is_pytest_command(resolved):
            return self._exit_code(cmd, resolved)
        o = _pytest_outcome(resolved, self.cwd, self.timeout)
        head = f"[{o.returncode}] {cmd}"
        if o.collected == 0:
            return (
                False,
                f"{head}\n    collected 0 tests — non-existent, renamed, or unowned "
                f"test id\n    {o.tail}",
            )
        if o.skipped:
            return (
                False,
                f"{head}\n    {o.skipped} skipped of {o.collected} — a skip cannot satisfy "
                f"a land gate (skip ≠ green)\n    {o.tail}",
            )
        if o.failed or o.errors:
            return (
                False,
                f"{head}\n    {o.failed} failed, {o.errors} errors of {o.collected}"
                f"\n    {o.tail}",
            )
        return True, f"{head}\n    {o.passed} passed"

    def _gate_full_suite(self, interpreter: str) -> tuple[bool, str]:
        """Run the whole project suite; any failure/error fails the land (skips stay legal)."""
        if not self.full_suite:
            return True, ""
        resolved = _rebind_python(self.full_suite, interpreter)
        try:
            proc = subprocess.run(
                resolved,
                shell=True,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"timeout: full suite ({self.full_suite})"
        if proc.returncode != 0:
            tail = "\n    ".join((proc.stdout + proc.stderr).strip().splitlines()[-3:])
            return (
                False,
                f"[{proc.returncode}] full suite ({self.full_suite}) — suite not clean"
                f"\n    {tail}",
            )
        return True, f"[0] full suite clean ({self.full_suite})"

    def _exit_code(self, cmd: str, resolved: str) -> tuple[bool, str]:
        """Exit-code fallback for a non-pytest named command (no per-test outcomes)."""
        try:
            proc = subprocess.run(
                resolved,
                shell=True,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"timeout: {cmd}"
        tail = "\n    ".join((proc.stdout + proc.stderr).strip().splitlines()[-3:])
        detail = (
            f"[{proc.returncode}] {cmd} "
            f"(not a pytest command — per-test outcomes unavailable)\n    {tail}"
        )
        return proc.returncode == 0, detail
