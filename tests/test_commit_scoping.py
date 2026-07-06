"""REQ-076 — scope the headless code commit to what the command itself authored.

A code commit for REQ-X used to ``git add -A`` the whole ``dev`` worktree, so a file left
dirty by a *concurrent* session for a different REQ was swept into REQ-X's commit — the
FlowSteward REQ-081→REQ-090 sweep (2026-07-05 postmortem), a silent same-commit-discipline
violation. The subtractive fix (not a lock/worktree — that would solve an information-flow
problem with git topology, the REQ-047 anti-pattern) is to **scope the commit to the
session's own delta**: the engine records the dirty-path set at the transaction boundary
(before ``claude -p`` runs) and stages only what the session dirtied afterward.

Real git teeth throughout — a throwaway repo, the ``GitCli`` seam exercised directly for the
staging arithmetic (AC1–AC3) and the full ``advance_once`` headless land for the wire-through
(AC4, the shape that actually swept).

* **AC1** (``test_scoped_commit_excludes_preexisting_dirt``) — a file already dirty (even
  *staged*) at the boundary is absent from the scoped commit; the session's own file is present.
* **AC2** (``test_capture_gate_tree_matches_scoped_commit``) — the capture-gate mirror
  (``write_code_tree``) serializes byte-for-byte the tree ``commit_code`` commits, so the
  REQ-063 gate and the commit never diverge.
* **AC3** (``test_unscoped_commit_stages_whole_tree``) — with no baseline (the ``checkpoint``
  path) the whole dirty tree is staged as before; a concurrent-dirt file *is* committed.
* **AC4** (``test_headless_land_does_not_sweep_concurrent_file``) — driving the real headless
  land, a planted concurrent-dirty file stays uncommitted while the REQ flip, index sync, and
  the session's code land in the one authoritative commit.
"""

from __future__ import annotations

from pathlib import Path

from devsteward.core.executor import RunOutcome
from devsteward.core.git import GitCli
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus

# The real headless-land harness (a temp ``git init`` repo on ``dev``, only ``claude`` faked and
# authoring its files *during* the run) is the one already proven by the REQ-063 integrity
# suite — reused here so AC4 exercises exactly the engine's live land path, one source of truth.
from test_commit_integrity import (
    _CAPTURED_TEST,
    _executor,
    _git,
    _init_git,
    _log_shas,
    _porcelain,
    _scaffold,
)


# -- a throwaway repo for the GitCli seam (AC1–AC3) ----------------------------


def _repo(root: Path) -> GitCli:
    """A real git repo on ``dev`` with one committed file, returning its ``GitCli`` seam."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "scoping@devsteward.test")
    _git(root, "config", "user.name", "DevSteward Scoping Test")
    _git(root, "checkout", "-q", "-b", "dev")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "scaffold")
    return GitCli(root)


def _committed_paths(root: Path, sha: str) -> set[str]:
    """The paths a commit touches (its diff against its parent)."""
    out = _git(root, "show", "--name-only", "--pretty=format:", sha)
    return {line for line in out.splitlines() if line}


# -- AC1: a file dirty at the boundary is excluded from the scoped commit -------


def test_scoped_commit_excludes_preexisting_dirt(tmp_path):
    """AC1: reproduce the REQ-081→REQ-090 sweep at the commit seam. A concurrent session's
    in-progress file is dirty (and even *staged*, as it would be in a shared index) when the
    baseline is snapshotted; the session then authors its own file. Committing with that
    baseline stages only the session's delta — the concurrent file is absent from the commit
    and left untouched in the tree, so same-commit discipline holds."""
    git = _repo(tmp_path)

    # A concurrent REQ's in-progress work, already staged in the shared index at the boundary.
    (tmp_path / "concurrent_work.py").write_text("# REQ-OTHER, mid-flight\n", encoding="utf-8")
    _git(tmp_path, "add", "concurrent_work.py")
    baseline = git.dirty_paths()
    assert "concurrent_work.py" in baseline

    # The session's own work, authored *after* the boundary.
    (tmp_path / "session_work.py").write_text("# this REQ\n", encoding="utf-8")

    sha = git.commit_code("REQ-001: the session's work", baseline)
    assert sha is not None
    touched = _committed_paths(tmp_path, sha)
    assert "session_work.py" in touched
    assert "concurrent_work.py" not in touched  # the sweep is prevented

    # The concurrent work is preserved in the tree, not consumed — still dirty for its own owner.
    assert "concurrent_work.py" in _porcelain(tmp_path)


# -- AC2: the capture-gate tree matches the scoped commit exactly --------------


def test_capture_gate_tree_matches_scoped_commit(tmp_path):
    """AC2: the REQ-063 self-check runs against ``write_code_tree``; it must serialize the
    *same* scoped tree ``commit_code`` lands, or the gate certifies a tree the commit does not
    hold. Same baseline in → byte-identical tree out, and the concurrent-dirt file is absent
    from the gate's tree too."""
    git = _repo(tmp_path)

    (tmp_path / "concurrent_work.py").write_text("# REQ-OTHER, mid-flight\n", encoding="utf-8")
    baseline = git.dirty_paths()
    (tmp_path / "session_work.py").write_text("# this REQ\n", encoding="utf-8")

    gate_tree = git.write_code_tree(baseline)
    assert gate_tree is not None
    # The gate never sees the concurrent file; it does see the session's own work.
    listed = set(_git(tmp_path, "ls-tree", "-r", "--name-only", gate_tree).split())
    assert "session_work.py" in listed
    assert "concurrent_work.py" not in listed

    sha = git.commit_code("REQ-001: the session's work", baseline)
    assert sha is not None
    commit_tree = _git(tmp_path, "rev-parse", f"{sha}^{{tree}}").strip()
    assert commit_tree == gate_tree  # the gate and the commit are one tree


# -- AC3: no baseline (the checkpoint path) stages the whole dirty tree ---------


def test_unscoped_commit_stages_whole_tree(tmp_path):
    """AC3: the over-scoping guard. ``checkpoint`` passes no baseline (its work is
    dirty-at-entry, indistinguishable from pre-existing dirt), so ``commit_code`` must stage the
    whole dirty tree as before — the human's interactively-curated work. Here a concurrent-dirt
    file *is* committed, proving the scoping is opt-in and today's behaviour is preserved."""
    git = _repo(tmp_path)

    (tmp_path / "concurrent_work.py").write_text("# another REQ\n", encoding="utf-8")
    (tmp_path / "session_work.py").write_text("# this REQ\n", encoding="utf-8")

    sha = git.commit_code("checkpoint: whole tree")  # baseline omitted → unscoped
    assert sha is not None
    touched = _committed_paths(tmp_path, sha)
    assert {"concurrent_work.py", "session_work.py"} <= touched
    assert _porcelain(tmp_path) == ""  # everything landed


# -- AC4: the real headless land does not sweep a concurrent file --------------


def test_headless_land_does_not_sweep_concurrent_file(tmp_path):
    """AC4 (wire-through, REQ-071): the executor must actually thread the boundary baseline into
    the land, not merely that the git seam can accept one. Drive ``advance_once`` — the session
    authors its code during the run — with a concurrent REQ's file planted dirty *before* the
    command begins. That file stays uncommitted, while the REQ ``done`` flip, the index sync,
    and the session's code all land in the one authoritative commit."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    _init_git(tmp_path)

    # A concurrent session's in-progress work, dirty in the shared tree at the boundary.
    (tmp_path / "concurrent_work.py").write_text("# REQ-OTHER, mid-flight\n", encoding="utf-8")

    ex = _executor(tmp_path, writes={
        "tests/test_dep.py": _CAPTURED_TEST,
        "data.txt": "captured\n",  # tracked, self-sufficient green
    })
    res = ex.advance_once()

    assert res.outcome is RunOutcome.DONE
    assert res.commit in _log_shas(tmp_path)
    touched = _committed_paths(tmp_path, res.commit)
    # The session's code AND the same-commit bookkeeping ride the one commit …
    assert {"data.txt", "tests/test_dep.py"} <= touched
    assert "docs/requirements/REQ-001.md" in touched
    assert "docs/requirements/REQUIREMENTS_INDEX.md" in touched
    # … but the concurrent REQ's file was never swept in.
    assert "concurrent_work.py" not in touched
    assert "concurrent_work.py" in _porcelain(tmp_path)  # preserved for its owner

    assert Ledger(tmp_path).status_of("REQ-001:develop") is StepStatus.DONE
    assert "status: done" in (tmp_path / "docs" / "requirements" / "REQ-001.md").read_text()
