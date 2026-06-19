"""REQ-033 — `steward rework`: the human-authorized return edge from a red validation.

AC1 re-arms develop+validate and records the rework event; AC2 refuses when there is no
red validation to rework; AC3 drives the full red→rework→fix→revalidate→land chain on the
real executor. AC4 (the live FlowSteward first case) is manual, out of automated scope.

Reuses the System-Test phase harness (`test_system_test_phase`) so the executor wiring —
real REQ source/verifier/flipper/land-gate/validate-routine around a fake `claude` and an
in-memory git topology — is identical to where the red is produced.
"""

from __future__ import annotations

import pytest
from devsteward.config import Config
from devsteward.core.executor import RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Decision, DecisionStatus, StepStatus
from devsteward.lifecycle import LifecycleError, rework
from devsteward.profiles.req.reqfile import parse_req

from conftest import FakeGitTopology, write_index
from test_system_test_phase import (
    SystemTesterRunner,
    _ARTIFACT_OK,
    _MANUAL,
    _REGRESSION,
    _events,
    _executor,
    _validation_events,
    _write_plan,
    _write_req,
)


def _seed_red(root, *, manual=False):
    """Seed an in-flight REQ-001 parked on a red validation, without running the loop:
    develop DONE, a red `validation` event, validate BLOCKED behind a parked decision."""
    req_dir = root / "docs" / "requirements"
    ac = _MANUAL if manual else {"id": "AC2", "test": "false", "check": "artifact"}
    _write_req(req_dir, "REQ-001", [_REGRESSION, ac], status="open")
    write_index(req_dir, [("REQ-001", "t", "OPEN", "–")])
    Ledger.init(root)
    led = Ledger(root)
    led.set_status("REQ-001:develop", StepStatus.DONE)
    led.save()
    detail = (
        "declined by Petra — live IMAP run still wrong"
        if manual
        else "[1] python -m pytest tests/test_imap.py::test_modseq\n    MODSEQ tuple decode failed"
    )
    led.append_event(
        "validation", step="REQ-001:validate", req="REQ-001", ok=False,
        driver="interactive", rerun=False,
        evidence=".devsteward/evidence/REQ-001/20260612T120000Z",
        results=[{"ac": "AC3" if manual else "AC2",
                  "check": "manual" if manual else "artifact",
                  "ok": False, "detail": detail}],
        artifacts=[], signoffs=[],
    )
    dec = Decision(
        id=led.next_decision_id(), step="REQ-001:validate",
        question=f"REQ-001 validation red — needs a human:\n{detail}", req="REQ-001",
    )
    led.park_decision(dec)  # sets validate BLOCKED + a decision_parked event
    return led, dec


# -- AC1 ------------------------------------------------------------------------


def test_rework_rearms_develop_and_validate(tmp_path):
    """rework flips develop→RECOVER and validate→PENDING, answers the parked decision, and
    appends a rework event carrying the red evidence path + brief; git and the REQ file are
    untouched. The declined-manual red is the same shape (D3)."""
    led, dec = _seed_red(tmp_path)
    req_path = tmp_path / "docs/requirements/REQ-001.md"
    before = req_path.read_text()

    res = rework(Config(root=tmp_path), led, "REQ-001")

    assert res.develop_step == "REQ-001:develop"
    assert res.validate_step == "REQ-001:validate"
    assert res.evidence == ".devsteward/evidence/REQ-001/20260612T120000Z"
    assert "MODSEQ" in res.brief and res.decision == dec.id

    fresh = Ledger(tmp_path)
    assert fresh.status_of("REQ-001:develop") is StepStatus.RECOVER
    assert fresh.status_of("REQ-001:validate") is StepStatus.PENDING
    answered = fresh.find_decision(dec.id)
    assert answered.status is DecisionStatus.ANSWERED and "reworked" in answered.answer
    rework_events = [e for e in fresh.events() if e["event"] == "rework"]
    assert len(rework_events) == 1
    assert rework_events[0]["evidence"] == res.evidence
    assert "MODSEQ" in rework_events[0]["brief"]

    # REQ file untouched (D5): no status flip, no verified_by — byte-identical.
    assert req_path.read_text() == before
    assert parse_req(req_path).status == "open"

    # A *declined manual* sign-off is the same red shape — rework re-arms it identically.
    other = tmp_path / "manual"
    other.mkdir()
    led_m, dec_m = _seed_red(other, manual=True)
    res_m = rework(Config(root=other), led_m, "REQ-001")
    fresh_m = Ledger(other)
    assert fresh_m.status_of("REQ-001:develop") is StepStatus.RECOVER
    assert fresh_m.status_of("REQ-001:validate") is StepStatus.PENDING
    assert res_m.decision == dec_m.id


# -- AC2 ------------------------------------------------------------------------


def test_rework_refusals(tmp_path):
    """rework refuses when there is no red validation to rework: unknown id, a done REQ
    (points at supersede), a REQ with no validate step, a validate step that is not
    blocked-red (green validation), and an awaiting-oracle manual park (no red event)."""
    led, _ = _seed_red(tmp_path)
    with pytest.raises(LifecycleError, match="not a known requirement"):
        rework(Config(root=tmp_path), led, "REQ-999")

    # done REQ → supersede pointer (done is never weakened, D3).
    done = tmp_path / "done"
    done.mkdir()
    ddir = done / "docs" / "requirements"
    _write_req(ddir, "REQ-001", [_REGRESSION, _ARTIFACT_OK], status="done")
    write_index(ddir, [("REQ-001", "t", "DONE", "–")])
    Ledger.init(done)
    led_d = Ledger(done)
    led_d.set_status("REQ-001:develop", StepStatus.DONE)
    led_d.set_status("REQ-001:validate", StepStatus.DONE)
    led_d.save()
    with pytest.raises(LifecycleError, match="supersed"):
        rework(Config(root=done), led_d, "REQ-001")

    # regression-only REQ → no validate step at all.
    reg = tmp_path / "reg"
    reg.mkdir()
    rdir = reg / "docs" / "requirements"
    _write_req(rdir, "REQ-001", [_REGRESSION], status="open")
    write_index(rdir, [("REQ-001", "t", "OPEN", "–")])
    Ledger.init(reg)
    led_r = Ledger(reg)
    led_r.set_status("REQ-001:develop", StepStatus.DONE)
    led_r.save()
    with pytest.raises(LifecycleError, match="no validate step"):
        rework(Config(root=reg), led_r, "REQ-001")

    # validate present but green (not blocked-red) → nothing to rework.
    green = tmp_path / "green"
    green.mkdir()
    gdir = green / "docs" / "requirements"
    _write_req(gdir, "REQ-001", [_REGRESSION, _ARTIFACT_OK], status="open")
    write_index(gdir, [("REQ-001", "t", "OPEN", "–")])
    Ledger.init(green)
    led_g = Ledger(green)
    led_g.set_status("REQ-001:develop", StepStatus.DONE)
    led_g.save()
    led_g.append_event(
        "validation", step="REQ-001:validate", req="REQ-001", ok=True,
        evidence="x", results=[{"ac": "AC2", "check": "artifact", "ok": True, "detail": "ok"}],
    )
    with pytest.raises(LifecycleError, match="no red validation"):
        rework(Config(root=green), led_g, "REQ-001")

    # a manual park merely awaiting its oracle is BLOCKED but records no red validation
    # event → not a red, rework refuses (run `steward validate` attended instead).
    awaiting = tmp_path / "awaiting"
    awaiting.mkdir()
    adir = awaiting / "docs" / "requirements"
    _write_req(adir, "REQ-001", [_REGRESSION, _MANUAL], status="open")
    write_index(adir, [("REQ-001", "t", "OPEN", "–")])
    Ledger.init(awaiting)
    led_a = Ledger(awaiting)
    led_a.set_status("REQ-001:develop", StepStatus.DONE)
    led_a.save()
    led_a.park_decision(Decision(
        id=led_a.next_decision_id(), step="REQ-001:validate",
        question="awaits human oracle", req="REQ-001",
    ))
    with pytest.raises(LifecycleError, match="no red validation"):
        rework(Config(root=awaiting), led_a, "REQ-001")


# -- AC3 ------------------------------------------------------------------------


class ReworkRunner(SystemTesterRunner):
    """The System Tester fake, plus: a develop ``--repeat`` session writes the ``FIXED``
    marker the artifact AC checks — modelling the builder's fix landing on the open branch
    so the previously-red acceptance command now passes."""

    def __call__(self, command, **kw):
        result = super().__call__(command, **kw)
        if "--repeat" in command:
            (self.root / "FIXED").write_text("yes\n", encoding="utf-8")
        return result


def test_rework_cycle_to_green_land(tmp_path):
    """The full chain on the real executor: develop (deferred) → red validation park →
    rework → develop --repeat fixes on the open branch → green re-validation → mechanical
    land + merge. The whole red→rework→fix→revalidate→land chain is in events.jsonl."""
    req_dir = tmp_path / "docs" / "requirements"
    _write_req(req_dir, "REQ-001",
               [_REGRESSION, {"id": "AC2", "test": "test -f FIXED", "check": "artifact"}])
    write_index(req_dir, [("REQ-001", "t", "OPEN", "–")])
    _write_plan(tmp_path, "REQ-001")
    Ledger.init(tmp_path)
    git = FakeGitTopology(current="dev")
    runner = ReworkRunner(tmp_path)
    ex = _executor(tmp_path, runner=runner, git=git)

    ex.advance_once(only="REQ-001")  # develop — deferred commit, no land
    red = ex.advance_once(only="REQ-001")  # validate — artifact AC red (no FIXED yet)
    assert red.outcome is RunOutcome.PARKED
    assert ex.ledger.status_of("REQ-001:validate") is StepStatus.BLOCKED

    # the human reviews the red and orders a fix
    rres = rework(Config(root=tmp_path), ex.ledger, "REQ-001")
    assert rres.evidence and rres.evidence.startswith(".devsteward/evidence/REQ-001/")
    assert ex.ledger.status_of("REQ-001:develop") is StepStatus.RECOVER
    assert "REQ-001:develop" in [s.id for s in ex.eligible_steps()]

    ex.advance_once(only="REQ-001")  # develop --repeat — writes FIXED, deferred commit
    green = ex.advance_once(only="REQ-001")  # validate — now green → land
    assert green.outcome is RunOutcome.DONE
    assert parse_req(req_dir / "REQ-001.md").status == "done"
    assert git.current == "dev"  # REQ-048: the green validate lands on dev, no merge

    # the full chain is auditable in events.jsonl, in order
    events = _events(tmp_path)
    kinds = [e["event"] for e in events]
    assert kinds.count("rework") == 1
    assert [v["ok"] for v in _validation_events(tmp_path)] == [False, True]
    i_redval = next(i for i, e in enumerate(events)
                    if e["event"] == "validation" and e["ok"] is False)
    i_rework = kinds.index("rework")
    i_recover = next(i for i, e in enumerate(events)
                     if e["event"] == "step_started"
                     and e["step"] == "REQ-001:develop" and e.get("recover"))
    i_greenval = next(i for i, e in enumerate(events)
                      if e["event"] == "validation" and e["ok"] is True)
    i_checkpoint = next(i for i, e in enumerate(events) if e["event"] == "checkpoint")
    assert i_redval < i_rework < i_recover < i_greenval < i_checkpoint
