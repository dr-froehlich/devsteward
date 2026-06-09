"""REQ-028 AC4 — the land gate runs tests in the project's configured environment.

Both FlowSteward REQs first failed land with ``[127] pytest: not found`` — the verifier
shelled into a context without the project venv, and a missing interpreter masqueraded as
"not yet verified". The gate now resolves a pytest-capable interpreter *before* running
(project venv, then the engine's own, or an explicit ``verify.python``); a configured-but-
unusable environment is a hard, surfaced error, never a silent pass-ahead to a 127.
"""

from __future__ import annotations

import pytest

import devsteward.core.verify as verify
from devsteward.core.model import Step
from devsteward.core.verify import NoUsableEnvError, resolve_test_interpreter
from devsteward.profiles.req.verify import ReqVerifier


def test_verifier_uses_project_env_no_127(tmp_path, monkeypatch):
    # (a) a project venv that can import pytest is resolved and used, so the command never
    #     shells into a bare `python` that isn't there (the 127 miss).
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.touch()
    monkeypatch.setattr(verify, "_has_pytest", lambda interp: interp == str(venv_python))
    assert resolve_test_interpreter(str(tmp_path)) == str(venv_python)

    # (b) a configured-but-unusable interpreter is a hard error, not a fall-through.
    monkeypatch.setattr(verify, "_has_pytest", lambda interp: False)
    with pytest.raises(NoUsableEnvError):
        resolve_test_interpreter(str(tmp_path), configured="/no/such/python")

    # and the land gate surfaces it as a verify failure distinct from a test failure —
    # so a `done` can never be reachable *because* the suite couldn't be run.
    v = ReqVerifier(cwd=str(tmp_path), python="/no/such/python", full_suite=None)
    ok, reason = v.verify(
        Step(
            id="REQ-X:land",
            command="/advance",
            phase="land",
            verify=("python -m pytest tests/test_x.py::test_y",),
        )
    )
    assert ok is False
    assert "environment" in reason.lower()
    # not the wording of a test outcome (no failed/skipped count) — an env error, surfaced
    assert "failed" not in reason and "skipped" not in reason
