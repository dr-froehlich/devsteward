"""REQ-055 — `steward revalidate`: the external-cause mirror of `steward rework`.

A red validation has two root causes. The develop was *hollow* (internal — `rework` reopens
develop) or an external lab/setup issue was fixed and the develop *stands* (re-run validate
only — this verb). REQ-055 names the missing symmetric edge and corrects the red-park brief
so it offers the choice instead of presuming the internal cause.

AC1 re-arms validate only (develop stays DONE) and records the `revalidate` event; AC2
refuses on the same taxonomy as `rework`; AC3 checks the `_park_red` brief names both edges;
AC4 is the CLI wiring (HEAD-agnostic, atomic, non-zero on refusal).

Reuses `test_rework.py`'s `_seed_red` red-validation harness (the identical in-memory git
topology where `rework` is exercised) so the mirror verb runs against the same wiring.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner
from devsteward.cli import main as cli_main
from devsteward.config import Config
from devsteward.core.executor import RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Decision, DecisionStatus, StepStatus
from devsteward.lifecycle import LifecycleError, revalidate
from devsteward.profiles.req.reqfile import parse_req
from devsteward.profiles.req.validate import ReqValidateRoutine

from conftest import FakeGitTopology, write_index
from test_rework import _seed_red
from test_system_test_phase import (
    SystemTesterRunner,
    _REGRESSION,
    _executor,
    _write_plan,
    _write_req,
)
from test_transaction_boundary import _init_git, _scaffold


# -- AC1 ------------------------------------------------------------------------


def test_revalidate_rearms_validate_only(tmp_path):
    """revalidate flips validate→PENDING and ONLY that — develop stays DONE (untouched),
    the parked decision is answered, and a `revalidate` event carries the red evidence path
    + brief; git and the REQ file are untouched. The declined-manual red is the same shape."""
    led, dec = _seed_red(tmp_path)
    req_path = tmp_path / "docs/requirements/REQ-001.md"
    before = req_path.read_text()

    res = revalidate(Config(root=tmp_path), led, "REQ-001")

    assert res.validate_step == "REQ-001:validate"
    assert res.evidence == ".devsteward/evidence/REQ-001/20260612T120000Z"
    assert "MODSEQ" in res.brief and res.decision == dec.id

    fresh = Ledger(tmp_path)
    # The whole point of the mirror: develop is left DONE; only validate re-arms.
    assert fresh.status_of("REQ-001:develop") is StepStatus.DONE
    assert fresh.status_of("REQ-001:validate") is StepStatus.PENDING
    answered = fresh.find_decision(dec.id)
    assert answered.status is DecisionStatus.ANSWERED and "revalidated" in answered.answer
    reval_events = [e for e in fresh.events() if e["event"] == "revalidate"]
    assert len(reval_events) == 1
    assert reval_events[0]["evidence"] == res.evidence
    assert reval_events[0]["validate"] == "REQ-001:validate"
    assert "MODSEQ" in reval_events[0]["brief"]
    # No `develop` key — develop is deliberately not the subject of this edge.
    assert "develop" not in reval_events[0]

    # REQ file untouched: no status flip, no verified_by — byte-identical.
    assert req_path.read_text() == before
    assert parse_req(req_path).status == "open"

    # A *declined manual* sign-off is the same red shape — revalidate re-arms it identically.
    other = tmp_path / "manual"
    other.mkdir()
    led_m, dec_m = _seed_red(other, manual=True)
    res_m = revalidate(Config(root=other), led_m, "REQ-001")
    fresh_m = Ledger(other)
    assert fresh_m.status_of("REQ-001:develop") is StepStatus.DONE
    assert fresh_m.status_of("REQ-001:validate") is StepStatus.PENDING
    assert res_m.decision == dec_m.id


# -- AC2 ------------------------------------------------------------------------


def test_revalidate_refusals(tmp_path):
    """revalidate refuses symmetrically to rework: unknown id, a done REQ (points at
    supersede), a REQ with no validate step, a validate step not blocked-red (green
    validation), and an awaiting-oracle manual park (no red event)."""
    led, _ = _seed_red(tmp_path)
    with pytest.raises(LifecycleError, match="not a known requirement"):
        revalidate(Config(root=tmp_path), led, "REQ-999")

    # done REQ → supersede pointer (done is never weakened).
    done = tmp_path / "done"
    done.mkdir()
    ddir = done / "docs" / "requirements"
    _write_req(ddir, "REQ-001", [_REGRESSION, {"id": "AC2", "test": "true", "check": "artifact"}],
               status="done")
    write_index(ddir, [("REQ-001", "t", "DONE", "–")])
    Ledger.init(done)
    led_d = Ledger(done)
    led_d.set_status("REQ-001:develop", StepStatus.DONE)
    led_d.set_status("REQ-001:validate", StepStatus.DONE)
    led_d.save()
    with pytest.raises(LifecycleError, match="supersed"):
        revalidate(Config(root=done), led_d, "REQ-001")

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
        revalidate(Config(root=reg), led_r, "REQ-001")

    # validate present but green (not blocked-red) → nothing to revalidate.
    green = tmp_path / "green"
    green.mkdir()
    gdir = green / "docs" / "requirements"
    _write_req(gdir, "REQ-001", [_REGRESSION, {"id": "AC2", "test": "true", "check": "artifact"}],
               status="open")
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
        revalidate(Config(root=green), led_g, "REQ-001")

    # an awaiting-oracle manual park is BLOCKED but records no red validation event → not a
    # red, revalidate refuses (run `steward validate` attended instead).
    awaiting = tmp_path / "awaiting"
    awaiting.mkdir()
    adir = awaiting / "docs" / "requirements"
    _write_req(adir, "REQ-001", [_REGRESSION, {"id": "AC2", "test": "x", "check": "manual"}],
               status="open")
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
        revalidate(Config(root=awaiting), led_a, "REQ-001")


# -- AC3 ------------------------------------------------------------------------


def test_red_park_brief_names_both_edges(tmp_path):
    """The red-validation brief frames a choice keyed on the root cause — it names BOTH
    `steward rework` (internal cause / hollow develop) and `steward revalidate` (external
    cause / lab fixed, develop stands), in the in-flight parked-decision question AND the
    non-in-flight VERIFY_FAILED detail — not an unconditional steer to rework."""
    # In-flight: drive a real red park through the executor and read the parked decision.
    req_dir = tmp_path / "docs" / "requirements"
    _write_req(req_dir, "REQ-001",
               [_REGRESSION, {"id": "AC2", "test": "false", "check": "artifact"}])
    write_index(req_dir, [("REQ-001", "t", "OPEN", "–")])
    _write_plan(tmp_path, "REQ-001")
    Ledger.init(tmp_path)
    ex = _executor(tmp_path, runner=SystemTesterRunner(tmp_path),
                   git=FakeGitTopology(current="dev"))
    ex.advance_once(only="REQ-001")            # develop — deferred commit
    red = ex.advance_once(only="REQ-001")      # validate — artifact AC red → park
    assert red.outcome is RunOutcome.PARKED
    (dec,) = ex.ledger.open_decisions()
    assert "steward rework REQ-001" in dec.question
    assert "steward revalidate REQ-001" in dec.question

    # Non-in-flight: the VERIFY_FAILED detail of a done re-validation names both edges too.
    routine = ReqValidateRoutine(req_dir)
    req = routine._req("REQ-001")
    step = ex.step_by_id("REQ-001:validate")
    results = [{"ac": "AC2", "check": "artifact", "ok": False, "detail": "boom"}]
    res = routine._park_red(ex, step, req, results, in_flight=False)
    assert res.outcome is RunOutcome.VERIFY_FAILED
    assert "steward rework REQ-001" in res.detail
    assert "steward revalidate REQ-001" in res.detail


# -- AC4 ------------------------------------------------------------------------


def test_revalidate_cli_wiring(tmp_path, monkeypatch):
    """`steward revalidate REQ` is registered and mirrors recover/rework: it succeeds even on
    the production branch (HEAD-agnostic, single-ledger invariant only) inside an atomic
    transaction, prints the validate→pending transition (develop stays done), and maps a
    LifecycleError refusal to a non-zero exit."""
    _scaffold(tmp_path, acs=(("AC1", "true", "regression"),
                             ("AC2", "false", "artifact")))
    # On the *production* branch: an advancing command would refuse — a recovery verb must not.
    _init_git(tmp_path, branch="main")
    monkeypatch.chdir(tmp_path)

    # Seed an in-flight REQ parked on a red validation.
    led = Ledger(tmp_path)
    led.set_status("REQ-001:develop", StepStatus.DONE)
    led.save()
    led.append_event(
        "validation", step="REQ-001:validate", req="REQ-001", ok=False,
        driver="interactive", rerun=False,
        evidence=".devsteward/evidence/REQ-001/20260612T120000Z",
        results=[{"ac": "AC2", "check": "artifact", "ok": False, "detail": "boom"}],
        artifacts=[], signoffs=[],
    )
    led.park_decision(Decision(
        id=led.next_decision_id(), step="REQ-001:validate",
        question="REQ-001 validation red", req="REQ-001",
    ))

    out = CliRunner().invoke(cli_main, ["revalidate", "REQ-001"], catch_exceptions=False)
    assert out.exit_code == 0, out.output
    assert "pending" in out.output and "develop stays done" in out.output

    reloaded = Ledger(tmp_path)
    assert reloaded.status_of("REQ-001:develop") is StepStatus.DONE   # untouched
    assert reloaded.status_of("REQ-001:validate") is StepStatus.PENDING

    # A refusal (unknown id) maps to a non-zero exit.
    bad = CliRunner().invoke(cli_main, ["revalidate", "REQ-999"])
    assert bad.exit_code != 0
