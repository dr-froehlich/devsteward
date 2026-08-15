"""REQ-074 AC2/AC3/AC4 — the decisions namespace re-founded.

Validation and attended waits are ledger **holds** (surfaced by `steward status`, resolved
by their own verbs), never `Decision` records; a decision is a genuine skill-raised fork
only, parked with a brief (context, options, recommendation) so the operator is briefed,
not just questioned.
"""

from __future__ import annotations

from click.testing import CliRunner

from devsteward.cli import main as cli_main
from devsteward.core.claude import Outcome, Result
from devsteward.core.executor import PARK_SENTINEL, Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Step, StepStatus
from devsteward.core.verify import CommandVerifier
from devsteward.core.accounts import SingleAccountProvider
from devsteward.lifecycle import revalidate, rework
from devsteward.profiles.req.validate import Signoff

from conftest import (
    FakeGitTopology,
    FakeRunner,
    ListStepSource,
    RecordingCommitter,
    ok_result,
    write_index,
)
from test_system_test_phase import (
    _MANUAL,
    _REGRESSION,
    _executor,
    _validation_events,
    _write_plan,
    _write_req,
)


def _core_executor(root, steps, runner):
    return Executor(
        # REQ-091: a spawn names its model; an unconfigured headless spawn refuses.
        model="test-spawn-model",
        root=root,
        source=ListStepSource(steps),
        verifier=CommandVerifier(cwd=str(root)),
        accounts=SingleAccountProvider(),
        runner=runner,
        committer=RecordingCommitter(),
        git=FakeGitTopology(),
    )


# -- AC2: validation holds are holds, not decisions -------------------------------


def test_validate_holds_park_no_decision(tmp_path):
    """The pending-oracle park (manual AC, unattended) and the red-validation park leave
    **no** Decision record — the wait is a ledger hold naming its real verb."""
    # Pending human oracle (unattended manual AC).
    req_dir = tmp_path / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", [_REGRESSION, _MANUAL])
    write_index(req_dir, [("REQ-001", "REQ-001 title", "OPEN", "–")])
    _write_plan(tmp_path, "REQ-001")
    Ledger.init(tmp_path)
    ex = _executor(tmp_path)
    ex.advance_once(only="REQ-001")  # develop
    res = ex.advance_once(only="REQ-001")  # unattended validate → oracle wait
    assert res.outcome is RunOutcome.PARKED
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:validate") is StepStatus.BLOCKED
    assert led.open_decisions() == []
    hold = led.hold_note("REQ-001:validate")
    assert "steward validate REQ-001" in hold and "human oracle" in hold

    # Red validation (declined manual sign-off, attended): a hold naming both return
    # edges — still no decision.
    red = tmp_path / "red"
    red.mkdir()
    req_dir2 = red / "docs" / "requirements"
    _write_req(req_dir2, "REQ-001", [_REGRESSION, _MANUAL])
    write_index(req_dir2, [("REQ-001", "REQ-001 title", "OPEN", "–")])
    _write_plan(red, "REQ-001")
    Ledger.init(red)
    ex2 = _executor(red)
    ex2.advance_once(only="REQ-001")
    step = ex2.step_by_id("REQ-001:validate")
    res2 = ex2.validate_runner(
        ex2, step, unattended=False, driver="interactive",
        signoff=lambda ac: Signoff(approved=False, reviewer="Petra"),
    )
    assert res2.outcome is RunOutcome.PARKED
    led2 = Ledger(red)
    assert led2.open_decisions() == []
    hold2 = led2.hold_note("REQ-001:validate")
    assert "steward rework REQ-001" in hold2 and "steward revalidate REQ-001" in hold2


def test_rework_and_revalidate_work_without_decision_record(tmp_path):
    """`steward rework` / `steward revalidate` key on the red validation event + the
    blocked step — with no Decision record present (the REQ-074 shape), both edges work."""
    from devsteward.config import Config

    def seed(root):
        req_dir = root / "docs" / "requirements"
        _write_req(req_dir, "REQ-001",
                   [_REGRESSION, {"id": "AC2", "test": "false", "check": "artifact"}])
        write_index(req_dir, [("REQ-001", "t", "OPEN", "–")])
        Ledger.init(root)
        led = Ledger(root)
        led.set_status("REQ-001:develop", StepStatus.DONE)
        led.save()
        led.append_event(
            "validation", step="REQ-001:validate", req="REQ-001", ok=False,
            driver="interactive", rerun=False,
            evidence=".devsteward/evidence/REQ-001/20260705T120000Z",
            results=[{"ac": "AC2", "check": "artifact", "ok": False, "detail": "red"}],
            artifacts=[], signoffs=[],
        )
        led.set_hold("REQ-001:validate", "REQ-001 validation red — rework or revalidate")
        led.save()
        return Config(root=root), Ledger(root)

    cfg, led = seed(tmp_path)
    assert led.open_decisions() == []  # the precondition under test
    res = rework(cfg, led, "REQ-001")
    assert res.develop_step == "REQ-001:develop"
    assert led.status_of("REQ-001:develop") is StepStatus.RECOVER
    assert led.status_of("REQ-001:validate") is StepStatus.PENDING
    assert led.hold_note("REQ-001:validate") == ""  # the hold cleared with the unblock

    other = tmp_path / "reval"
    other.mkdir()
    cfg2, led2 = seed(other)
    res2 = revalidate(cfg2, led2, "REQ-001")
    assert res2.validate_step == "REQ-001:validate"
    assert led2.status_of("REQ-001:develop") is StepStatus.DONE
    assert led2.status_of("REQ-001:validate") is StepStatus.PENDING


# -- AC3: the attended wait is a hold, not a decision ------------------------------


def test_attended_park_is_a_hold_not_a_decision(project):
    """Batch hitting an attended step blocks it with a hold naming the run-attended verb —
    no Decision record, so the circular answer→re-run→re-park trap is structurally gone."""
    step = Step(
        id="REQ-A:develop", command="/advance REQ-A develop", req="REQ-A",
        attended=True, attended_reason="REQ-A declared a concept phase",
    )
    ex = _core_executor(project, [step], FakeRunner(default=ok_result()))
    res = ex.run_step(step, unattended=True)
    assert res.outcome is RunOutcome.PARKED
    led = Ledger(project)
    assert led.open_decisions() == []
    assert led.status_of("REQ-A:develop") is StepStatus.BLOCKED
    hold = led.hold_note("REQ-A:develop")
    assert "concept phase" in hold and "/advance REQ-A" in hold


# -- AC4: a genuine fork parks with a brief ----------------------------------------


_BRIEF_TEXT = (
    f"{PARK_SENTINEL} Which database engine should the cache use?\n"
    "The REQ is silent; both fit the constraints and migration differs.\n"
    "- sqlite (zero-ops, single file)\n"
    "- postgres (matches production)\n"
    "recommendation: sqlite — the cache is local and disposable\n"
)


def test_skill_fork_parks_with_brief_and_list_renders_it(tmp_path, monkeypatch):
    """Both park paths carry the fork brief: the sentinel block parses into question +
    context + options + recommendation, and `steward decision-list` renders it all."""
    from test_transaction_boundary import _init_git, _scaffold

    _scaffold(tmp_path, acs=(("AC1", "true", "regression"),))
    _init_git(tmp_path)
    monkeypatch.chdir(tmp_path)

    step = Step(id="REQ-A:develop", command="/advance REQ-A develop", req="REQ-A")
    runner = FakeRunner(default=Result(Outcome.OK, _BRIEF_TEXT, [], 0))
    ex = _core_executor(tmp_path, [step], runner)
    res = ex.run_step(step, unattended=True)
    assert res.outcome is RunOutcome.PARKED

    (dec,) = Ledger(tmp_path).open_decisions()
    assert dec.question == "Which database engine should the cache use?"
    assert dec.options == [
        "sqlite (zero-ops, single file)", "postgres (matches production)",
    ]
    assert dec.recommendation.startswith("sqlite")
    assert "migration differs" in dec.context

    out = CliRunner().invoke(cli_main, ["decision-list"])
    assert out.exit_code == 0, out.output
    assert "Which database engine" in out.output
    assert "option 1: sqlite (zero-ops, single file)" in out.output
    assert "option 2: postgres (matches production)" in out.output
    assert "recommendation: sqlite" in out.output
    assert "steward decide DEC-001" in out.output
