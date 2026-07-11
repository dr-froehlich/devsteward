"""REQ-079 — the code commit stages the whole dirty tree; nothing of the step's work is
scoped away.

REQ-076 committed only ``dirty_paths() - baseline`` (the delta since the transaction
boundary), on the premise that anything already dirty at the boundary was a concurrent
session's. That premise misfiled the step's **own** work twice: the engine's flip writes
(FlowSteward REQ-098/099, patched by REQ-077's force-include) and a previous failed
attempt's files on the ``steward repeat`` path (FlowSteward REQ-103 — attempt 3 went green
against the full working tree but the commit captured 1 of 10 files, the rest being dirty
since attempts 1–2). REQ-079 subtracts the heuristic: every code commit stages the entire
dirty tree, ``.devsteward/`` excluded; concurrency is doctrine (one session per repo), not
commit machinery.

Real-git teeth throughout — the throwaway-repo harness proven by the REQ-063 integrity suite.

* **AC1** (``test_commit_stages_prior_attempt_work``) — the REQ-103 shape at the commit
  seam: pre-existing dirt (a prior attempt's modified tracked file + untracked new file)
  and a fresh session file all land in ``commit_code``'s commit; ``.devsteward/`` stays
  out; the seam exposes no scoping parameters.
* **AC2** (``test_headless_land_commits_whole_tree_and_flip``) — wire-through: the real
  headless land with prior-attempt dirt present lands the dirt, the session's files, the
  ``done`` flip, and the index ``DONE`` in the one authoritative commit, tree clean, no
  capture gap.
* **AC3** (``test_capture_gate_tree_is_whole_tree``) — the capture-gate mirror serializes
  the identical whole tree the commit lands (REQ-063: the gate never certifies a different
  tree than lands).
"""

from __future__ import annotations

import inspect

from devsteward.core.executor import RunOutcome
from devsteward.core.git import GitCli
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus

# Reuse the real-git land harness proven by the REQ-063 integrity suite (one source of truth).
from test_commit_integrity import (
    _CAPTURED_TEST,
    _executor,
    _git,
    _init_git,
    _porcelain,
    _scaffold,
)

_REQ = "docs/requirements/REQ-001.md"
_INDEX = "docs/requirements/REQUIREMENTS_INDEX.md"


def _touched(root, sha):
    return {p for p in _git(root, "show", "--name-only", "--pretty=format:", sha).split() if p}


def _committed(root, sha, path):
    return _git(root, "show", f"{sha}:{path}")


def _dirty_prior_attempt(root) -> None:
    """Plant a prior failed attempt's leftovers: one modified tracked file, one untracked
    new file — dirty *before* the engine runs (the REQ-103 ``steward repeat`` shape)."""
    (root / "README.md").write_text("attempt-1 edit\n", encoding="utf-8")  # tracked, modified
    (root / "impl.py").write_text("VALUE = 'attempt-1'\n", encoding="utf-8")  # untracked, new


# -- AC1: the commit seam stages pre-existing dirt + fresh work alike -----------


def test_commit_stages_prior_attempt_work(tmp_path):
    """AC1: files dirty before the commit (a prior attempt's work) and a freshly-authored
    file are ALL in the code commit; ``.devsteward/`` is excluded; the seam has no
    baseline/include scoping parameters."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    (tmp_path / "README.md").write_text("scaffold\n", encoding="utf-8")
    _init_git(tmp_path)

    git = GitCli(tmp_path)
    _dirty_prior_attempt(tmp_path)
    # The "session" authors one more file on top of the prior attempt's dirt.
    (tmp_path / "session.py").write_text("VALUE = 'attempt-3'\n", encoding="utf-8")
    # Ledger writes never ride the code commit.
    (tmp_path / ".devsteward" / "scratch.txt").write_text("cursor\n", encoding="utf-8")

    sha = git.commit_code("REQ-001: whole tree")

    assert sha is not None
    touched = _touched(tmp_path, sha)
    assert {"README.md", "impl.py", "session.py"} <= touched
    assert not any(p.startswith(".devsteward") for p in touched)
    # The scoping surface is gone: message-only commit, parameterless mirror (REQ-079 AC1).
    assert list(inspect.signature(GitCli.commit_code).parameters) == ["self", "message"]
    assert list(inspect.signature(GitCli.write_code_tree).parameters) == ["self"]


# -- AC2: wire-through — the real headless land path ---------------------------


def test_headless_land_commits_whole_tree_and_flip(tmp_path):
    """AC2: the headless land (``advance_once`` over a real GitCli) with prior-attempt dirt
    present lands that dirt, the session's files, the ``status: done`` flip, and the index
    ``DONE`` row in the one authoritative commit; the tree is clean; the capture gate passes
    (no ``capture_gap`` event) — the executor's whole path is unscoped, not merely the seam."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    (tmp_path / "README.md").write_text("scaffold\n", encoding="utf-8")
    _init_git(tmp_path)
    _dirty_prior_attempt(tmp_path)

    ex = _executor(tmp_path, writes={
        "tests/test_dep.py": _CAPTURED_TEST,
        "data.txt": "captured\n",
    })
    res = ex.advance_once()

    assert res.outcome is RunOutcome.DONE
    touched = _touched(tmp_path, res.commit)
    # Prior-attempt dirt + session work + the engine's flip, one commit (same-commit discipline).
    assert {"README.md", "impl.py", "data.txt", "tests/test_dep.py", _REQ, _INDEX} <= touched
    assert "status: done" in _committed(tmp_path, res.commit, _REQ)
    assert "DONE" in _committed(tmp_path, res.commit, _INDEX)
    assert _porcelain(tmp_path) == ""
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.DONE
    events = [e["event"] for e in led.events()]
    assert "checkpoint" in events
    assert "capture_gap" not in events


# -- AC3: the capture-gate mirror is the committed tree ------------------------


def test_capture_gate_tree_is_whole_tree(tmp_path):
    """AC3: with pre-existing dirt present, ``write_code_tree()`` serializes the exact tree
    ``commit_code`` then lands — identical tree ids, so the REQ-063 gate can never certify
    a different tree than lands."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    (tmp_path / "README.md").write_text("scaffold\n", encoding="utf-8")
    _init_git(tmp_path)

    git = GitCli(tmp_path)
    _dirty_prior_attempt(tmp_path)
    (tmp_path / "session.py").write_text("VALUE = 'attempt-3'\n", encoding="utf-8")

    gate_tree = git.write_code_tree()
    sha = git.commit_code("REQ-001: whole tree")
    committed_tree = _git(tmp_path, "rev-parse", f"{sha}^{{tree}}").strip()

    assert gate_tree == committed_tree
