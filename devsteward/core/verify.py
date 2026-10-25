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

# A leading bare ``pytest`` token (REQ-068 Decision 4 — "one flavor"). Run via the console
# script, ``pytest`` shells with no repo root on ``sys.path``, so a ``from tests.<helper>``
# import that resolves fine under ``python -m pytest`` explodes. The engine normalizes a
# leading ``pytest …`` to ``<resolved interpreter> -m pytest …`` so the lane *and* the flavor
# never depend on how a human happened to type the string. (A non-leading ``pytest`` argument,
# or a non-pytest command, is untouched.)
_PYTEST_PREFIX = re.compile(r"^(\s*)pytest(\s|$)")


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
    """Rebind a leading ``python``/``python3``/``pytest`` to a pytest-capable interpreter."""
    if not (_PY_PREFIX.match(cmd) or _PYTEST_PREFIX.match(cmd)):
        return cmd
    interpreter = _pick_interpreter(cwd)
    return _rebind_interpreter(cmd, interpreter)


def _rebind_interpreter(cmd: str, interpreter: str) -> str:
    """Normalize a leading interpreter token to an explicit pytest-capable interpreter.

    A leading ``python``/``python3`` is rebound to ``interpreter``; a leading bare ``pytest``
    is normalized to ``interpreter -m pytest`` (REQ-068 Decision 4 — one flavor, repo root
    importable). Anything else is returned unchanged.
    """
    if _PY_PREFIX.match(cmd):
        return _PY_PREFIX.sub(
            lambda m: f"{m.group(1)}{shlex.quote(interpreter)}{m.group(3)}", cmd, count=1
        )
    if _PYTEST_PREFIX.match(cmd):
        return _PYTEST_PREFIX.sub(
            lambda m: f"{m.group(1)}{shlex.quote(interpreter)} -m pytest{m.group(2)}",
            cmd,
            count=1,
        )
    return cmd


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


def _pytest_targets(cmd: str) -> list[str]:
    """The genuine test node-ids/paths of a pytest command — never a bare word or marker value.

    Used to derive the project-wide ``artifact``/``manual`` node-id set the develop full-suite
    run deselects (REQ-068 Decision 2 / REQ-070). The deselect list is fed to ``--deselect``, so
    every token here must be a *collectible* target; a non-node-id (a bare word, a directory, a
    ``-m`` marker value, prose) deselected by id is at best a no-op and at worst catastrophic —
    ``pytest --deselect tests`` deselects the whole ``tests/`` tree and empties the suite.

    Two disciplines keep the set pure (REQ-070):

    * A ``manual:`` acceptance criterion is **human prose**, not a command — it carries no
      collectible node-id and contributes nothing, even when the prose mentions ``pytest`` (e.g.
      "run ``python -m pytest -m not live`` and confirm a ``0 skipped`` summary"). That prose
      must never be tokenized into deselect targets.
    * Only a token that *looks like* a pytest target is kept: it ends in ``.py`` (a test file) or
      contains ``.py::`` (a node-id ``file.py::test`` / ``file.py::Cls::test``). The interpreter,
      the ``pytest`` module/executable, any flag, a ``-m`` marker value, and any bare prose word
      are all dropped.
    """
    if cmd.strip().lower().startswith("manual:"):
        return []  # a human-oracle AC — prose, no collectible node-id (REQ-070)
    if not _is_pytest_command(cmd):
        return []
    try:
        toks = shlex.split(cmd)
    except ValueError:
        toks = cmd.split()
    # A real target is a test file or a node-id rooted in one — never a bare word, dir, or
    # marker value. This is what makes the ``manual contributes nothing`` promise actual and
    # stops a stray ``tests`` / ``not live`` token from reaching ``--deselect`` (REQ-070).
    return [t for t in toks if t.endswith(".py") or ".py::" in t]


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


def _subprocess_env(env: dict[str, str] | None) -> dict[str, str] | None:
    """The child environment for a grading subprocess: the engine's own environment with
    ``env`` overlaid (REQ-075 AC3). The overlay **wins** over any inherited value, so an
    injected ``DEVSTEWARD_EVIDENCE_DIR`` overrides a stale one left by a prior capture's
    ``export``. ``None`` (the default) means "inherit unchanged" — subprocess sees
    ``os.environ`` and nothing is allocated."""
    if not env:
        return None
    return {**os.environ, **env}


def _pytest_outcome(
    cmd: str, cwd: str | None, timeout: float, env: dict[str, str] | None = None
) -> Outcome:
    """Run a pytest command with an injected ``--junitxml`` and parse per-test counts.

    Exit code 0 cannot tell a pass from a skip (both exit 0) or a zero-collection from a
    real pass; the built-in JUnit XML can. No plugin/dependency is added — ``--junitxml``
    and ``junit_family=xunit2`` ship with pytest. ``env`` overlays the child environment
    (REQ-075 AC3: the engine hands the grading test its evidence dir).
    """
    fd, xml_path = tempfile.mkstemp(suffix=".xml", prefix="devsteward-junit-")
    os.close(fd)
    try:
        full = f"{cmd} --junitxml={shlex.quote(xml_path)} -o junit_family=xunit2"
        try:
            proc = subprocess.run(
                full, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                env=_subprocess_env(env),
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
