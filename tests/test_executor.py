"""REQ-003 AC2, REQ-005 AC1, REQ-006 — the executor loop end to end (fake runner)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Decision, Step, StepStatus
from devsteward.core.verify import CommandVerifier

from conftest import (
    FakeGitTopology,
    FakeRunner,
    ListStepSource,
    RecordingCommitter,
    ok_result,
    park_result,
)


def _executor(root, steps, runner, committer=None, on_verified=None):
    return Executor(
        root=root,
        source=ListStepSource(steps),
        verifier=CommandVerifier(cwd=str(root)),
        accounts=SingleAccountProvider(),
        runner=runner,
        committer=committer or RecordingCommitter(),
        on_verified=on_verified,
        git=FakeGitTopology(),  # REQ-049: unit loop tests use the in-memory git seam (on dev)
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


def test_on_verified_runs_after_pass_before_commit(project):
    """The terminal-flip hook fires only on a passing verify, ahead of the commit, so any
    status flip it makes is captured by the one checkpoint commit (the engine-owns-`done`
    fix)."""
    order: list[str] = []
    step = Step(id="REQ-009:land", command="/advance", verify=("true",))

    class Spy(RecordingCommitter):
        def __call__(self, s):
            order.append("commit")
            return super().__call__(s)

    committer = Spy()
    ex = _executor(
        project, [step], FakeRunner(default=ok_result()), committer,
        on_verified=lambda s: order.append(f"verified:{s.id}"),
    )
    res = ex.run_step(step)
    assert res.outcome is RunOutcome.DONE
    assert order == ["verified:REQ-009:land", "commit"]


def test_on_verified_skipped_when_verify_fails(project):
    """A failed land never reaches the terminal flip — nothing writes a premature `done`."""
    calls: list[str] = []
    step = Step(id="REQ-009:land", command="/advance", verify=("false",))
    ex = _executor(
        project, [step], FakeRunner(default=ok_result()),
        on_verified=lambda s: calls.append(s.id),
    )
    res = ex.run_step(step)
    assert res.outcome is RunOutcome.VERIFY_FAILED
    assert calls == []


def test_checkpoint_flips_commits_and_advances(project):
    """`steward checkpoint` runs the verify→flip→commit→advance tail for an interactive
    land — one transaction, no claude call."""
    flipped: list[str] = []
    step = Step(id="REQ-009:land", command="/advance", verify=("true",))
    committer = RecordingCommitter()
    ex = _executor(
        project, [step], FakeRunner(default=ok_result()), committer,
        on_verified=lambda s: flipped.append(s.id),
    )
    res = ex.checkpoint(step)
    assert res.outcome is RunOutcome.DONE
    assert flipped == ["REQ-009:land"]
    assert committer.committed == ["REQ-009:land"]
    assert Ledger(project).status_of("REQ-009:land") is StepStatus.DONE


def test_checkpoint_verify_failure_does_not_flip_or_commit(project):
    """A red checkpoint marks the step failed and touches neither the flip nor the commit."""
    flipped: list[str] = []
    step = Step(id="REQ-009:land", command="/advance", verify=("false",))
    committer = RecordingCommitter()
    ex = _executor(
        project, [step], FakeRunner(default=ok_result()), committer,
        on_verified=lambda s: flipped.append(s.id),
    )
    res = ex.checkpoint(step)
    assert res.outcome is RunOutcome.VERIFY_FAILED
    assert flipped == []
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


def test_recover_status_eligible_and_signalled(project):
    """REQ-026 AC4: a RECOVER step is eligible; the executor drives it with `--repeat` in the
    command (the resume signal, renamed from `--recover` by REQ-054, so the skill knows it is
    resuming); a clean run advances it to DONE."""
    step = Step(id="REQ-9:land", command="/advance REQ-9 land", verify=("true",), req="REQ-9")
    runner = FakeRunner(default=ok_result())
    ex = _executor(project, [step], runner)
    ex.ledger.set_status("REQ-9:land", StepStatus.RECOVER)
    ex.ledger.save()

    assert [s.id for s in ex.eligible_steps()] == ["REQ-9:land"]  # RECOVER is runnable

    res = ex.run_step(step)
    assert res.outcome is RunOutcome.DONE
    assert "--repeat" in runner.calls[-1]["command"]  # recovery signalled to the skill
    assert Ledger(project).status_of("REQ-9:land") is StepStatus.DONE


def test_run_only_isolates_req(project):
    """REQ-026 AC5: `run(only=REQ-X)` drives only REQ-X's steps to completion and never runs a
    step belonging to another eligible REQ."""
    xd = Step(id="REQ-X:design", command="/advance REQ-X design", verify=(), req="REQ-X")
    xb = Step(id="REQ-X:build", command="/advance REQ-X build",
              depends_on=("REQ-X:design",), verify=(), req="REQ-X")
    y = Step(id="REQ-Y:design", command="/advance REQ-Y design", verify=(), req="REQ-Y")
    ex = _executor(project, [xd, xb, y], FakeRunner(default=ok_result()))

    results = ex.run(only="REQ-X")
    assert [r.step.id for r in results] == ["REQ-X:design", "REQ-X:build"]
    led = Ledger(project)
    assert led.status_of("REQ-X:build") is StepStatus.DONE
    assert led.status_of("REQ-Y:design") is StepStatus.PENDING  # the other REQ never ran


def test_advance_only_targets_named_req(project):
    """REQ-026 AC6: `advance_once(only=REQ-X)` runs REQ-X's next step even when a lower-id REQ
    is also eligible."""
    low = Step(id="REQ-001:design", command="/advance REQ-001 design", verify=(), req="REQ-001")
    high = Step(id="REQ-009:design", command="/advance REQ-009 design", verify=(), req="REQ-009")
    ex = _executor(project, [low, high], FakeRunner(default=ok_result()))

    res = ex.advance_once(only="REQ-009")
    assert res.step.id == "REQ-009:design"
    led = Ledger(project)
    assert led.status_of("REQ-009:design") is StepStatus.DONE
    assert led.status_of("REQ-001:design") is StepStatus.PENDING  # lower-id REQ skipped


class _CountingStop:
    """A StopController stand-in: ``should_stop`` returns False for the first ``stop_after``
    calls, then True — so the run loop completes one step before the flag trips."""

    def __init__(self, stop_after: int):
        self.n = 0
        self.stop_after = stop_after

    def should_stop(self) -> bool:
        self.n += 1
        return self.n > self.stop_after

    def register_child(self, proc) -> None:
        pass

    def clear_child(self) -> None:
        pass


def test_graceful_stop_after_current_step(project, monkeypatch):
    """REQ-025 AC9: one stop request lets the current step finish, then the loop exits without
    starting the next; the StopController's 1st SIGINT sets the flag, the 2nd kills the child."""
    a = Step(id="REQ-A:design", command="/advance REQ-A design", verify=())
    b = Step(id="REQ-B:design", command="/advance REQ-B design", verify=())
    ex = Executor(
        root=project,
        source=ListStepSource([a, b]),
        verifier=CommandVerifier(cwd=str(project)),
        accounts=SingleAccountProvider(),
        runner=FakeRunner(default=ok_result()),
        committer=RecordingCommitter(),
        stop=_CountingStop(stop_after=1),
        git=FakeGitTopology(),
    )
    results = ex.run()
    assert [r.step.id for r in results] == ["REQ-A:design"]  # only the first step ran
    assert results[0].outcome is RunOutcome.DONE
    led = Ledger(project)
    assert led.status_of("REQ-A:design") is StepStatus.DONE
    assert led.status_of("REQ-B:design") is StepStatus.PENDING  # never started

    # The controller itself: 1st SIGINT sets the flag; 2nd kills the child group and exits 130.
    from devsteward.core import stop as stop_mod

    ctrl = stop_mod.StopController()
    ctrl._on_sigint()
    assert ctrl.should_stop()

    killed: list = []
    monkeypatch.setattr(stop_mod.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(stop_mod.os, "killpg", lambda pg, sig: killed.append(pg))
    ctrl.register_child(SimpleNamespace(pid=4242, poll=lambda: None))
    with pytest.raises(SystemExit) as exc:
        ctrl._on_sigint()
    assert exc.value.code == 130
    assert killed == [4242]


# -- REQ-059: self-healing sweep + honest ineligibility -----------------------


def test_stranded_running_swept_to_pending_on_run(project):
    """REQ-059 AC1: a step stranded RUNNING by an interrupted prior run (a `step_started`
    with no terminal event) self-heals on the next run — the sweep requeues it to PENDING and
    appends an `interrupted` event naming it *before* selecting work, so the run then drives
    it to DONE with no hand-edit of state.yaml."""
    step = Step(id="REQ-9:develop", command="/advance REQ-9 develop",
                verify=("true",), req="REQ-9")
    ex = _executor(project, [step], FakeRunner(default=ok_result()))
    # Strand it: RUNNING with a step_started but no terminal event (the SIGINT window).
    ex.ledger.set_status("REQ-9:develop", StepStatus.RUNNING)
    ex.ledger.save()
    ex.ledger.append_event("step_started", step="REQ-9:develop",
                           command="/advance REQ-9 develop", recover=False)

    results = ex.run()

    led = Ledger(project)
    assert led.status_of("REQ-9:develop") is StepStatus.DONE  # requeued, then driven to done
    assert [r.step.id for r in results] == ["REQ-9:develop"]
    kinds = [e["event"] for e in led.events() if e.get("step") == "REQ-9:develop"]
    assert "interrupted" in kinds
    # The reconcile fired before the run re-started the step (and before its land).
    assert kinds.index("interrupted") < kinds.index("checkpoint")
    interrupted = [e for e in led.events() if e["event"] == "interrupted"]
    assert interrupted[-1]["requeued"] == "pending"


def test_stranded_running_recover_preserves_signal(project):
    """REQ-059 AC2: a step stranded out of RECOVER (an interrupted `steward repeat` re-arm,
    whose last `step_started` carries recover:true) requeues to RECOVER — not PENDING — so the
    driven re-run issues its develop command with --repeat and the partial work in the tree is
    assessed rather than restarted clean."""
    step = Step(id="REQ-9:develop", command="/advance REQ-9 develop",
                verify=("true",), req="REQ-9")
    runner = FakeRunner(default=ok_result())
    ex = _executor(project, [step], runner)
    # Strand a *recovering* attempt: RECOVER → run_step flipped it RUNNING and wrote
    # step_started recover=True, then a SIGINT killed it before any terminal event.
    ex.ledger.set_status("REQ-9:develop", StepStatus.RUNNING)
    ex.ledger.save()
    ex.ledger.append_event("step_started", step="REQ-9:develop",
                           command="/advance REQ-9 develop --repeat", recover=True)

    ex.run()

    # The sweep must not downgrade it to a clean restart: it requeued to RECOVER.
    interrupted = [e for e in Ledger(project).events() if e["event"] == "interrupted"]
    assert interrupted[-1]["requeued"] == "recover"
    # ...so the driven re-run carries the resume signal to the skill.
    assert "--repeat" in runner.calls[-1]["command"]


def test_only_ineligibility_names_real_cause(project):
    """REQ-059 AC3: only_ineligibility_reason names the real obstruction and never fabricates
    a dependency — a RUNNING strand is named as interrupted, a BLOCKED step as parked (never a
    dependency block), and the unfinished-dependency message is returned only when a
    depends_on entry is genuinely not DONE, naming that dependency."""
    # (a) RUNNING strand → named as interrupted, not a dependency block.
    running = Step(id="REQ-R:develop", command="/advance REQ-R develop", req="REQ-R")
    ex = _executor(project, [running], FakeRunner(default=ok_result()))
    ex.ledger.set_status("REQ-R:develop", StepStatus.RUNNING)
    ex.ledger.save()
    msg = ex.only_ineligibility_reason("REQ-R")
    assert "REQ-R:develop" in msg and "RUNNING" in msg
    assert "dependency" not in msg

    # (b) BLOCKED → named as parked (a fork, with its decide verb) or held (REQ-074),
    # never a dependency block.
    blocked = Step(id="REQ-B:develop", command="/advance REQ-B develop", req="REQ-B")
    ex = _executor(project, [blocked], FakeRunner(default=ok_result()))
    ex.ledger.park_decision(Decision(
        id=ex.ledger.next_decision_id(), step="REQ-B:develop", req="REQ-B",
        question="fork?",
    ))
    msg = ex.only_ineligibility_reason("REQ-B")
    assert "parked" in msg and "steward decide DEC-001" in msg
    assert "dependency" not in msg
    held = Step(id="REQ-H:develop", command="/advance REQ-H develop", req="REQ-H")
    ex_h = _executor(project, [held], FakeRunner(default=ok_result()))
    ex_h.ledger.set_hold("REQ-H:develop", "awaits the human oracle")
    ex_h.ledger.save()
    msg_h = ex_h.only_ineligibility_reason("REQ-H")
    assert "held" in msg_h and "human oracle" in msg_h and "dependency" not in msg_h

    # (c) a genuinely unfinished dependency → the dependency block message, naming the dep.
    # REQ-X:develop depends on REQ-W:develop, which is not DONE (PENDING), and REQ-X has no
    # other eligible step — so --only REQ-X selects nothing for a real dependency reason.
    dep = Step(id="REQ-W:develop", command="/advance REQ-W develop", req="REQ-W")
    blocked_by_dep = Step(id="REQ-X:develop", command="/advance REQ-X develop",
                          depends_on=("REQ-W:develop",), req="REQ-X")
    ex = _executor(project, [dep, blocked_by_dep], FakeRunner(default=ok_result()))
    assert ex.next_eligible(only="REQ-X") is None  # the dep gates it
    msg = ex.only_ineligibility_reason("REQ-X")
    assert "unfinished dependency" in msg and "REQ-W:develop" in msg
