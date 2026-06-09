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

import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from .model import Step

# A leading ``python``/``python3`` token in an acceptance command. REQ authors write
# ``python -m pytest …``, but the engine's runtime env may have no bare ``python`` on PATH
# (only ``python3``, with pytest living in a venv). We rebind that token to an interpreter
# that can actually run the tests — turning an env-shape mismatch (exit 127, ``python: not
# found``; or ``No module named pytest``) back into a real result.
_PY_PREFIX = re.compile(r"^(\s*)(python3?)(\s)")


def _venv_interpreters(cwd: str | None):
    """Yield project-local venv interpreters under ``cwd``, most-conventional first."""
    if not cwd:
        return
    root = Path(cwd)
    for name in (".venv", "venv"):
        for sub in ("bin/python", "Scripts/python.exe"):
            candidate = root / name / sub
            if candidate.exists():
                yield str(candidate)


def _has_pytest(interpreter: str) -> bool:
    try:
        return (
            subprocess.run(
                [interpreter, "-c", "import pytest"], capture_output=True, timeout=60
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def _pick_interpreter(cwd: str | None) -> str:
    """The interpreter the acceptance tests should run under.

    Steward may be installed in a pipx venv whose interpreter (``sys.executable``) lacks
    pytest, while the project's own ``.venv`` has it — or vice versa. Prefer the project
    venv, fall back to ``sys.executable``, choosing the first that can import pytest so the
    tests run for real instead of failing on an env-shape mismatch.
    """
    candidates = [*_venv_interpreters(cwd), sys.executable]
    for interpreter in candidates:
        if _has_pytest(interpreter):
            return interpreter
    return sys.executable


def _resolve_interpreter(cmd: str, cwd: str | None = None) -> str:
    """Rebind a leading bare ``python``/``python3`` to a pytest-capable interpreter."""
    if not _PY_PREFIX.match(cmd):
        return cmd
    interpreter = _pick_interpreter(cwd)
    return _rebind_python(cmd, interpreter)


def _rebind_python(cmd: str, interpreter: str) -> str:
    """Rebind a leading bare ``python``/``python3`` token to an explicit interpreter."""
    if not _PY_PREFIX.match(cmd):
        return cmd
    return _PY_PREFIX.sub(
        lambda m: f"{m.group(1)}{shlex.quote(interpreter)}{m.group(3)}", cmd, count=1
    )


class NoUsableEnvError(RuntimeError):
    """No interpreter that can import pytest was found among the candidates.

    REQ-028 Decision 4: a configured-but-unusable environment (or a discovery that turns
    up nothing pytest-capable) is a **hard, surfaced** error — never a silent skip-ahead
    that lets the test command die with ``127``/``No module named pytest`` and read as
    "not yet verified". A ``done`` must never be reachable *because* the suite couldn't run.
    """


def resolve_test_interpreter(cwd: str | None = None, configured: str | None = None) -> str:
    """The interpreter the land gate runs its tests under, or a hard error.

    ``configured`` (``verify.python`` in project config) is authoritative: if set but it
    cannot import pytest, that is a :class:`NoUsableEnvError`, not a fall-through — an
    explicit choice that doesn't work must surface, not be quietly replaced. With no
    configured interpreter, discovery prefers the project venv, then ``sys.executable``,
    taking the first that can import pytest; if none can, that too is a hard error.
    """
    if configured:
        interp = configured
        if not os.path.isabs(interp):
            interp = str(Path(cwd or ".") / interp)
        if _has_pytest(interp):
            return interp
        raise NoUsableEnvError(
            f"configured test interpreter cannot import pytest: {configured}"
        )
    candidates = [*_venv_interpreters(cwd), sys.executable]
    for interp in candidates:
        if _has_pytest(interp):
            return interp
    raise NoUsableEnvError(
        "no interpreter can import pytest among: " + ", ".join(candidates)
    )


def _is_pytest_command(cmd: str) -> bool:
    """True if ``cmd`` invokes pytest (``python -m pytest …`` or a ``pytest`` executable).

    Only pytest commands carry machine-readable per-test outcomes (via JUnit XML); a
    non-pytest acceptance command falls back to exit-code semantics.
    """
    try:
        toks = shlex.split(cmd)
    except ValueError:
        toks = cmd.split()
    return any(
        t == "pytest" or t.endswith("/pytest") or t.endswith("\\pytest") or t.endswith("pytest.exe")
        for t in toks
    )


@dataclass(frozen=True)
class Outcome:
    """Per-test counts parsed from a pytest run's JUnit XML.

    ``parsed`` records whether the XML was produced and read; an unparsed run that exited
    non-zero (usage/collection error) reports ``collected == 0``.
    """

    collected: int
    passed: int
    skipped: int
    failed: int
    errors: int
    returncode: int
    tail: str
    parsed: bool


def _pytest_outcome(cmd: str, cwd: str | None, timeout: float) -> Outcome:
    """Run a pytest command with an injected ``--junitxml`` and parse per-test counts.

    Exit code 0 cannot tell a pass from a skip (both exit 0) or a zero-collection from a
    real pass; the built-in JUnit XML can. No plugin/dependency is added — ``--junitxml``
    and ``junit_family=xunit2`` ship with pytest.
    """
    fd, xml_path = tempfile.mkstemp(suffix=".xml", prefix="devsteward-junit-")
    os.close(fd)
    try:
        full = f"{cmd} --junitxml={shlex.quote(xml_path)} -o junit_family=xunit2"
        try:
            proc = subprocess.run(
                full, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return Outcome(0, 0, 0, 0, 0, 124, f"timeout: {cmd}", parsed=False)
        tail = "\n    ".join((proc.stdout + proc.stderr).strip().splitlines()[-3:])
        collected = passed = skipped = failed = errors = 0
        parsed = False
        if os.path.exists(xml_path) and os.path.getsize(xml_path) > 0:
            try:
                root = ET.parse(xml_path).getroot()
            except ET.ParseError:
                root = None
            if root is not None:
                for suite in root.iter("testsuite"):
                    collected += int(suite.get("tests", 0) or 0)
                    failed += int(suite.get("failures", 0) or 0)
                    errors += int(suite.get("errors", 0) or 0)
                    skipped += int(suite.get("skipped", 0) or 0)
                    parsed = True
                passed = max(collected - failed - errors - skipped, 0)
        return Outcome(collected, passed, skipped, failed, errors, proc.returncode, tail, parsed)
    finally:
        try:
            os.unlink(xml_path)
        except OSError:
            pass


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
                    _resolve_interpreter(cmd, self.cwd),
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
