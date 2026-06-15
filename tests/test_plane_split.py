"""REQ-037 — the ledger lives on the integration branch only; topology operations are
atomic and recoverable.

The blind spot that hid the live crash was a *unit fake* that kept one in-memory ledger and
never modelled which branch a ``.devsteward/`` commit landed on. So — like plan 0017's
``test_ledger_close`` — every assertion here runs against a **real** ``git init`` repo with
the real ``GitCli``; only ``claude`` (the develop/System-Tester sessions) and the interactive
bring-up are faked. The oracle is real git state: which branch carries the ledger, whether a
merge conflicts, whether an abort restored the repo byte-for-byte.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from devsteward.config import Config
from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.lint import lint
from devsteward.profiles.req import ReqStepSource
from devsteward.profiles.req.checkpoint import PlanArtifactGate, ReqDoneFlipper
from devsteward.profiles.req.validate import ReqValidateRoutine
from devsteward.profiles.req.verify import ReqVerifier

from conftest import FakeRunner, ok_result


# -- scaffold ------------------------------------------------------------------


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


def _scaffold(root: Path, *, acs, app="base\n"):
    req_dir = root / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", acs)
    _index(req_dir, ("REQ-001", "OPEN"))
    _plan(root, "REQ-001")
    (root / "app.py").write_text(app, encoding="utf-8")
    Ledger.init(root, profile="req")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout


def _init_git(root: Path, *, remote: Path | None = None) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "plane@devsteward.test")
    _git(root, "config", "user.name", "Plane Split Test")
    _git(root, "checkout", "-q", "-b", "dev")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "scaffold")
    if remote is not None:
        _git(root, "clone", "-q", "--bare", str(root), str(remote))
        _git(root, "remote", "add", "origin", str(remote))
        _git(root, "push", "-q", "origin", "dev")


def _porcelain(root: Path) -> str:
    return _git(root, "status", "--porcelain").strip()


def _branch(root: Path) -> str:
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()


def _subjects(root: Path) -> list[str]:
    return _git(root, "log", "--format=%s", "dev").splitlines()


def _dev_events(root: Path) -> str:
    return _git(root, "show", "dev:.devsteward/events.jsonl")


def _feature_ledger_diff(root: Path, feature: str) -> str:
    return _git(root, "diff", f"dev...{feature}", "--", ".devsteward").strip()


def _dev_worktree(root: Path) -> Path:
    """The engine's linked worktree currently checked out on ``dev`` (not the main tree)."""
    out = _git(root, "worktree", "list", "--porcelain")
    path = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.strip() == "branch refs/heads/dev" and path and Path(path) != root:
            return Path(path)
    raise AssertionError("no dev worktree found")


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


class _Runner:
    """A FakeRunner that captures an artifact in the System-Tester session (so an artifact
    validate gate has evidence to pass on) and, when ``code`` is given, writes it as the
    develop session's edit (so the feature branch carries a real, conflictable change)."""

    def __init__(self, root: Path, code: str | None = None):
        self.root = Path(root)
        self.code = code

    def __call__(self, command, **kwargs):
        if "--evidence" in command:  # the System-Tester session
            rel = command.split("--evidence", 1)[1].strip().split()[0]
            d = self.root / rel
            d.mkdir(parents=True, exist_ok=True)
            (d / "capture.txt").write_text("captured evidence\n", encoding="utf-8")
        elif self.code is not None:  # the develop session
            (self.root / "app.py").write_text(self.code, encoding="utf-8")
        return ok_result()


# -- AC1 -----------------------------------------------------------------------


def test_green_deferred_land_no_ledger_conflict_realgit(tmp_path):
    """A deferred-validate REQ whose feature branch was cut before dev advanced its ledger
    (the develop_committed write lands on dev *after* the cut — independent histories of
    events.jsonl on dev vs. the cut point) reaches a green land; the feature→dev merge
    completes with no conflict on .devsteward/, dev is clean at rest, and the merge commit
    is present."""
    _scaffold(tmp_path, acs=[("AC1", "true", "artifact")])  # artifact ⇒ validate sibling
    _init_git(tmp_path)
    ex = _executor(tmp_path, runner=_Runner(tmp_path), with_validate=True)

    r1 = ex.advance_once()  # develop defers onto a feature branch; ledger lands on dev
    assert r1.outcome is RunOutcome.DONE
    feature = _branch(tmp_path)
    assert feature != "dev"
    # dev advanced its ledger after the cut (the develop_committed event is on dev, not on the
    # merge base) — the exact "both sides have appended" precondition of the live crash.
    assert "develop_committed" in _dev_events(tmp_path)
    assert _feature_ledger_diff(tmp_path, feature) == ""  # …yet the feature carries no ledger

    r2 = ex.advance_once()  # validate runs green and lands → feature merges into dev
    assert r2.outcome is RunOutcome.DONE
    assert _branch(tmp_path) == "dev"
    assert _porcelain(tmp_path) == ""  # dev clean at rest — no aborted/half merge
    led = Ledger(tmp_path)
    assert any(e["event"] == "branch_merged" for e in led.events())
    assert any(s.startswith(f"Merge {feature} into dev") for s in _subjects(tmp_path))
    assert led.status_of("REQ-001:validate").value == "done"


# -- AC2 -----------------------------------------------------------------------


def test_feature_branch_carries_no_ledger_realgit(tmp_path):
    """After a full develop and a parked (awaiting-oracle) validate on a feature branch,
    `git diff dev...feature -- .devsteward/` is empty, while the develop/validate ledger
    events ARE present on dev's events.jsonl."""
    _scaffold(tmp_path, acs=[("AC1", "true", "regression"), ("AC2", "manual", "manual")])
    _init_git(tmp_path)
    ex = _executor(tmp_path, with_validate=True)

    r1 = ex.advance_once()  # develop (regression green) defers; validate sibling pending
    assert r1.outcome is RunOutcome.DONE
    feature = _git(tmp_path, "branch", "--format=%(refname:short)").split()
    feature = next(b for b in feature if b != "dev")

    r2 = ex.advance_once()  # validate: a pure-manual AC parks awaiting the human oracle
    assert r2.outcome is RunOutcome.PARKED

    assert _feature_ledger_diff(tmp_path, feature) == ""  # pure code on the feature branch
    dev_events = _dev_events(tmp_path)
    assert "develop_committed" in dev_events
    assert '"step": "REQ-001:validate"' in dev_events  # the validate step ran, recorded on dev


# -- AC3 -----------------------------------------------------------------------


def test_conflicting_merge_aborts_and_recovers_realgit(tmp_path):
    """A topology operation that would conflict is atomic and recoverable: a forced code
    conflict aborts, leaving dev byte-identical (same HEAD, clean tree, ledger intact),
    records an actionable recovery instruction, and under unattended parks a decision — never
    an uncaught CalledProcessError."""
    _scaffold(tmp_path, acs=[("AC1", "true", "artifact")])
    _init_git(tmp_path)
    ex = _executor(tmp_path, runner=_Runner(tmp_path, "FEATURE\n"), with_validate=True)

    r1 = ex.advance_once()  # develop writes app.py=FEATURE on the feature branch (deferred)
    assert r1.outcome is RunOutcome.DONE
    feature = _branch(tmp_path)

    # A deploy host / parallel work advances app.py on dev *after* the cut, via the engine's
    # own dev worktree — so the pending feature→dev merge will conflict on app.py.
    wt = _dev_worktree(tmp_path)
    (wt / "app.py").write_text("DEV\n", encoding="utf-8")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "dev advances app.py independently")
    app_before = _git(tmp_path, "show", "dev:app.py")  # dev's own code, pre-merge

    r2 = ex.advance_once()  # validate green → land → merge conflicts → atomic abort + record
    # No uncaught CalledProcessError reached the driver; the aborted merge surfaces as a park.
    assert r2.outcome is RunOutcome.PARKED

    # The merge was atomic: it did not apply (the abort restored the repo), so the feature is
    # unmerged, dev's code is byte-for-byte unchanged, and the tree is clean — never stranded.
    assert _porcelain(tmp_path) == ""
    assert _branch(tmp_path) == "dev"
    assert _git(tmp_path, "show", "dev:app.py") == app_before  # dev code untouched by the abort
    led = Ledger(tmp_path)
    assert not any(e["event"] == "branch_merged" for e in led.events())
    assert "Merge req-001" not in _git(tmp_path, "log", "--format=%s", "dev")
    # The recovery is recorded and a decision is parked (unattended) for the human to resolve.
    aborted = [e for e in led.events() if e["event"] == "merge_aborted"]
    assert aborted and feature in aborted[-1]["detail"]
    assert led.open_decisions() and "conflict" in led.open_decisions()[-1].question.lower()


# -- AC4 -----------------------------------------------------------------------


def test_fetch_first_incorporates_remote_feature_commit_realgit(tmp_path):
    """Fetch-before-merge: when origin/<feature> is ahead of the local feature branch (a
    deploy host pushed a commit), the land fetches and incorporates the remote commit before
    merging, and the landed dev contains it."""
    remote = tmp_path.parent / (tmp_path.name + "-remote.git")
    _scaffold(tmp_path, acs=[("AC1", "true", "artifact")])
    _init_git(tmp_path, remote=remote)
    ex = _executor(tmp_path, runner=_Runner(tmp_path), with_validate=True)

    r1 = ex.advance_once()  # develop defers onto the feature branch
    assert r1.outcome is RunOutcome.DONE
    feature = _branch(tmp_path)
    _git(tmp_path, "push", "-q", "origin", feature)

    # A deploy host clones the remote, commits a live fix on the feature branch, and pushes.
    host = tmp_path.parent / (tmp_path.name + "-host")
    _git(tmp_path.parent, "clone", "-q", str(remote), str(host))
    _git(host, "config", "user.email", "host@devsteward.test")
    _git(host, "config", "user.name", "Deploy Host")
    _git(host, "checkout", "-q", feature)
    (host / "live_fix.txt").write_text("hotfix from the deploy host\n", encoding="utf-8")
    _git(host, "add", "-A")
    _git(host, "commit", "-q", "-m", "deploy-host live fix")
    _git(host, "push", "-q", "origin", feature)

    r2 = ex.advance_once()  # validate land: fetch-first incorporates the remote commit
    assert r2.outcome is RunOutcome.DONE
    assert _branch(tmp_path) == "dev"
    # the deploy host's commit is now on dev (fetched, fast-forwarded, then merged).
    assert "deploy-host live fix" in _git(tmp_path, "log", "--format=%s", "dev")
    assert (tmp_path / "live_fix.txt").exists()


# -- AC5 -----------------------------------------------------------------------


def test_ledger_on_feature_branch_guarded(tmp_path):
    """The no-ledger-on-feature invariant is enforced two ways: the engine records ledger
    commits on dev (never on the feature branch), and `steward lint` reports a feature branch
    whose diff against dev includes a .devsteward/ change."""
    # (a) engine half: drive a develop on a feature branch; the feature carries no ledger,
    #     the events are on dev.
    _scaffold(tmp_path, acs=[("AC1", "true", "artifact")])
    _init_git(tmp_path)
    ex = _executor(tmp_path, runner=_Runner(tmp_path), with_validate=True)
    r1 = ex.advance_once()
    assert r1.outcome is RunOutcome.DONE
    feature = _branch(tmp_path)
    assert _feature_ledger_diff(tmp_path, feature) == ""   # engine refused to ride the ledger
    assert "develop_committed" in _dev_events(tmp_path)     # …it recorded on dev instead

    # (b) lint half: a feature branch that *does* carry a hand-committed ledger change is a
    #     hard lint error (the regression this design exists to prevent).
    cfg = Config(root=tmp_path,
                 requirements_dir="docs/requirements",
                 index_file="docs/requirements/REQUIREMENTS_INDEX.md")
    assert lint(cfg) == []  # clean while the feature carries pure code
    (tmp_path / ".devsteward" / "events.jsonl").write_text(
        _git(tmp_path, "show", f"{feature}:.devsteward/events.jsonl") + '{"event":"sneaked"}\n',
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A", "--", ".devsteward")
    _git(tmp_path, "commit", "-q", "-m", "sneak a ledger change onto the feature branch")
    problems = lint(cfg)
    assert any("carries a ledger change" in p and feature in p for p in problems)
