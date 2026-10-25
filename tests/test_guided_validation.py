"""REQ-034 — human validation as a guided, asynchronous activity.

The manual-AC half of the System-Test phase (REQ-030) reworked: a guided interactive
session (the editor pattern — TTY inherited, foreground wait, never claude -p), a two-phase
``start``/``record`` bookkeeping a mid-session skill can call (Claude never spawned from
within Claude), an async QA-ticket park that does not freeze the project, clean
reconcile-on-resume, and the three terminal outcomes routed.

Wired like ``test_system_test_phase.py`` (the REQ profile's real source/verifier/flipper/
land-gate/validate-routine) plus an injected *interactive* runner standing in for the
foreground bring-up — so shape A is exercised without a real claude or a TTY.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome, StepResult
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.profiles.req import ReqStepSource
from devsteward.profiles.req.checkpoint import PlanArtifactGate, ReqDoneFlipper
from devsteward.profiles.req.reqfile import parse_req
from devsteward.profiles.req.validate import ReqValidateRoutine, Signoff
from devsteward.profiles.req.verify import ReqVerifier

from conftest import FakeGitTopology, write_index
from test_system_test_phase import (
    SystemTesterRunner,
    _events,
    _project,
    _validation_events,
    _write_plan,
    _write_req,
    _REGRESSION,
    _ARTIFACT_OK,
    _MANUAL,
)


@pytest.fixture(autouse=True)
def _plain_shell(monkeypatch):
    """Shape A is the *plain shell* scenario — ensure CLAUDECODE is unset so the nesting
    guard does not refuse (the suite itself may run inside a Claude session). The nesting
    test re-sets it explicitly."""
    monkeypatch.delenv("CLAUDECODE", raising=False)


class FakeInteractiveRunner:
    """Stand-in for :func:`devsteward.core.claude.run_claude_interactive` — the foreground
    guided bring-up (REQ-034 D6). Records each call (so a test can prove the session was
    brought up *interactively*, not via ``claude -p``), optionally captures an artifact the
    guided session would have produced, and returns exit code 0."""

    def __init__(self, root: Path, artifact: str | None = None, content: str = "observed\n"):
        self.root = Path(root)
        self.artifact = artifact
        self.content = content
        self.calls: list[dict] = []

    def __call__(self, command, *, argv_prefix=None, cwd=None, env=None,
                 model=None, effort=None):
        self.calls.append({"command": command, "model": model, "argv_prefix": argv_prefix})
        if self.artifact and "--evidence" in command:
            rel = command.split("--evidence", 1)[1].split()[0]
            p = self.root / rel / self.artifact
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(self.content, encoding="utf-8")
        return 0


def _executor(root, *, runner=None, interactive_runner=None, git=None):
    req_dir = root / "docs" / "requirements"
    return Executor(
        # REQ-091: a spawn names its model; an unconfigured headless spawn refuses.
        model="test-spawn-model",
        root=root,
        source=ReqStepSource(req_dir),
        verifier=ReqVerifier(cwd=str(root), full_suite=None),
        accounts=SingleAccountProvider(),
        runner=runner or SystemTesterRunner(root),
        interactive_runner=interactive_runner or FakeInteractiveRunner(root),
        git=git or FakeGitTopology(current="dev"),
        on_verified=ReqDoneFlipper(req_dir, req_dir / "REQUIREMENTS_INDEX.md"),
        land_gate=PlanArtifactGate(root / "docs" / "plans"),
        step_claude={"develop": ("claude-opus-4-8", "high"),
                     "repair": ("claude-sonnet-4-6", "high"),
                     "validate": ("claude-opus-4-8", "high")},
        validate_runner=ReqValidateRoutine(req_dir),
    )


def _approve(ac):
    return Signoff(approved=True, reviewer="Petra", scope="reviewed the proof run")


def _decline(ac):
    return Signoff(approved=False, reviewer="Petra")


def _defer(ac):
    return Signoff(approved=False, reviewer="", deferred=True)


# -- AC1 ------------------------------------------------------------------------


def test_shell_validate_wraps_interactive_session_two_phase(tmp_path):
    """`steward validate` runs the two-phase bookkeeping around an *interactive* session:
    prep (evidence dir, RUNNING, branch ready) → foreground bring-up (TTY, not claude -p) →
    record (engine artifact gate + the human verdict). The verdict is engine-recorded; the
    session cannot self-certify (a declining verdict does not land)."""
    _project(tmp_path, [_REGRESSION, _ARTIFACT_OK, _MANUAL])
    headless = SystemTesterRunner(tmp_path)            # the develop session's fake claude -p
    interactive = FakeInteractiveRunner(tmp_path, artifact="capture.txt")
    git = FakeGitTopology(current="dev")
    ex = _executor(tmp_path, runner=headless, interactive_runner=interactive, git=git)
    ex.advance_once(only="REQ-001")                    # develop → deferred, on feature branch

    step = ex.step_by_id("REQ-001:validate")
    res = ex.validate_runner.guided_validate(ex, step, signoff=_approve, driver="interactive")

    # the guided session was brought up once, in the foreground, with the evidence dir —
    # and via the *interactive* bring-up, never as a headless `claude -p /system-test`.
    assert len(interactive.calls) == 1
    cmd = interactive.calls[0]["command"]
    assert cmd.startswith("/system-test REQ-001 --evidence ") and "--guided" in cmd
    assert not any("/system-test" in c["command"] for c in headless.calls)

    # the engine ran the artifact gate itself and recorded the evidence + the human verdict
    (ev,) = _validation_events(tmp_path)
    assert ev["ok"] is True
    assert any(r["ac"] == "AC2" and r["check"] == "artifact" and r["ok"] for r in ev["results"])
    (so,) = ev["signoffs"]
    assert so["reviewer"] == "Petra" and so["approved"] is True
    assert res.outcome is RunOutcome.DONE
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "done"
    assert git.current == "dev"  # REQ-048: lands on dev, no merge

    # cannot self-certify: a declining verdict (even with a captured artifact) does not land
    other = tmp_path / "declined"
    other.mkdir()
    _project(other, [_REGRESSION, _ARTIFACT_OK, _MANUAL])
    ex2 = _executor(other, interactive_runner=FakeInteractiveRunner(other, artifact="c.txt"),
                    git=FakeGitTopology(current="dev"))
    ex2.advance_once(only="REQ-001")
    res2 = ex2.validate_runner.guided_validate(
        ex2, ex2.step_by_id("REQ-001:validate"), signoff=_decline)
    assert res2.outcome is RunOutcome.PARKED
    assert parse_req(other / "docs/requirements/REQ-001.md").status == "open"


# -- AC2 ------------------------------------------------------------------------


def test_in_session_start_record_and_nesting_refusal(tmp_path, monkeypatch):
    """The two-phase bookkeeping is invocable as discrete start/record steps a mid-session
    skill calls (no new Claude spawned), and the bring-up refuses when run inside a Claude
    session (CLAUDECODE set)."""
    _project(tmp_path, [_REGRESSION, _MANUAL])
    interactive = FakeInteractiveRunner(tmp_path)
    ex = _executor(tmp_path, interactive_runner=interactive, git=FakeGitTopology(current="dev"))
    ex.advance_once(only="REQ-001")                    # develop → deferred, on feature branch

    routine = ex.validate_runner
    step = ex.step_by_id("REQ-001:validate")

    # shape B: start() then record() — the skill drove the guided work in-session itself
    ctx = routine.start(ex, step)
    assert not isinstance(ctx, StepResult)
    assert ctx.evidence_dir.is_dir()
    assert ex.ledger.status_of("REQ-001:validate") is StepStatus.RUNNING
    res = routine.record(ex, ctx, signoff=_approve, driver="interactive")
    assert res.outcome is RunOutcome.DONE
    assert interactive.calls == []                     # no new Claude spawned mid-session
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "done"

    # the bring-up refuses inside a Claude session, pointing at a plain terminal / the skill
    monkeypatch.setenv("CLAUDECODE", "1")
    refusal = ex.bring_up_guided_session(step, "evidence/x")
    assert isinstance(refusal, str)
    assert "CLAUDECODE" in refusal and "plain terminal" in refusal
    assert interactive.calls == []                     # still never spawned


# -- AC3 ------------------------------------------------------------------------


def test_pending_validation_parks_async_nonblocking(tmp_path):
    """A pending verdict parks as an async QA-ticket: clean tree on dev (REQ-048), the REQ
    unlanded — and a subsequent run advances an independent REQ (the waiting human does not
    freeze the pipeline)."""
    req_dir = tmp_path / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", [_REGRESSION, _MANUAL])
    _write_req(req_dir, "REQ-002", [_REGRESSION])
    write_index(req_dir, [("REQ-001", "t", "OPEN", "–"), ("REQ-002", "t", "OPEN", "–")])
    _write_plan(tmp_path, "REQ-001", "REQ-002")
    Ledger.init(tmp_path)
    git = FakeGitTopology(current="dev")
    ex = _executor(tmp_path, git=git)
    ex.advance_once(only="REQ-001")                    # develop REQ-001 → deferred commit

    step = ex.step_by_id("REQ-001:validate")
    res = ex.validate_runner.guided_validate(ex, step, signoff=_defer)
    assert res.outcome is RunOutcome.PARKED

    assert git.current == "dev"                         # never leaves dev
    assert parse_req(req_dir / "REQ-001.md").status == "open"  # unlanded on a park
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:validate") is StepStatus.BLOCKED
    # REQ-074: the async QA wait is a hold naming its verb, not a decision.
    assert led.open_decisions() == []
    hold = led.hold_note("REQ-001:validate")
    assert "pending" in hold and "REQ-001" in hold

    # the pipeline is not frozen — a subsequent run advances the independent REQ-002
    ex.run()
    assert parse_req(req_dir / "REQ-002.md").status == "done"


# -- AC4 ------------------------------------------------------------------------


def test_parked_validation_resumes_then_lands(tmp_path):
    """A parked (deferred) validation cleanly resumes and a green verdict fires the deferred
    mechanical land — all on dev (REQ-048: trunk-based, no branch to reconcile)."""
    _project(tmp_path, [_REGRESSION, _MANUAL])
    git = FakeGitTopology(current="dev")
    ex = _executor(tmp_path, git=git)
    ex.advance_once(only="REQ-001")                    # develop → deferred commit
    step = ex.step_by_id("REQ-001:validate")

    # first attempt: the human defers → async park
    ex.validate_runner.guided_validate(ex, step, signoff=_defer)
    assert git.current == "dev"
    assert ex.ledger.status_of("REQ-001:validate") is StepStatus.BLOCKED

    # resume: the green verdict fires the deferred land, still on dev
    res = ex.validate_runner.guided_validate(
        ex, ex.step_by_id("REQ-001:validate"), signoff=_approve)
    assert res.outcome is RunOutcome.DONE
    assert git.current == "dev"
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "done"


# -- AC5 ------------------------------------------------------------------------


def _run_guided(tmp_path, name, signoff_fn):
    root = tmp_path / name
    root.mkdir()
    _project(root, [_REGRESSION, _MANUAL])
    git = FakeGitTopology(current="dev")
    ex = _executor(root, interactive_runner=FakeInteractiveRunner(root), git=git)
    ex.advance_once(only="REQ-001")
    res = ex.validate_runner.guided_validate(
        ex, ex.step_by_id("REQ-001:validate"), signoff=signoff_fn)
    return root, git, res


def test_human_validation_terminal_outcomes_clean_tree(tmp_path):
    """The three terminal outcomes route correctly and each stays on dev (REQ-048): green →
    mechanical land; declined → red park whose message points at `steward rework`; pending →
    async park — and no land on any park."""
    # green → land
    root, git, res = _run_guided(tmp_path, "green", _approve)
    assert res.outcome is RunOutcome.DONE
    assert parse_req(root / "docs/requirements/REQ-001.md").status == "done"
    assert git.current == "dev"

    # declined → red park pointing at `steward rework`, no land, on dev
    root, git, res = _run_guided(tmp_path, "declined", _decline)
    assert res.outcome is RunOutcome.PARKED
    assert "steward rework" in res.detail
    # REQ-074: the red validation is a hold naming both return edges, not a decision.
    led_red = Ledger(root)
    assert led_red.open_decisions() == []
    hold_red = led_red.hold_note("REQ-001:validate")
    assert "steward rework" in hold_red and "validation red" in hold_red
    assert git.current == "dev"
    assert parse_req(root / "docs/requirements/REQ-001.md").status == "open"

    # pending → async park, no land, on dev
    root, git, res = _run_guided(tmp_path, "pending", _defer)
    assert res.outcome is RunOutcome.PARKED
    assert git.current == "dev"
    assert Ledger(root).status_of("REQ-001:validate") is StepStatus.BLOCKED
