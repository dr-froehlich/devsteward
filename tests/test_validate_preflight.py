"""REQ-065 §1 — the validate land gate is pre-flighted.

The ``CompositeLandGate`` (concept-artifact + plan-artifact) used to run only inside
``mechanical_land``, which fires *after* the System-Test session and its human sign-offs —
so a formality red (a concept doc at the wrong path, a missing plan) wasted a whole paid
session and every oracle it collected. REQ-065 moves the check into the validate entry
points (``start`` / ``__call__``): a refusal returns ``REFUSED`` **before** the step is set
``RUNNING`` or any session is spawned, leaving the ledger and tree untouched.

Wired like ``test_guided_validation.py`` but with the real ``CompositeLandGate`` so the
*concept* arm is exercised.
"""

from __future__ import annotations

from pathlib import Path

from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome, StepResult
from devsteward.core.model import StepStatus
from devsteward.profiles.req import ReqStepSource
from devsteward.profiles.req.checkpoint import (
    CompositeLandGate,
    ConceptArtifactGate,
    PlanArtifactGate,
    ReqDoneFlipper,
)
from devsteward.profiles.req.validate import ReqValidateRoutine
from devsteward.profiles.req.verify import ReqVerifier

from conftest import FakeGitTopology
from test_system_test_phase import (
    SystemTesterRunner,
    _events,
    _project,
    _REGRESSION,
    _ARTIFACT_OK,
    _MANUAL,
)


def _executor(root, *, runner):
    """Like ``test_system_test_phase._executor`` but with the *composite* land gate (plan +
    concept), so a concept-gate refusal is what fires."""
    req_dir = root / "docs" / "requirements"
    return Executor(
        root=root,
        source=ReqStepSource(req_dir),
        verifier=ReqVerifier(cwd=str(root), full_suite=None),
        accounts=SingleAccountProvider(),
        runner=runner,
        git=FakeGitTopology(current="dev"),
        on_verified=ReqDoneFlipper(req_dir, req_dir / "REQUIREMENTS_INDEX.md"),
        land_gate=CompositeLandGate(
            PlanArtifactGate(root / "docs" / "plans"),
            ConceptArtifactGate(root / "docs" / "concepts", req_dir),
        ),
        repair_budget=0,
        step_claude={"develop": ("claude-opus-4-8", "high"),
                     "repair": ("claude-sonnet-4-6", "high"),
                     "validate": ("claude-opus-4-8", "high")},
        validate_runner=ReqValidateRoutine(req_dir),
    )


def _started(root, step_id: str) -> bool:
    return any(
        e.get("event") == "step_started" and e.get("step") == step_id
        for e in _events(root)
    )


def test_start_fires_concept_gate_before_running(tmp_path):
    """``start()`` runs the composite gate first: a REQ that declared a concept phase with no
    ``docs/concepts/REQ-NNN.md`` doc is refused (``REFUSED``) before the step goes ``RUNNING``,
    before any ``step_started`` is logged, and before the System Tester session is spawned."""
    _project(tmp_path, [_REGRESSION, _ARTIFACT_OK, _MANUAL], process={"concept": "true"})
    runner = SystemTesterRunner(tmp_path)
    ex = _executor(tmp_path, runner=runner)
    step = ex.step_by_id("REQ-001:validate")

    res = ex.validate_runner.start(ex, step)

    assert isinstance(res, StepResult)
    assert res.outcome is RunOutcome.REFUSED
    assert "REQ-001.md" in res.detail and "concept" in res.detail
    # ledger + tree untouched, no session spawned
    assert ex.ledger.status_of("REQ-001:validate") is StepStatus.PENDING
    assert not _started(tmp_path, "REQ-001:validate")
    assert not any("/system-test" in c["command"] for c in runner.calls)


def test_batch_call_fires_gate_before_running(tmp_path):
    """The batch entry point (``__call__``) pre-flights the same gate: same ``REFUSED`` with
    no ``RUNNING``, no ``step_started``, no spawned session."""
    _project(tmp_path, [_REGRESSION, _ARTIFACT_OK, _MANUAL], process={"concept": "true"})
    runner = SystemTesterRunner(tmp_path)
    ex = _executor(tmp_path, runner=runner)
    step = ex.step_by_id("REQ-001:validate")

    res = ex.validate_runner(ex, step, unattended=True)

    assert res.outcome is RunOutcome.REFUSED
    assert "concept" in res.detail
    assert ex.ledger.status_of("REQ-001:validate") is StepStatus.PENDING
    assert not _started(tmp_path, "REQ-001:validate")
    assert not any("/system-test" in c["command"] for c in runner.calls)


def test_gate_clear_lets_start_proceed(tmp_path):
    """When the gate is clear (plan present, no concept phase) the pre-flight is a no-op:
    ``start()`` returns a context, sets ``RUNNING`` and logs ``step_started`` as before."""
    _project(tmp_path, [_REGRESSION, _ARTIFACT_OK, _MANUAL])  # plan written by _project
    runner = SystemTesterRunner(tmp_path)
    ex = _executor(tmp_path, runner=runner)
    step = ex.step_by_id("REQ-001:validate")

    ctx = ex.validate_runner.start(ex, step)

    assert not isinstance(ctx, StepResult)  # a StartContext — proceeded
    assert ctx.evidence_dir.is_dir()
    assert ex.ledger.status_of("REQ-001:validate") is StepStatus.RUNNING
    assert _started(tmp_path, "REQ-001:validate")
