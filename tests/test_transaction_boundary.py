"""REQ-049 — the universal transaction boundary + central invariants.

Real-git teeth (the plan-0021 lesson: a fake can't certify rollback). A throwaway ``git
init`` repo on ``dev``, only ``claude`` faked (``FakeRunner``); the executor commits for real
and the assertions read real git state.

* **AC2** — an injected git failure mid-mutation leaves the repo + ledger byte-identical to
  the pre-command snapshot and surfaces a :class:`RecoverableError` (no raw
  ``CalledProcessError``, no half-state).
* **AC3** — ``steward decision`` and the recovery verbs succeed regardless of HEAD: the
  central invariants exempt them from the branch/tree gate (INV-1 only), so a parked decision
  can never strand on the "wrong branch".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from devsteward.cli import main as cli_main
from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.errors import PreconditionError, RecoverableError
from devsteward.core.executor import Executor
from devsteward.core.git import GitCli
from devsteward.core.invariants import check_invariants
from devsteward.core.ledger import Ledger
from devsteward.core.model import Decision, Step, StepStatus
from devsteward.profiles.req import ReqStepSource
from devsteward.profiles.req.checkpoint import PlanArtifactGate, ReqDoneFlipper
from devsteward.profiles.req.verify import ReqVerifier

from conftest import FakeRunner, ok_result


# -- scaffold ------------------------------------------------------------------


def _write_req(req_dir: Path, rid: str, acs, *, status="open"):
    req_dir.mkdir(parents=True, exist_ok=True)
    items = "".join(
        f"- id: {aid}\n"
        f"  text: {aid} holds.\n"
        f'  test: "{test}"\n'
        f"  check: {check}\n"
        f"  status: pending\n"
        for aid, test, check in acs
    )
    (req_dir / f"{rid}.md").write_text(
        f"---\n"
        f"id: {rid}\n"
        f'title: "{rid} title"\n'
        f"status: {status}\n"
        f"kind: feature\n"
        f"added: 2026-06-19\n"
        f"completed: null\n"
        f"verified_by: null\n"
        f"depends_on: []\n"
        f"concept_refs: []\n"
        f"scenario_refs: []\n"
        f"supersedes: null\n"
        f"tags: []\n"
        f"---\n\n"
        f"## Context\n\n{rid} context.\n\n"
        f"## Requirement\n\nDo the thing.\n\n"
        "```yaml acceptance\n" + items + "```\n\n"
        f"## Notes\n\nNone.\n",
        encoding="utf-8",
    )


def _index(req_dir: Path, *rows):
    lines = [
        "# Requirements Index", "",
        "| ID | Title | Status | File | Depends on |",
        "|----|-------|--------|------|------------|",
    ]
    for rid, status in rows:
        lines.append(f"| {rid} | {rid} title | {status} | [{rid}]({rid}.md) | – |")
    (req_dir / "REQUIREMENTS_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _scaffold(root: Path, *, acs=(("AC1", "true", "regression"),)):
    req_dir = root / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", list(acs))
    _index(req_dir, ("REQ-001", "OPEN"))
    plans = root / "docs" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "0001-plan.md").write_text("# Plan 0001\n\nCovers REQ-001.\n", encoding="utf-8")
    # A `single` account provider so build_executor (the CLI path) never reaches for cswap.
    (root / ".devsteward").mkdir(parents=True, exist_ok=True)
    (root / ".devsteward" / "config.yaml").write_text(
        "accounts:\n  provider: single\n", encoding="utf-8"
    )
    Ledger.init(root, profile="req")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _init_git(root: Path, branch: str = "dev") -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "boundary@devsteward.test")
    _git(root, "config", "user.name", "DevSteward Boundary Test")
    _git(root, "checkout", "-q", "-b", branch)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "scaffold")


def _head(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").strip()


def _porcelain(root: Path) -> str:
    return _git(root, "status", "--porcelain").strip()


def _executor(root: Path, *, git=None, runner=None) -> Executor:
    req_dir = root / "docs" / "requirements"
    return Executor(
        root=root,
        source=ReqStepSource(req_dir),
        verifier=ReqVerifier(cwd=str(root), full_suite=None),
        accounts=SingleAccountProvider(),
        runner=runner or FakeRunner(default=ok_result()),
        on_verified=ReqDoneFlipper(req_dir, req_dir / "REQUIREMENTS_INDEX.md"),
        land_gate=PlanArtifactGate(root / "docs" / "plans"),
        production_branch="main",
        integration_branch="dev",
        git=git if git is not None else GitCli(root),
    )


# -- AC2 -----------------------------------------------------------------------


class _FailingGitCli(GitCli):
    """A real :class:`GitCli` that raises on the Nth ``git commit`` — an injected
    mid-mutation failure. ``reset``/``rev-parse``/``add`` are untouched, so the boundary's
    own rollback (``git reset --hard``) still works."""

    def __init__(self, root: Path, *, fail_on_commit: int):
        super().__init__(root)
        self.fail_on_commit = fail_on_commit
        self.commit_n = 0

    def _run(self, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        if args and args[0] == "commit":
            self.commit_n += 1
            if self.commit_n == self.fail_on_commit:
                raise subprocess.CalledProcessError(
                    1, ["git", *args], "", "injected commit failure"
                )
        return super()._run(*args, check=check)


def test_injected_failure_rolls_back_byte_identical(tmp_path):
    """AC2: a green develop lands the *code* commit, then the trailing *ledger* commit fails
    mid-mutation. The boundary restores the pre-command snapshot — same HEAD, byte-identical
    ledger, clean tree, the REQ never flipped ``done`` — and raises a RecoverableError (with a
    recovery line) chained from the original ``CalledProcessError``, which never escapes."""
    _scaffold(tmp_path)
    _init_git(tmp_path)
    before_head = _head(tmp_path)
    before_events = (tmp_path / ".devsteward" / "events.jsonl").read_bytes()
    before_state = (tmp_path / ".devsteward" / "state.yaml").read_bytes()

    # Fail the *second* commit: the code commit (1) lands the done-flip, then the ledger
    # commit (2) raises — the worst "half-applied" shape absent a boundary.
    git = _FailingGitCli(tmp_path, fail_on_commit=2)
    ex = _executor(tmp_path, git=git)

    with pytest.raises(RecoverableError) as exc:
        ex.advance_once()

    # No raw CalledProcessError escaped — it is chained inside the typed error.
    assert isinstance(exc.value.__cause__, subprocess.CalledProcessError)
    assert exc.value.recovery  # carries the one-line operator recovery
    assert git.commit_n == 2  # the code commit happened, then the ledger commit failed

    # Byte-identical: HEAD, the event log, and the cursor are exactly the pre-command state.
    assert _head(tmp_path) == before_head
    assert (tmp_path / ".devsteward" / "events.jsonl").read_bytes() == before_events
    assert (tmp_path / ".devsteward" / "state.yaml").read_bytes() == before_state
    assert _porcelain(tmp_path) == ""  # no half-state left dirty in the tree

    # The REQ never flipped done — neither in the working tree nor in any commit.
    assert "status: open" in (tmp_path / "docs" / "requirements" / "REQ-001.md").read_text()
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is not StepStatus.DONE
    assert not any(e["event"] == "checkpoint" for e in led.events())


# -- AC3 -----------------------------------------------------------------------


def test_invariants_exempt_recovery_verbs_from_branch_gate(tmp_path):
    """AC3 (the core guarantee): on the production branch the full invariants refuse a
    mutation (INV-2), but ``allow_any_head=True`` enforces only INV-1 — so a recovery/decision
    verb runs regardless of HEAD. There is no 'wrong branch' for it to strand on."""
    _scaffold(tmp_path)
    _init_git(tmp_path, branch="main")  # the production branch
    ex = _executor(tmp_path, git=GitCli(tmp_path))

    # An advancing command would refuse here…
    with pytest.raises(PreconditionError) as exc:
        check_invariants(ex)
    assert "main" in str(exc.value)
    # …but a recovery/decision verb is exempt from the branch gate.
    check_invariants(ex, allow_any_head=True)  # does not raise

    # And the exemption holds with HEAD detached (no branch at all) — regardless of HEAD.
    _git(tmp_path, "checkout", "-q", "--detach")
    check_invariants(ex, allow_any_head=True)  # still does not raise


def test_decision_and_recover_succeed_on_production_branch(tmp_path, monkeypatch):
    """AC3 (end to end): a decision parked on ``dev``, then HEAD moved to the production
    branch, is answered by ``steward decision answer`` — and ``steward recover`` re-arms a
    failed step — both with exit 0, regardless of HEAD. The historical stalemate (a parked
    decision no command could recover) is unreachable."""
    _scaffold(tmp_path)
    _init_git(tmp_path)

    # Park a decision and fail a step on dev, then commit that ledger state.
    led = Ledger(tmp_path)
    led.set_status("REQ-001:develop", StepStatus.FAILED)
    led.park_decision(
        Decision(id="DEC-001", step="REQ-001:develop", question="which db?", req="REQ-001")
    )
    led.save()
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "parked decision + failed step")

    # Move HEAD onto the production branch — historically where recovery stranded.
    _git(tmp_path, "checkout", "-q", "-b", "main")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    # `steward decision answer` succeeds on the production branch (no branch gate).
    answer = runner.invoke(
        cli_main, ["decision", "answer", "DEC-001", "resolved"], catch_exceptions=False
    )
    assert answer.exit_code == 0, answer.output
    led2 = Ledger(tmp_path)
    (dec,) = [d for d in led2.decisions() if d.id == "DEC-001"]
    assert dec.status.value == "answered"
    assert led2.status_of("REQ-001:develop") is StepStatus.PENDING  # decision unblocked it

    # `steward recover` re-arms a failed step on the production branch too. Re-fail it first.
    led2.set_status("REQ-001:develop", StepStatus.FAILED)
    led2.save()
    rec = runner.invoke(cli_main, ["recover", "REQ-001"], catch_exceptions=False)
    assert rec.exit_code == 0, rec.output
    assert Ledger(tmp_path).status_of("REQ-001:develop") is StepStatus.RECOVER

    # Contrast: an *advancing* command (checkpoint) refuses on production — the single
    # top-level handler turns the PreconditionError into a non-zero exit + the recovery line.
    refuse = runner.invoke(cli_main, ["checkpoint", "REQ-001", "develop"])
    assert refuse.exit_code != 0
    assert "recovery:" in refuse.stderr and "main" in refuse.stderr
