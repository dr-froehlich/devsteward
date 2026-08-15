"""REQ-065 §2 — ``steward reland``: replay the land of a recorded green without re-running
the validation session.

When a validate step is left ``FAILED`` by a land-gate refusal (the missing concept doc /
plan the pre-flight now catches, or the historical post-session refusals already stuck in a
ledger), the session ran and its artifact gate + human sign-offs are durable in the green
``validation`` event. Once the formality is fixed, ``reland`` re-certifies that same green
and lands — no re-spawn, no re-prompt. It refuses, with a routing diagnostic, for any step
outside its narrow precondition shape (Decision 4).
"""

from __future__ import annotations

from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.profiles.req import ReqStepSource
from devsteward.profiles.req.checkpoint import (
    CompositeLandGate,
    ConceptArtifactGate,
    PlanArtifactGate,
    ReqDoneFlipper,
)
from devsteward.profiles.req.reqfile import parse_req
from devsteward.profiles.req.validate import ReqValidateRoutine
from devsteward.profiles.req.verify import ReqVerifier

from conftest import FakeGitTopology, write_index
from test_system_test_phase import (
    SystemTesterRunner,
    _events,
    _write_plan,
    _write_req,
    _REGRESSION,
    _ARTIFACT_OK,
    _MANUAL,
)


def _executor(root, *, runner=None):
    req_dir = root / "docs" / "requirements"
    return Executor(
        # REQ-091: a spawn names its model; an unconfigured headless spawn refuses.
        model="test-spawn-model",
        root=root,
        source=ReqStepSource(req_dir),
        verifier=ReqVerifier(cwd=str(root), full_suite=None),
        accounts=SingleAccountProvider(),
        runner=runner or SystemTesterRunner(root),
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


def _build(root, acs=(_REGRESSION, _ARTIFACT_OK, _MANUAL), *, plan=True, runner=None):
    req_dir = root / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", list(acs))
    write_index(req_dir, [("REQ-001", "REQ-001 title", "OPEN", "–")])
    if plan:
        _write_plan(root, "REQ-001")
    Ledger.init(root)
    return _executor(root, runner=runner)


def _green_then_refused(ex, req_id="REQ-001"):
    """Synthesize the FAILED-after-green shape: a green ``validation`` (artifact gate green +
    a recorded human sign-off) followed by the land-gate refusal that set the step FAILED —
    exactly what the old post-session gate produced (and what a stuck ledger still holds)."""
    led = ex.ledger
    validate = f"{req_id}:validate"
    led.append_event(
        "validation", step=validate, req=req_id, ok=True, driver="interactive",
        rerun=False, evidence=f".devsteward/evidence/{req_id}/20260623T000000Z",
        results=[
            {"ac": "AC2", "check": "artifact", "ok": True, "detail": "[0] true\n    1 passed"},
            {"ac": "AC3", "check": "manual", "ok": True,
             "detail": "sign-off by Petra — reviewed the proof run"},
        ],
        artifacts=[{"path": f".devsteward/evidence/{req_id}/20260623T000000Z/c.txt",
                    "sha256": "deadbeef"}],
        signoffs=[{"ac": "AC3", "approved": True, "reviewer": "Petra",
                   "scope": "reviewed the proof run", "date": "2026-06-23"}],
    )
    led.set_status(validate, StepStatus.FAILED)
    led.save()
    led.append_event(
        "land_refused", step=validate,
        detail=f"refusing to land {req_id} — no file in plans/ names {req_id}",
    )


# -- AC2 ------------------------------------------------------------------------


def test_reland_lands_recorded_green_without_session(tmp_path):
    """A FAILED validate whose last events are a green validation then a land_refused lands on
    ``reland`` once the formality is fixed: the REQ flips ``done``, the cursor advances to the
    validate step, the session is **not** re-run, and the recorded sign-off is carried into
    ``verified_by`` (no re-prompt)."""
    req_dir = tmp_path / "docs" / "requirements"
    runner = SystemTesterRunner(tmp_path)
    ex = _build(tmp_path, plan=False, runner=runner)   # no plan yet → the missing formality
    ex.advance_once(only="REQ-001")                    # develop → deferred commit (no gate)
    assert ex.ledger.status_of("REQ-001:develop") is StepStatus.DONE

    _green_then_refused(ex)                             # the old post-session refusal shape
    assert ex.ledger.status_of("REQ-001:validate") is StepStatus.FAILED

    _write_plan(tmp_path, "REQ-001")                    # the operator fixes the formality
    n_before = len(runner.calls)
    res = ex.validate_runner.reland(ex, "REQ-001")

    assert res.outcome is RunOutcome.DONE
    assert len(runner.calls) == n_before               # no validation session re-run
    assert parse_req(req_dir / "REQ-001.md").status == "done"
    assert ex.ledger.status_of("REQ-001:validate") is StepStatus.DONE
    assert ex.ledger.cursor_step == "REQ-001:validate"
    assert any(e["event"] == "reland" and e.get("req") == "REQ-001" for e in _events(tmp_path))
    assert "Petra" in (req_dir / "REQ-001.md").read_text()  # sign-off carried into verified_by


def test_reland_refuses_if_gate_still_red(tmp_path):
    """A final safety pre-flight: if the formality is *not* fixed, ``reland`` refuses and
    leaves the step FAILED (nothing lands)."""
    ex = _build(tmp_path, plan=False)                  # plan still missing
    ex.advance_once(only="REQ-001")
    _green_then_refused(ex)

    res = ex.validate_runner.reland(ex, "REQ-001")     # gate still refuses
    assert res.outcome is RunOutcome.REFUSED
    assert "still refuses" in res.detail
    assert ex.ledger.status_of("REQ-001:validate") is StepStatus.FAILED
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status != "done"


# -- AC3 ------------------------------------------------------------------------


def test_reland_precondition_failures(tmp_path):
    """``reland`` refuses, with a diagnostic routing to ``revalidate`` / ``repeat``, for any
    step outside its narrow shape: a regression-only REQ (no validate step), a
    DONE/PENDING/RUNNING validate, a red validation (BLOCKED), and a FAILED step with no green
    validation behind it."""
    # 1. regression-only REQ → no validate step → PENDING, refuse with both route hints
    ex = _build(tmp_path / "a", acs=(_REGRESSION,))
    res = ex.validate_runner.reland(ex, "REQ-001")
    assert res.outcome is RunOutcome.REFUSED
    assert "steward revalidate REQ-001" in res.detail
    assert "steward repeat REQ-001" in res.detail

    # 2. DONE validate → refuse
    ex = _build(tmp_path / "b")
    ex.ledger.set_status("REQ-001:validate", StepStatus.DONE)
    ex.ledger.save()
    assert ex.validate_runner.reland(ex, "REQ-001").outcome is RunOutcome.REFUSED

    # 3. RUNNING validate → refuse
    ex = _build(tmp_path / "c")
    ex.ledger.set_status("REQ-001:validate", StepStatus.RUNNING)
    ex.ledger.save()
    assert ex.validate_runner.reland(ex, "REQ-001").outcome is RunOutcome.REFUSED

    # 4. red validation parked (BLOCKED) → refuse, route to revalidate
    ex = _build(tmp_path / "d")
    ex.ledger.append_event(
        "validation", step="REQ-001:validate", req="REQ-001", ok=False,
        results=[{"ac": "AC2", "check": "artifact", "ok": False, "detail": "[1] false"}],
    )
    ex.ledger.set_status("REQ-001:validate", StepStatus.BLOCKED)
    ex.ledger.save()
    res = ex.validate_runner.reland(ex, "REQ-001")
    assert res.outcome is RunOutcome.REFUSED and "revalidate" in res.detail

    # 5. FAILED but no green validation behind it (only a red + a land_refused) → refuse
    ex = _build(tmp_path / "e")
    ex.ledger.append_event(
        "validation", step="REQ-001:validate", req="REQ-001", ok=False,
        results=[{"ac": "AC2", "check": "artifact", "ok": False, "detail": "[1] false"}],
    )
    ex.ledger.set_status("REQ-001:validate", StepStatus.FAILED)
    ex.ledger.save()
    ex.ledger.append_event("land_refused", step="REQ-001:validate", detail="no plan")
    assert ex.validate_runner.reland(ex, "REQ-001").outcome is RunOutcome.REFUSED
