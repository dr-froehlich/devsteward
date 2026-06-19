"""REQ-032 — the ledger is always committed: every terminal step outcome leaves a clean
working tree, so a multi-REQ ``steward run`` never lets step N's ledger writes ride inside
step N+1's commits (the mixed-provenance audit-boundary leak).

Unlike the in-memory ``FakeGitTopology`` suites, these tests need a **real git** repo: the
whole oracle is ``git status`` cleanliness, which only a real checkout can show. The
pattern is ``FakeRunner`` (no real ``claude``) over a real ``GitCli`` + real ``ReqVerifier``
in a throwaway repo on the ``dev`` integration branch — the executor commits for real and
the assertions read real git state.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.profiles.req import ReqStepSource
from devsteward.profiles.req.checkpoint import PlanArtifactGate, ReqDoneFlipper
from devsteward.profiles.req.validate import ReqValidateRoutine
from devsteward.profiles.req.verify import ReqVerifier

from conftest import FakeRunner, ok_result, park_result


# -- fixtures ------------------------------------------------------------------


def _write_req(req_dir: Path, rid: str, acs, *, status="open", depends_on=()):
    """A REQ with an explicit AC list ``[(id, test, check), …]``."""
    req_dir.mkdir(parents=True, exist_ok=True)
    deps = "[" + ", ".join(depends_on) + "]"
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
        f"added: 2026-06-11\n"
        f"completed: null\n"
        f"verified_by: null\n"
        f"depends_on: {deps}\n"
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


def _plan(root: Path, *reqs):
    plans = root / "docs" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "0001-plan.md").write_text(
        "# Plan 0001\n\n" + "\n".join(f"Covers {r}." for r in reqs) + "\n",
        encoding="utf-8",
    )


def _scaffold(root: Path, rid="REQ-001", *, acs=(("AC1", "true", "regression"),)):
    """A throwaway project: one REQ + plan + index + an initialized ledger."""
    req_dir = root / "docs" / "requirements"
    _write_req(req_dir, rid, list(acs))
    _index(req_dir, (rid, "OPEN"))
    _plan(root, rid)
    Ledger.init(root, profile="req")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _init_git(root: Path) -> None:
    """A real repo on the ``dev`` integration branch (off ``main``, so commits are allowed),
    with the scaffold committed as the initial state."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "ledger@devsteward.test")
    _git(root, "config", "user.name", "DevSteward Ledger Test")
    _git(root, "checkout", "-q", "-b", "dev")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "scaffold")


def _porcelain(root: Path) -> str:
    return _git(root, "status", "--porcelain").strip()


def _tip_subject(root: Path) -> str:
    return _git(root, "log", "-1", "--format=%s").strip()


def _subjects(root: Path) -> list[str]:
    return _git(root, "log", "--format=%s").splitlines()


def _current_branch(root: Path) -> str:
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()


def _executor(root: Path, *, runner=None, with_validate=False) -> Executor:
    req_dir = root / "docs" / "requirements"
    return Executor(
        root=root,
        source=ReqStepSource(req_dir),
        verifier=ReqVerifier(cwd=str(root), full_suite=None),
        accounts=SingleAccountProvider(),
        runner=runner or FakeRunner(default=ok_result()),
        on_verified=ReqDoneFlipper(req_dir, req_dir / "REQUIREMENTS_INDEX.md"),
        land_gate=PlanArtifactGate(root / "docs" / "plans"),
        validate_runner=ReqValidateRoutine(req_dir) if with_validate else None,
        production_branch="main",
        integration_branch="dev",
    )


# -- AC1 -----------------------------------------------------------------------


def test_batch_land_commits_clean_on_dev(tmp_path):
    """After a green batch land (REQ-048: trunk-based), dev is clean and its tip is the
    trailing ledger commit; the work commit and the cursor advance are two separate commits,
    with no feature branch and no branch_merged event."""
    _scaffold(tmp_path)
    _init_git(tmp_path)
    ex = _executor(tmp_path)

    res = ex.advance_once()
    assert res.outcome is RunOutcome.DONE

    assert _current_branch(tmp_path) == "dev"
    assert _porcelain(tmp_path) == ""  # clean at rest — the whole point
    assert _tip_subject(tmp_path) == "REQ-001: ledger checkpoint"
    # the work commit precedes it and carries no ledger (REQ-048: code commit excludes it)
    assert _subjects(tmp_path)[1] == "REQ-001:develop: REQ-001 title — develop"
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.DONE
    assert not any(e["event"] == "branch_merged" for e in led.events())
    # the checkpoint event is *inside* the committed tip, not dangling in the tree
    assert "checkpoint" in _git(tmp_path, "show", "HEAD:.devsteward/events.jsonl")


def test_dev_only_cycle_no_branch_no_worktree_realgit(tmp_path):
    """REQ-048 AC1: a full develop→land cycle creates no feature branch and spins up no
    worktree — git's own branch and worktree lists show only dev and the repo root."""
    _scaffold(tmp_path)
    _init_git(tmp_path)
    ex = _executor(tmp_path)

    res = ex.advance_once()
    assert res.outcome is RunOutcome.DONE

    # exactly one branch — dev — and exactly one worktree — the repo root.
    branches = [b.lstrip("* ").strip() for b in _git(tmp_path, "branch").splitlines()]
    assert branches == ["dev"]
    worktrees = [
        ln for ln in _git(tmp_path, "worktree", "list", "--porcelain").splitlines()
        if ln.startswith("worktree ")
    ]
    assert len(worktrees) == 1


# -- AC2 -----------------------------------------------------------------------


def test_interactive_checkpoint_commits_clean_on_dev(tmp_path):
    """The same holds for the interactive close (``steward checkpoint``): it lands on dev
    (REQ-048) with a clean tree whose tip is the trailing ledger commit, and a checkpoint
    event marked interactive."""
    _scaffold(tmp_path)
    _init_git(tmp_path)
    ex = _executor(tmp_path)

    res = ex.checkpoint(ex.step_by_id("REQ-001:develop"))
    assert res.outcome is RunOutcome.DONE

    assert _current_branch(tmp_path) == "dev"
    assert _porcelain(tmp_path) == ""
    assert _tip_subject(tmp_path) == "REQ-001: ledger checkpoint"
    led = Ledger(tmp_path)
    assert not any(e["event"] == "branch_merged" for e in led.events())
    (cp,) = [e for e in led.events() if e["event"] == "checkpoint"]
    assert cp["driver"] == "interactive"


# -- AC3 -----------------------------------------------------------------------


def test_deferred_develop_close_commits_trailing_ledger(tmp_path):
    """A deferred develop close (``lands=False`` — a REQ with a validate sibling) commits on
    dev and leaves a clean tree (REQ-048): the work commit, then the trailing ledger commit
    carrying ``develop_committed`` — and no land yet."""
    _scaffold(tmp_path, acs=[("AC1", "true", "artifact")])  # artifact ⇒ validate sibling
    _init_git(tmp_path)
    ex = _executor(tmp_path, with_validate=True)

    res = ex.advance_once()  # the develop step only — it defers, it does not land
    assert res.outcome is RunOutcome.DONE

    assert _current_branch(tmp_path) == "dev"  # never leaves dev
    assert _porcelain(tmp_path) == ""  # clean at rest
    assert _tip_subject(tmp_path) == "REQ-001: ledger checkpoint"
    # the develop_committed event is on dev's committed events.jsonl (not dirty in the tree).
    dev_events = _git(tmp_path, "show", "dev:.devsteward/events.jsonl")
    assert "develop_committed" in dev_events
    # no land yet — no checkpoint event until the validate sibling goes green.
    assert not any(e["event"] == "checkpoint" for e in Ledger(tmp_path).events())


# -- AC4 -----------------------------------------------------------------------


class _EvidenceRunner:
    """A FakeRunner that, for the System Tester session (carrying ``--evidence <dir>``),
    captures a real artifact file — so the red validation has evidence to commit."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.calls: list[str] = []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if "--evidence" in command:
            rel = command.split("--evidence", 1)[1].strip().split()[0]
            d = self.root / rel
            d.mkdir(parents=True, exist_ok=True)
            (d / "capture.txt").write_text("captured evidence\n", encoding="utf-8")
        return ok_result()


def test_red_and_parked_outcomes_commit_ledger_and_evidence(tmp_path):
    """A parked decision and a red in-flight validation each leave the tree clean: the
    park / red event and any captured evidence files are committed before the executor
    returns to the loop."""
    # (a) a parked decision (the develop session raised an unresolved fork)
    park_dir = tmp_path / "parked"
    park_dir.mkdir()
    _scaffold(park_dir)
    _init_git(park_dir)
    ex = _executor(park_dir, runner=FakeRunner(default=park_result("which database?")))

    res = ex.advance_once()
    assert res.outcome is RunOutcome.PARKED
    assert _porcelain(park_dir) == ""  # the parked decision is committed, tree clean
    assert _tip_subject(park_dir) == "REQ-001: ledger close — parked"
    led = Ledger(park_dir)
    assert led.open_decisions()  # the fork is recorded…
    assert "decisions:" in _git(park_dir, "show", "HEAD:.devsteward/state.yaml")  # …committed

    # (b) a red in-flight validation: artifact AC test "false" fails the engine gate, the
    # captured evidence + the red validation event are committed before the park returns.
    val_dir = tmp_path / "red_validation"
    val_dir.mkdir()
    _scaffold(val_dir, acs=[("AC1", "false", "artifact")])
    _init_git(val_dir)
    ex2 = _executor(val_dir, runner=_EvidenceRunner(val_dir), with_validate=True)

    results = ex2.run()  # develop defers + lands; validate runs, goes red, parks
    assert results[-1].outcome is RunOutcome.PARKED
    assert _porcelain(val_dir) == ""
    led2 = Ledger(val_dir)
    (val_event,) = [e for e in led2.events() if e["event"] == "validation"]
    assert val_event["ok"] is False
    # the captured artifact is tracked by git (committed), not left dirty in the tree
    tracked = _git(val_dir, "ls-files").splitlines()
    assert any(t.endswith("capture.txt") for t in tracked)


# -- AC5 -----------------------------------------------------------------------


def test_no_empty_commits_on_no_op_paths(tmp_path):
    """No empty commits: a land on dev makes exactly the code commit + the trailing ledger
    commit (no branch_merged follow-up — REQ-048), and a production-branch refusal commits
    nothing."""
    # (a) a checkpoint on dev: the work commit + the trailing ledger commit, nothing extra —
    # no feature branch to merge, so no branch_merged ledger-close commit is fabricated.
    _scaffold(tmp_path)
    _init_git(tmp_path)
    ex = _executor(tmp_path)
    before = len(_subjects(tmp_path))

    res = ex.checkpoint(ex.step_by_id("REQ-001:develop"))
    assert res.outcome is RunOutcome.DONE
    after = _subjects(tmp_path)
    assert len(after) == before + 2  # the code commit + the ledger checkpoint, nothing extra
    assert not any("ledger close" in s for s in after)  # no branch_merged ledger-close commit
    assert not any(e["event"] == "branch_merged" for e in Ledger(tmp_path).events())

    # (b) a refusal on the production branch writes no commit at all.
    other = tmp_path / "production"
    other.mkdir()
    _scaffold(other)
    _git(other, "init", "-q")
    _git(other, "config", "user.email", "ledger@devsteward.test")
    _git(other, "config", "user.name", "DevSteward Ledger Test")
    _git(other, "checkout", "-q", "-b", "main")  # the production branch
    _git(other, "add", "-A")
    _git(other, "commit", "-q", "-m", "scaffold")
    ex2 = _executor(other)
    n_before = len(_subjects(other))

    res2 = ex2.advance_once()
    assert res2.outcome is RunOutcome.REFUSED
    assert len(_subjects(other)) == n_before  # the engine made no commit on production
