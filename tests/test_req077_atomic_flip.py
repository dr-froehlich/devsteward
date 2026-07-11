"""REQ-077 guards, as kept by REQ-079 — the ``done``-flip rides the code commit and a land
never returns DONE over a dirty tree.

REQ-077's original AC2 (scoped staging force-includes the flip past the REQ-076 boundary
subtraction) is superseded: REQ-079 removed the scoping entirely, so the whole-tree commit
stages the flip like any other write — the superseding coverage is
``test_req079_whole_tree_commit.py::test_headless_land_commits_whole_tree_and_flip``. What
survives here are the scoping-independent guards:

* **AC1** (``test_checkpoint_commits_flip_clean_tree``) — the interactive ``checkpoint`` path
  commits the flip in the one code commit and leaves a clean tree.
* **AC3** (``test_land_asserts_clean_tree_or_fails_loudly``) — a commit that fails to capture
  the work is caught by the post-land clean-tree assertion: the land rolls back and raises
  rather than returning DONE over a dirty tree; a clean land returns DONE.

Real-git teeth throughout — the same throwaway-repo harness the REQ-063 integrity suite proved.
"""

from __future__ import annotations

import pytest

from devsteward.core.errors import RecoverableError
from devsteward.core.executor import RunOutcome
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


def _committed(root, sha, path):
    """The contents of ``path`` in commit ``sha``."""
    return _git(root, "show", f"{sha}:{path}")


def _touched(root, sha):
    return {p for p in _git(root, "show", "--name-only", "--pretty=format:", sha).split() if p}


# -- AC1: the interactive checkpoint path commits the flip, clean tree ----------


def test_checkpoint_commits_flip_clean_tree(tmp_path):
    """AC1: ``ex.checkpoint`` (no claude, ``baseline is None``) on a landing REQ whose work is
    already dirty in the tree (interactive ``/advance`` left it) commits the ``done`` flip +
    index ``DONE`` in the one code commit and leaves ``git status --porcelain`` clean."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    _init_git(tmp_path)
    # /advance left the work dirty (uncommitted) for the bookkeeper.
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_dep.py").write_text(_CAPTURED_TEST, encoding="utf-8")
    (tmp_path / "data.txt").write_text("captured\n", encoding="utf-8")

    ex = _executor(tmp_path)  # the AuthoringRunner never fires on the checkpoint path
    ex.ledger.set_cursor("REQ-001:develop")
    ex.ledger.save()
    res = ex.checkpoint(ex.step_by_id("REQ-001:develop"))

    assert res.outcome is RunOutcome.DONE
    # The flip rides the one code commit …
    assert "status: done" in _committed(tmp_path, res.commit, _REQ)
    assert "DONE" in _committed(tmp_path, res.commit, _INDEX)
    assert {_REQ, _INDEX, "data.txt", "tests/test_dep.py"} <= _touched(tmp_path, res.commit)
    # … and the tree is clean (the trailing .devsteward/ ledger commit is its own commit).
    assert _porcelain(tmp_path) == ""
    assert Ledger(tmp_path).status_of("REQ-001:develop") is StepStatus.DONE


# -- AC3: a dropped flip is caught — fail loudly, never DONE over a dirty tree --


def test_land_asserts_clean_tree_or_fails_loudly(tmp_path):
    """AC3: a green land whose commit does **not** capture the work (the flip + session code
    stay dirty) fails loudly — the post-land clean-tree assertion raises and the enclosing
    transaction rolls the half-land back — rather than reporting DONE over a dirty tree. Simulate
    an incomplete commit with a ``committer`` seam that captures nothing, so ``on_verified``'s
    flip and the session's files are left uncommitted after the "commit"."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    _init_git(tmp_path)

    ex = _executor(tmp_path, writes={
        "tests/test_dep.py": _CAPTURED_TEST,
        "data.txt": "captured\n",
    })
    ex.committer = lambda step: None  # the commit captures nothing (incomplete-commit shape)

    with pytest.raises(RecoverableError):
        ex.advance_once()

    # Nothing certified: the step is not DONE and there is no checkpoint event (rolled back).
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is not StepStatus.DONE
    assert not any(e["event"] == "checkpoint" for e in led.events())

    # Control: the real commit path lands the same work DONE, clean, flip committed.
    good = tmp_path / "good"
    good.mkdir()
    _scaffold(good, test="python -m pytest tests/test_dep.py")
    _init_git(good)
    gres = _executor(good, writes={
        "tests/test_dep.py": _CAPTURED_TEST,
        "data.txt": "captured\n",
    }).advance_once()
    assert gres.outcome is RunOutcome.DONE
    assert _porcelain(good) == ""
    assert "status: done" in _committed(good, gres.commit, _REQ)
