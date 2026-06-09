"""The land verifier runs acceptance commands under a pytest-capable interpreter.

REQ authors write acceptance tests as ``python -m pytest …``. Two reality-boundary defects:
(1) the engine's runtime env may have no bare ``python`` on PATH (only ``python3``), so the
command died with exit 127 ``python: not found`` (this is what happened to REQ-020); (2) when
steward is installed in a pipx venv, ``sys.executable`` has no pytest, so the command died
with ``No module named pytest`` while the project's own ``.venv`` had it (REQ-025/026). The
verifier now rebinds a leading ``python``/``python3`` token to the first interpreter that can
import pytest, preferring the project's ``.venv`` over ``sys.executable``.
"""

from __future__ import annotations

import sys

from devsteward.core.model import Step
from devsteward.core.verify import (
    CommandVerifier,
    _pick_interpreter,
    _resolve_interpreter,
)


def test_resolve_rebinds_leading_python():
    # With no cwd the only candidate is sys.executable (which runs this test, so it has
    # pytest); the leading token is rebound to it.
    assert _resolve_interpreter("python -m pytest x::y").startswith(sys.executable)
    assert _resolve_interpreter("python3 -m pytest x").startswith(sys.executable)
    assert _resolve_interpreter("  python -m pytest").strip().startswith(sys.executable)


def test_resolve_leaves_other_commands_untouched():
    assert _resolve_interpreter("pytest x::y") == "pytest x::y"
    assert _resolve_interpreter("true") == "true"
    # only the leading token is rebound, not a later 'python' argument
    assert _resolve_interpreter("env python3 -V") == "env python3 -V"


def test_pick_prefers_project_venv_with_pytest(tmp_path, monkeypatch):
    """When sys.executable lacks pytest but the project ``.venv`` has it, pick the venv.

    Simulates the pipx-install shape: steward's own interpreter can't ``import pytest`` but
    the consumer project's ``.venv/bin/python`` can. The verifier must rebind to the venv so
    a correctly-implemented REQ lands instead of failing on ``No module named pytest``.
    """
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.touch()

    import devsteward.core.verify as verify

    monkeypatch.setattr(verify.sys, "executable", "/no/pytest/python")
    monkeypatch.setattr(
        verify, "_has_pytest", lambda interp: interp == str(venv_python)
    )
    assert _pick_interpreter(str(tmp_path)) == str(venv_python)
    assert _resolve_interpreter("python -m pytest x", str(tmp_path)).startswith(
        str(venv_python)
    )


def test_pick_falls_back_to_sys_executable_when_no_venv(monkeypatch):
    import devsteward.core.verify as verify

    monkeypatch.setattr(verify, "_has_pytest", lambda interp: True)
    assert _pick_interpreter(None) == sys.executable


def test_verify_runs_python_command_under_engine_interpreter():
    """A ``python -m …`` acceptance command passes even when bare ``python`` is absent,
    because the verifier runs it under sys.executable."""
    v = CommandVerifier()
    ok, detail = v.verify(
        Step(id="REQ-X:land", command="/advance", verify=("python -c \"import sys\"",), phase="land")
    )
    assert ok is True, detail
    # the reported detail keeps the author's original command for legibility
    assert "python -c" in detail
