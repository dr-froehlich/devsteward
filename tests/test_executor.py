"""REQ-003 AC2, REQ-005 AC1, REQ-006 — the executor loop end to end (fake runner)."""

from __future__ import annotations

from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Step, StepStatus
from devsteward.core.verify import CommandVerifier

from conftest import FakeRunner, ListStepSource, RecordingCommitter, ok_result, park_result


def _executor(root, steps, runner, committer=None):
    return Executor(
        root=root,
        source=ListStepSource(steps),
        verifier=CommandVerifier(cwd=str(root)),
        accounts=SingleAccountProvider(),
        runner=runner,
        committer=committer or RecordingCommitter(),
    )


def test_run_step_done_path(project):
    """A step whose acceptance test passes is committed and advanced to done."""
    step = Step(id="REQ-009:land", command="/advance REQ-009 land", verify=("true",))
    committer = RecordingCommitter()
    ex = _executor(project, [step], FakeRunner(default=ok_result()), committer)

    res = ex.run_step(step)
    assert res.outcome is RunOutcome.DONE
    assert res.commit is not None
    assert committer.committed == ["REQ-009:land"]
    assert Ledger(project).status_of("REQ-009:land") is StepStatus.DONE


def test_verify_failure_blocks_done(project):
    """A step whose acceptance test fails is marked failed, never done, no commit."""
    step = Step(id="REQ-009:land", command="/advance", verify=("false",))
    committer = RecordingCommitter()
    ex = _executor(project, [step], FakeRunner(default=ok_result()), committer)

    res = ex.run_step(step)
    assert res.outcome is RunOutcome.VERIFY_FAILED
    assert committer.committed == []
    assert Ledger(project).status_of("REQ-009:land") is StepStatus.FAILED


def test_unattended_env_is_signalled(project):
    step = Step(id="REQ-009:build", command="/advance", verify=())
    runner = FakeRunner(default=ok_result())
    ex = _executor(project, [step], runner)
    ex.run_step(step, unattended=True)
    assert runner.calls[-1]["unattended"] is True


def test_park_and_surface(project):
    """One step parks a fork (blocked, no commit); the next independent step still runs."""
    a = Step(id="REQ-A:design", command="/advance REQ-A design", verify=())
    b = Step(id="REQ-B:design", command="/advance REQ-B design", verify=())
    runner = FakeRunner(script={"REQ-A": park_result("Which database?")},
                        default=ok_result())
    committer = RecordingCommitter()
    ex = _executor(project, [a, b], runner, committer)

    results = ex.run()
    outcomes = {r.step.id: r.outcome for r in results}
    assert outcomes["REQ-A:design"] is RunOutcome.PARKED
    assert outcomes["REQ-B:design"] is RunOutcome.DONE

    led = Ledger(project)
    assert led.status_of("REQ-A:design") is StepStatus.BLOCKED
    assert led.status_of("REQ-B:design") is StepStatus.DONE
    # The parked fork is recorded and surfaced; A was never committed.
    assert "REQ-A:design" not in committer.committed
    parked = led.open_decisions()
    assert len(parked) == 1 and parked[0].step == "REQ-A:design"
    assert "database" in parked[0].question.lower()


def test_answer_then_resume(project):
    """After answering the parked decision, a later run resumes the unblocked step."""
    a = Step(id="REQ-A:design", command="/advance REQ-A design", verify=())
    runner = FakeRunner(script={"REQ-A": park_result("fork?")}, default=ok_result())
    ex = _executor(project, [a], runner)
    ex.run()
    assert Ledger(project).status_of("REQ-A:design") is StepStatus.BLOCKED

    Ledger(project).answer_decision("DEC-001", "resolved")
    # Now the runner succeeds for REQ-A.
    ex2 = _executor(project, [a], FakeRunner(default=ok_result()))
    results = ex2.run()
    assert results[-1].outcome is RunOutcome.DONE
    assert Ledger(project).status_of("REQ-A:design") is StepStatus.DONE


def test_dependencies_gate_eligibility(project):
    design = Step(id="R:design", command="/advance", verify=())
    build = Step(id="R:build", command="/advance", depends_on=("R:design",), verify=())
    ex = _executor(project, [design, build], FakeRunner(default=ok_result()))

    # Only design is eligible at first.
    assert [s.id for s in ex.eligible_steps()] == ["R:design"]
    ex.run_step(design)
    # Now build is eligible.
    assert [s.id for s in ex.eligible_steps()] == ["R:build"]
