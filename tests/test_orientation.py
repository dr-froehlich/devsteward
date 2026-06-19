"""REQ-040 — `steward checkpoint` refuses an already-done step (idempotency).

REQ-048 made this trunk-based: there is one ledger on ``dev`` and the engine never branches
or spins a worktree, so the old "read the live integration-branch ledger from a *feature
branch*" hazard (REQ-040/041) can no longer arise and those tests retired with the
machinery. What survives is the idempotency guard: a re-checkpoint of an already-done
(deferred) develop step must write nothing. Every assertion runs against a **real** ``git
init`` repo with the real ``GitCli``; only ``claude`` is faked.
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
    # cfg needs root/req_dir: `steward status` reads cfg.root for the REQ-036 skill-drift
    # signal, and other read commands read cfg.req_dir — a bare SimpleNamespace AttributeErrors.
    monkeypatch.setattr(
        cli, "_load_or_die",
        lambda: SimpleNamespace(root=tmp_path, req_dir=tmp_path / "docs" / "requirements"),
    )
    monkeypatch.setattr(cli, "build_executor", lambda cfg, **kw: _executor(tmp_path))
    return CliRunner().invoke(main, args)


# -- checkpoint idempotency guard ----------------------------------------------


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


# -- the 2026-06-15 incident cannot recur (no duplicate checkpoint) ------------


def test_incident_no_duplicate_checkpoint_realgit(tmp_path, monkeypatch):
    """A deferred-land develop step is checkpointed once (its develop_committed lands on
    dev); `steward status` reports it done (the live cursor), and a second `steward
    checkpoint` is refused — so no duplicate develop_committed (and no `commit: null` shadow)
    is appended (REQ-040 Decision 3; trunk-based on dev — REQ-048)."""
    _scaffold(tmp_path, acs=[("AC1", "true", "artifact")])
    _init_git(tmp_path)
    ex = _executor(tmp_path, runner=_CodeRunner(tmp_path))

    r1 = ex.advance_once()  # the single deferred develop checkpoint
    assert r1.outcome is RunOutcome.DONE
    assert _branch(tmp_path) == "dev"  # REQ-048: never leaves dev

    committed = [
        ln for ln in _dev_events_bytes(tmp_path).splitlines() if '"develop_committed"' in ln
    ]
    assert len(committed) == 1  # exactly one, with a real commit sha
    assert '"commit": null' not in committed[0]

    # status reports the live done cursor
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
