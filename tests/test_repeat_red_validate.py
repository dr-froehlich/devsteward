"""`steward repeat` on a validate step parked on a **red** — REQ-055's body, REQ-098's verb.

A red validation has two root causes: the develop was *hollow* (internal — `rework` reopens
develop) or an external lab/setup issue was fixed and the develop *stands* (re-run the
validation only). REQ-055 built the second edge as `steward revalidate`; REQ-098 Decision 1
deleted that verb and folded its body — unchanged — into `steward repeat`, which reads the
ledger to find the red instead of making the operator name it. The ledger event is still
`revalidate` (REQ-098 Decision 5), so every consumer ledger keeps replaying.

What is asserted here: the re-arm touches validate only (develop stays DONE) and records
the `revalidate` event; `repeat` refuses only when nothing stopped; the `_park_red` brief
names both moves; and the CLI wiring is HEAD-agnostic, atomic and non-zero on a refusal.

Reuses `test_rework.py`'s `_seed_red` red-validation harness (the identical in-memory git
topology where `rework` is exercised) so both moves run against the same wiring.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner
from devsteward.cli import main as cli_main
from devsteward.config import Config
from devsteward.core.executor import RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Decision, DecisionStatus, StepStatus
from devsteward.lifecycle import LifecycleError, repeat
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


def test_repeat_rearms_validate_only(tmp_path):
    """`repeat` on a red flips validate→PENDING and ONLY that — develop stays DONE
    (untouched), the parked decision is answered, and a `revalidate` event carries the red
    evidence path + brief; git and the REQ file are untouched. The declined-manual red is the
    same shape."""
    led, dec = _seed_red(tmp_path)
    req_path = tmp_path / "docs/requirements/REQ-001.md"
    before = req_path.read_text()

    res = repeat(Config(root=tmp_path), led, "REQ-001")

    assert res.kinds == ["revalidate"] and res.steps == ["REQ-001:validate"]
    assert res.recovered == []                       # nothing FAILED here, only the red park
    assert res.evidence == ".devsteward/evidence/REQ-001/20260612T120000Z"
    assert "MODSEQ" in res.brief and res.decision == dec.id

    fresh = Ledger(tmp_path)
    # The whole point of the mirror: develop is left DONE; only validate re-arms.
    assert fresh.status_of("REQ-001:develop") is StepStatus.DONE
    assert fresh.status_of("REQ-001:validate") is StepStatus.PENDING
    answered = fresh.find_decision(dec.id)
    assert answered.status is DecisionStatus.ANSWERED and "repeated" in answered.answer
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

    # A *declined manual* sign-off is the same red shape — repeat re-arms it identically.
    other = tmp_path / "manual"
    other.mkdir()
    led_m, dec_m = _seed_red(other, manual=True)
    res_m = repeat(Config(root=other), led_m, "REQ-001")
    fresh_m = Ledger(other)
    assert fresh_m.status_of("REQ-001:develop") is StepStatus.DONE
    assert fresh_m.status_of("REQ-001:validate") is StepStatus.PENDING
    assert res_m.decision == dec_m.id


# -- AC2 ------------------------------------------------------------------------


def test_repeat_refuses_only_when_nothing_stopped(tmp_path):
    """REQ-098 Decision 3 withdrew REQ-055's symmetric-with-`rework` refusal taxonomy.

    `repeat` reads the ledger for a *stopped* step, so it no longer refuses an unknown id, a
    done REQ or a REQ without a validate step on their own account — each of those simply has
    nothing stopped, and one refusal covers them all. The state that used to refuse and now
    succeeds is the awaiting-oracle `manual` park (state F): REQ-055 Decision 2 kept it out
    because its forward path was `steward validate`, which stays true (Decision 6) — but the
    operator may now also re-arm it, which is the whole point of the item.
    """
    def _project(root, acs, *, status="open", develop=StepStatus.DONE):
        rdir = root / "docs" / "requirements"
        _write_req(rdir, "REQ-001", acs, status=status)
        write_index(rdir, [("REQ-001", "t", status.upper(), "–")])
        Ledger.init(root)
        led = Ledger(root)
        led.set_status("REQ-001:develop", develop)
        led.save()
        return led

    # (a) an unknown id has no steps at all → nothing to repeat.
    led = _seed_red(tmp_path)[0]
    with pytest.raises(LifecycleError, match="nothing to repeat"):
        repeat(Config(root=tmp_path), led, "REQ-999")

    # (b) a done REQ: every step DONE → nothing stopped.
    done = tmp_path / "done"; done.mkdir()
    led_d = _project(done, [_REGRESSION, {"id": "AC2", "test": "true", "check": "artifact"}],
                     status="done")
    led_d.set_status("REQ-001:validate", StepStatus.DONE)
    led_d.save()
    with pytest.raises(LifecycleError, match="nothing to repeat"):
        repeat(Config(root=done), led_d, "REQ-001")

    # (c) a regression-only REQ whose develop is done → nothing stopped.
    reg = tmp_path / "reg"; reg.mkdir()
    led_r = _project(reg, [_REGRESSION])
    with pytest.raises(LifecycleError, match="nothing to repeat"):
        repeat(Config(root=reg), led_r, "REQ-001")

    # (d) a validate step that is present but *green* (never parked) → nothing stopped.
    green = tmp_path / "green"; green.mkdir()
    led_g = _project(green, [_REGRESSION, {"id": "AC2", "test": "true", "check": "artifact"}])
    led_g.append_event(
        "validation", step="REQ-001:validate", req="REQ-001", ok=True,
        evidence="x", results=[{"ac": "AC2", "check": "artifact", "ok": True, "detail": "ok"}],
    )
    with pytest.raises(LifecycleError, match="nothing to repeat"):
        repeat(Config(root=green), led_g, "REQ-001")

    # (e) the awaiting-oracle `manual` park — BLOCKED with no red validation event. This is
    # the state REQ-055 Decision 2 excluded; REQ-098 re-arms it (hold cleared, no scope).
    awaiting = tmp_path / "awaiting"; awaiting.mkdir()
    led_a = _project(awaiting, [_REGRESSION, {"id": "AC2", "test": "x", "check": "manual"}])
    led_a.set_hold("REQ-001:validate", "awaits its human oracle — steward validate REQ-001")
    led_a.save()
    res = repeat(Config(root=awaiting), led_a, "REQ-001")
    assert res.kinds == ["unhold"] and res.scope is None and res.evidence is None
    fresh_a = Ledger(awaiting)
    assert fresh_a.status_of("REQ-001:validate") is StepStatus.PENDING
    assert fresh_a.status_of("REQ-001:develop") is StepStatus.DONE
    assert fresh_a.hold_note("REQ-001:validate") == ""


# -- AC3 ------------------------------------------------------------------------


def test_red_park_brief_names_both_moves(tmp_path):
    """The red-validation brief frames a choice keyed on the root cause — it names BOTH
    `steward rework` (internal cause / hollow develop) and `steward repeat` (external cause /
    lab fixed, develop stands), in the in-flight parked-decision question AND the
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
    # REQ-074: the red validation is a hold naming both edges, not a decision.
    assert ex.ledger.open_decisions() == []
    hold = ex.ledger.hold_note("REQ-001:validate")
    assert "steward rework REQ-001" in hold
    assert "steward repeat REQ-001" in hold

    # Non-in-flight: the VERIFY_FAILED detail of a done re-validation names both edges too.
    routine = ReqValidateRoutine(req_dir)
    req = routine._req("REQ-001")
    step = ex.step_by_id("REQ-001:validate")
    results = [{"ac": "AC2", "check": "artifact", "ok": False, "detail": "boom"}]
    res = routine._park_red(ex, step, req, results, in_flight=False)
    assert res.outcome is RunOutcome.VERIFY_FAILED
    assert "steward rework REQ-001" in res.detail
    assert "steward repeat REQ-001" in res.detail


# -- AC4 ------------------------------------------------------------------------


def test_repeat_cli_wiring_on_a_red(tmp_path, monkeypatch):
    """`steward repeat REQ` takes the red branch from the CLI and mirrors rework: it succeeds
    even on the production branch (HEAD-agnostic, single-ledger invariant only) inside an
    atomic transaction, prints the validate→pending transition (develop stays done), and maps
    a LifecycleError refusal to a non-zero exit."""
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

    out = CliRunner().invoke(cli_main, ["repeat", "REQ-001"], catch_exceptions=False)
    assert out.exit_code == 0, out.output
    assert "pending" in out.output and "develop stays done" in out.output

    reloaded = Ledger(tmp_path)
    assert reloaded.status_of("REQ-001:develop") is StepStatus.DONE   # untouched
    assert reloaded.status_of("REQ-001:validate") is StepStatus.PENDING

    # A refusal (unknown id) maps to a non-zero exit.
    bad = CliRunner().invoke(cli_main, ["repeat", "REQ-999"])
    assert bad.exit_code != 0
