"""REQ-074 AC5/AC6 — `steward decide`: the guided attended resolution of a parked fork,
and the delivery of the answered fork into the resuming session's prompt.
"""

from __future__ import annotations

from click.testing import CliRunner

from devsteward.cli import main as cli_main
from devsteward.core import claude as claude_mod
from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Decision, DecisionStatus, Step, StepStatus
from devsteward.core.verify import CommandVerifier

from conftest import (
    FakeGitTopology,
    FakeRunner,
    ListStepSource,
    RecordingCommitter,
    ok_result,
)


def _park_fork(root, *, step="REQ-001:develop"):
    led = Ledger(root)
    led.park_decision(Decision(
        id=led.next_decision_id(), step=step, req=step.split(":", 1)[0],
        question="Which database engine?",
        options=["sqlite", "postgres"],
        recommendation="sqlite",
        context="both fit; migration differs",
    ))
    return led


def _cli_project(tmp_path, monkeypatch):
    from test_transaction_boundary import _init_git, _scaffold

    _scaffold(tmp_path, acs=(("AC1", "true", "regression"),))
    _init_git(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("DEVSTEWARD_UNATTENDED", raising=False)


# -- AC5 ---------------------------------------------------------------------------


def test_decide_refuses_claude_and_unattended(tmp_path, monkeypatch):
    """`steward decide` is attended-only: it refuses inside a Claude session (CLAUDECODE)
    and under DEVSTEWARD_UNATTENDED=1, leaving the fork parked and the step BLOCKED."""
    _cli_project(tmp_path, monkeypatch)
    _park_fork(tmp_path)

    inside = CliRunner().invoke(
        cli_main, ["decide", "DEC-001"], env={"CLAUDECODE": "1"}
    )
    assert inside.exit_code != 0
    assert "never spawned from within Claude" in inside.output

    unattended = CliRunner().invoke(
        cli_main, ["decide", "DEC-001"], env={"DEVSTEWARD_UNATTENDED": "1"}
    )
    assert unattended.exit_code != 0
    assert "attended" in unattended.output

    led = Ledger(tmp_path)
    (dec,) = led.open_decisions()
    assert dec.status is DecisionStatus.OPEN
    assert led.status_of("REQ-001:develop") is StepStatus.BLOCKED


def test_decide_records_choice_and_unblocks(tmp_path, monkeypatch):
    """The guided session briefs (spawned with the fork brief); the engine records the
    operator's numbered choice + rationale afterward and unblocks the step — and never
    resurrects a step a concurrent land already carried to DONE (REQ-073 replay rule)."""
    _cli_project(tmp_path, monkeypatch)
    _park_fork(tmp_path)

    prompts: list[str] = []

    def fake_interactive(command, *, argv_prefix=None, cwd=None, env=None,
                         model=None, effort=None):
        prompts.append(command)
        return 0

    monkeypatch.setattr(claude_mod, "run_claude_interactive", fake_interactive)

    res = CliRunner().invoke(cli_main, ["decide", "DEC-001"], input="1\nlocal cache\n")
    assert res.exit_code == 0, res.output
    # The guided session was briefed, and told not to self-certify.
    (prompt,) = prompts
    assert "Which database engine?" in prompt
    assert "sqlite" in prompt and "postgres" in prompt
    assert "recommendation" in prompt.lower()
    assert "engine records the operator" in prompt

    led = Ledger(tmp_path)
    d = led.find_decision("DEC-001")
    assert d.status is DecisionStatus.ANSWERED
    assert d.answer == "sqlite"  # option 1 resolved to its text
    assert d.rationale == "local cache"
    assert led.status_of("REQ-001:develop") is StepStatus.PENDING

    # A DONE step is never resurrected by a late decide.
    led.set_status("REQ-001:develop", StepStatus.DONE)
    led.save()
    _park_fork(tmp_path)  # DEC-002, blocks the step again — then a land wins the race
    led2 = Ledger(tmp_path)
    led2.set_status("REQ-001:develop", StepStatus.DONE)
    led2.save()
    res2 = CliRunner().invoke(cli_main, ["decide", "DEC-002"], input="2\n\n")
    assert res2.exit_code == 0, res2.output
    final = Ledger(tmp_path)
    assert final.find_decision("DEC-002").status is DecisionStatus.ANSWERED
    assert final.status_of("REQ-001:develop") is StepStatus.DONE  # not resurrected


# -- AC6 ---------------------------------------------------------------------------


def test_answered_fork_is_delivered_into_resumed_command(project):
    """The resumed step's command carries the answered fork (question, choice, rationale)
    — the --repair-brief pattern; a step with no answered fork runs its plain command."""
    step = Step(id="REQ-A:develop", command="/advance REQ-A develop", req="REQ-A")
    led = Ledger(project)
    led.park_decision(Decision(
        id=led.next_decision_id(), step="REQ-A:develop", req="REQ-A",
        question="Which database engine?", options=["sqlite", "postgres"],
    ))
    led.answer_decision("DEC-001", "sqlite", rationale="local cache, zero ops")

    runner = FakeRunner(default=ok_result())
    ex = Executor(
        root=project,
        source=ListStepSource([step]),
        verifier=CommandVerifier(cwd=str(project)),
        accounts=SingleAccountProvider(),
        runner=runner,
        committer=RecordingCommitter(),
        git=FakeGitTopology(),
    )
    res = ex.run_step(step, unattended=True)
    assert res.outcome is RunOutcome.DONE
    command = runner.calls[-1]["command"]
    assert command.startswith("/advance REQ-A develop")
    assert "Which database engine?" in command
    assert "Choice: sqlite" in command
    assert "Rationale: local cache, zero ops" in command
    assert "do not re-open the fork" in command

    # A foreign/undecided step's command is untouched.
    other = Step(id="REQ-B:develop", command="/advance REQ-B develop", req="REQ-B")
    ex2 = Executor(
        root=project,
        source=ListStepSource([other]),
        verifier=CommandVerifier(cwd=str(project)),
        accounts=SingleAccountProvider(),
        runner=runner,
        committer=RecordingCommitter(),
        git=FakeGitTopology(),
    )
    ex2.run_step(other, unattended=True)
    assert runner.calls[-1]["command"] == "/advance REQ-B develop"
