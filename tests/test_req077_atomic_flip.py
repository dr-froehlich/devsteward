"""REQ-077 — the checkpoint/land commit is atomic: the ``done``-flip rides the code commit.

REQ-076 scopes a headless code commit to the session's own delta by *timing* — stage only
``dirty_paths() - baseline``. That heuristic cannot classify the engine's **own** bookkeeping:
the ``REQUIREMENTS_INDEX.md`` row every land writes, and the REQ-file ``status`` flip. When
either is dirty at the boundary it lands in ``baseline`` and ``on_verified``'s flip to it is
subtracted back out — committed nowhere, left dirty in the tree (the FlowSteward REQ-098/099
drift, which *cascades* through the shared index once seeded).

The fix corrects the category error: the engine's flip paths are staged **by knowledge,
always**, outside the timing subtraction (``on_verified`` returns them, the commit
force-includes them). Real-git teeth throughout — the same throwaway-repo harness the REQ-063
integrity suite proved.

* **AC1** (``test_checkpoint_commits_flip_clean_tree``) — the interactive ``checkpoint`` path
  (``baseline is None``) commits the flip and leaves a clean tree. A regression guard on the
  already-immune whole-tree path.
* **AC2** (``test_headless_land_scoped_staging_includes_flip``) — the reproduction: with the REQ
  file **and** the shared index dirty at the boundary, the headless land still commits the flip
  and leaves a clean (scoped) tree. Fails on pre-fix code (flip dropped).
* **AC3** (``test_land_asserts_clean_tree_or_fails_loudly``) — a flip path dropped from the
  commit is caught by the post-land clean-tree assertion: the land rolls back and raises rather
  than returning DONE over a dirty tree; a clean land returns DONE.
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


# -- AC2: the reproduction — REQ file + index dirty at the boundary -------------


def test_headless_land_scoped_staging_includes_flip(tmp_path):
    """AC2: the FlowSteward REQ-098/099 shape. The REQ file **and** the shared index are dirty
    at the transaction boundary (a prior land's own residue / a hand edit), so both land in the
    REQ-076 baseline. The headless land must still commit ``on_verified``'s flip to those paths
    — staged by knowledge, past the timing subtraction — and leave a clean scoped tree. On
    pre-fix code the flip is subtracted out: the committed status stays ``open`` and the tree is
    left dirty."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    _init_git(tmp_path)

    # Dirty the engine's own bookkeeping at the boundary — the condition the timing heuristic
    # cannot classify. (A real run seeds this via the cascade: a prior step's dropped index-flip
    # leaves the index dirty for the next step's boundary.)
    reqp = tmp_path / _REQ
    reqp.write_text(reqp.read_text(encoding="utf-8") + "\n<!-- pre-boundary edit -->\n",
                    encoding="utf-8")
    idxp = tmp_path / _INDEX
    idxp.write_text(idxp.read_text(encoding="utf-8") + "\n<!-- pre-boundary edit -->\n",
                    encoding="utf-8")

    ex = _executor(tmp_path, writes={
        "tests/test_dep.py": _CAPTURED_TEST,
        "data.txt": "captured\n",  # tracked, self-sufficient green
    })
    res = ex.advance_once()

    assert res.outcome is RunOutcome.DONE
    # The flip landed despite both bookkeeping files being baseline-dirty.
    assert "status: done" in _committed(tmp_path, res.commit, _REQ)
    assert "DONE" in _committed(tmp_path, res.commit, _INDEX)
    assert {_REQ, _INDEX, "data.txt", "tests/test_dep.py"} <= _touched(tmp_path, res.commit)
    # Clean scoped tree — no dropped flip left behind (the cascade's seed is gone).
    assert _porcelain(tmp_path) == ""
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.DONE
    assert any(e["event"] == "checkpoint" for e in led.events())


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
