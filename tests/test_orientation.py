"""REQ-040 — read commands resolve the live integration-branch ledger, and `steward
checkpoint` refuses an already-done step.

The read-side and idempotency follow-up to REQ-037 (which bound only the *write* paths).
Like ``test_plane_split.py`` the blind spot that hid the live defect was a unit fake that
kept one in-memory ledger and never modelled *which branch* a ``.devsteward/`` read
resolved — so every assertion here runs against a **real** ``git init`` repo with the real
``GitCli`` and a real integration worktree; only ``claude`` is faked. The oracle is real git
state: which branch's ledger the read resolved, and whether a re-checkpoint wrote anything.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from devsteward import cli
from devsteward.cli import main
from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.profiles.req import ReqStepSource
from devsteward.profiles.req.checkpoint import PlanArtifactGate, ReqDoneFlipper
from devsteward.profiles.req.validate import ReqValidateRoutine
from devsteward.profiles.req.verify import ReqVerifier

from conftest import FakeRunner, ok_result


# -- scaffold (mirrors test_plane_split.py: real git, ledger on dev) -----------


def _write_req(req_dir: Path, rid: str, acs):
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
        f"---\nid: {rid}\ntitle: \"{rid} title\"\nstatus: open\nkind: feature\n"
        f"added: 2026-06-15\ncompleted: null\nverified_by: null\ndepends_on: []\n"
        f"concept_refs: []\nscenario_refs: []\nsupersedes: null\ntags: []\n---\n\n"
        f"## Context\n\n{rid} context.\n\n## Requirement\n\nDo it.\n\n"
        "```yaml acceptance\n" + items + "```\n\n## Notes\n\nNone.\n",
        encoding="utf-8",
    )


def _index(req_dir: Path, *rows):
    lines = ["# Requirements Index", "",
             "| ID | Title | Status | File | Depends on |",
             "|----|-------|--------|------|------------|"]
    for rid, status in rows:
        lines.append(f"| {rid} | {rid} title | {status} | [{rid}]({rid}.md) | – |")
    (req_dir / "REQUIREMENTS_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _plan(root: Path, *reqs):
    plans = root / "docs" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "0001-plan.md").write_text(
        "# Plan 0001\n\n" + "\n".join(f"Covers {r}." for r in reqs) + "\n", encoding="utf-8"
    )


def _scaffold(root: Path, *, acs):
    req_dir = root / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", acs)
    _index(req_dir, ("REQ-001", "OPEN"))
    _plan(root, "REQ-001")
    (root / "app.py").write_text("base\n", encoding="utf-8")
    Ledger.init(root, profile="req")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout


def _init_git(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "orient@devsteward.test")
    _git(root, "config", "user.name", "Orientation Test")
    _git(root, "checkout", "-q", "-b", "dev")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "scaffold")


def _branch(root: Path) -> str:
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()


def _dev_head(root: Path) -> str:
    return _git(root, "rev-parse", "dev").strip()


def _dev_events_bytes(root: Path) -> str:
    return _git(root, "show", "dev:.devsteward/events.jsonl")


class _CodeRunner:
    """A FakeRunner whose develop session writes a real code edit, so the deferred
    develop_committed carries a real commit sha (not the no-change ``commit: null``)."""

    def __init__(self, root: Path, code: str = "feature\n"):
        self.root = Path(root)
        self.code = code

    def __call__(self, command, **kwargs):
        if "--evidence" not in command:  # the develop session (not the System Tester)
            (self.root / "app.py").write_text(self.code, encoding="utf-8")
        return ok_result()


def _executor(root: Path, *, runner=None) -> Executor:
    req_dir = root / "docs" / "requirements"
    return Executor(
        root=root,
        source=ReqStepSource(req_dir),
        verifier=ReqVerifier(cwd=str(root), full_suite=None),
        accounts=SingleAccountProvider(),
        runner=runner or FakeRunner(default=ok_result()),
        on_verified=ReqDoneFlipper(req_dir, req_dir / "REQUIREMENTS_INDEX.md"),
        land_gate=PlanArtifactGate(root / "docs" / "plans"),
        validate_runner=ReqValidateRoutine(req_dir),
        production_branch="main",
        integration_branch="dev",
    )


def _run_cli(monkeypatch, tmp_path, args):
    """Invoke a CLI command the way `steward` does — a *fresh* executor per call (the bug
    only shows when each command binds the ledger itself, not via a shared in-memory one)."""
    monkeypatch.setattr(cli, "_load_or_die", lambda: SimpleNamespace())
    monkeypatch.setattr(cli, "build_executor", lambda cfg, **kw: _executor(tmp_path))
    return CliRunner().invoke(main, args)


# -- AC1: read-path binding ----------------------------------------------------


def test_status_reads_live_ledger_from_feature_branch_realgit(tmp_path, monkeypatch):
    """On a real repo with the ledger on dev, from a feature branch whose branch-cut
    .devsteward/state.yaml is stale (dev has since advanced — a cursor/step the feature
    snapshot lacks), `steward status` reports the LIVE dev cursor and step status, not the
    stale feature-branch snapshot."""
    _scaffold(tmp_path, acs=[("AC1", "true", "artifact")])  # artifact ⇒ deferred + feature branch
    _init_git(tmp_path)
    ex = _executor(tmp_path)

    r1 = ex.advance_once()  # develop defers onto a feature branch; the ledger advances on dev
    assert r1.outcome is RunOutcome.DONE
    feature = _branch(tmp_path)
    assert feature != "dev"

    # Teeth: the on-disk (feature branch) snapshot is genuinely stale — it has no record of
    # the develop step, while dev's live ledger marks it done.
    stale = (tmp_path / ".devsteward" / "state.yaml").read_text(encoding="utf-8")
    assert "REQ-001:develop" not in stale
    assert Ledger(_dev_worktree(tmp_path)).status_of("REQ-001:develop").value == "done"

    # `steward status`, invoked while HEAD is the feature branch, must report the live cursor.
    result = _run_cli(monkeypatch, tmp_path, ["status"])
    assert result.exit_code == 0, result.output
    assert "cursor: REQ-001:develop" in result.output
    assert "REQ-001:develop" in result.output and "done" in result.output


def _dev_worktree(root: Path) -> Path:
    out = _git(root, "worktree", "list", "--porcelain")
    path = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.strip() == "branch refs/heads/dev" and path and Path(path) != root:
            return Path(path)
    raise AssertionError("no dev worktree found")


# -- AC2: checkpoint idempotency guard -----------------------------------------


def test_checkpoint_refuses_already_done_step_realgit(tmp_path, monkeypatch):
    """`steward checkpoint REQ-001 develop` on a step already at status done refuses with a
    non-zero, actionable message and makes ZERO ledger writes — events.jsonl byte-unchanged
    and no new ledger commit on dev."""
    _scaffold(tmp_path, acs=[("AC1", "true", "artifact")])  # deferred develop stays done while REQ open
    _init_git(tmp_path)
    ex = _executor(tmp_path)

    r1 = ex.advance_once()  # develop done (deferred); REQ-001 still open with a pending validate
    assert r1.outcome is RunOutcome.DONE

    events_before = _dev_events_bytes(tmp_path)
    head_before = _dev_head(tmp_path)

    result = _run_cli(monkeypatch, tmp_path, ["checkpoint", "REQ-001", "develop"])
    assert result.exit_code != 0
    assert "already done" in result.output

    # zero ledger writes: events.jsonl byte-unchanged and no new ledger commit on dev
    assert _dev_events_bytes(tmp_path) == events_before
    assert _dev_head(tmp_path) == head_before


# -- AC3: the 2026-06-15 incident cannot recur end-to-end ----------------------


def test_incident_no_duplicate_checkpoint_realgit(tmp_path, monkeypatch):
    """A deferred-land develop step is checkpointed once (its develop_committed lands on
    dev); from the feature branch `steward status` reports it done (the live cursor, not the
    stale snapshot), and a second `steward checkpoint` is refused — so no duplicate
    develop_committed (and no `commit: null` shadow) is appended. Decisions 1 and 3 together."""
    _scaffold(tmp_path, acs=[("AC1", "true", "artifact")])
    _init_git(tmp_path)
    ex = _executor(tmp_path, runner=_CodeRunner(tmp_path))

    r1 = ex.advance_once()  # the single deferred develop checkpoint
    assert r1.outcome is RunOutcome.DONE
    feature = _branch(tmp_path)
    assert feature != "dev"

    committed = [
        ln for ln in _dev_events_bytes(tmp_path).splitlines() if '"develop_committed"' in ln
    ]
    assert len(committed) == 1  # exactly one, with a real commit sha
    assert '"commit": null' not in committed[0]

    # Decision 1: from the feature branch, status sees the live done cursor (not the stale snapshot)
    status = _run_cli(monkeypatch, tmp_path, ["status"])
    assert status.exit_code == 0, status.output
    assert "cursor: REQ-001:develop" in status.output

    # Decision 3: the mis-diagnosed re-run is refused — no second develop_committed appended
    redo = _run_cli(monkeypatch, tmp_path, ["checkpoint", "REQ-001", "develop"])
    assert redo.exit_code != 0
    assert "already done" in redo.output

    committed_after = [
        ln for ln in _dev_events_bytes(tmp_path).splitlines() if '"develop_committed"' in ln
    ]
    assert committed_after == committed  # byte-identical: no duplicate, no commit: null shadow
