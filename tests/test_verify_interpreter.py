"""The land verifier runs acceptance commands under the engine's own interpreter.

REQ authors write acceptance tests as ``python -m pytest …``. A reality-boundary defect:
the engine's runtime env may have no bare ``python`` on PATH (only ``python3``, with pytest
in a venv), so the command died with exit 127 ``python: not found`` and a *correctly
implemented* REQ was marked land-failed (this is what happened to REQ-020). The verifier
now rebinds a leading ``python``/``python3`` token to ``sys.executable`` so the tests run
under the same interpreter that runs steward.
"""

from __future__ import annotations

import sys

from devsteward.core.model import Step
from devsteward.core.verify import CommandVerifier, _resolve_interpreter


def test_resolve_rebinds_leading_python():
    assert _resolve_interpreter("python -m pytest x::y").startswith(sys.executable)
    assert _resolve_interpreter("python3 -m pytest x").startswith(sys.executable)
    assert _resolve_interpreter("  python -m pytest").strip().startswith(sys.executable)


def test_resolve_leaves_other_commands_untouched():
    assert _resolve_interpreter("pytest x::y") == "pytest x::y"
    assert _resolve_interpreter("true") == "true"
    # only the leading token is rebound, not a later 'python' argument
    assert _resolve_interpreter("env python3 -V") == "env python3 -V"


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
