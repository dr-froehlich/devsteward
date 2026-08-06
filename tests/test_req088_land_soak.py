"""REQ-088 Cause B — the land always captures its own `done` flip.

The engine wrote the flip (REQ frontmatter + index row) into the worktree and relied on
`git add -A` to stage it. Intermittently it staged **nothing**, the flip missed its commit,
and REQ-077's `_assert_committed_clean` rolled the land back with

    land left 2 path(s) uncommitted after the code commit — REQ-001.md, REQUIREMENTS_INDEX.md

Three conditions coincide, all structural rather than unlucky:

1. the flip is **size-preserving** — `status: open` → `status: done` and `| OPEN |` →
   `| DONE |` are 4 bytes either way;
2. it lands in the **same wall-clock second** as the stat git cached for that path when the
   capture gate staged the tree, and git (built without `USE_NSEC`, the default) compares
   only seconds + size;
3. git's racy-clean content-check does not rescue it, because that only fires for an entry
   whose cached mtime is at or after the *index file's* own timestamp — and the capture-gate
   extract pushes the index write seconds past the flip.

`test_land_restages_the_flip_under_the_confirmed_mechanism` forces all three with `os.utime`
so the proof is deterministic; `test_land_soak_never_leaves_the_tree_dirty` is the standing
`check: live` bound that a land never leaves the tree dirty for *any* reason.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from devsteward.core.errors import RecoverableError
from devsteward.core.executor import RunOutcome
from devsteward.core.git import GitCli
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus

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

#: Soak size — 30 lands, ~23s. Sized by cost, not by detection power: measured against a
#: deliberately un-fixed engine this catches the *known* Cause-B mechanism only about 1 run in
#: 5, because reproducing it needs a wall-clock-second coincidence the soak cannot force.
#: `test_land_restages_the_flip_under_the_confirmed_mechanism` is the real oracle for that
#: mechanism; this soak is the standing bound on the *invariant* ("a land never leaves the tree
#: dirty") and so on residual causes nobody has diagnosed yet. Raising it buys little: at 60
#: lands the cost doubles and detection is still well under half.
SOAK_LANDS = 30


# -- AC5: the confirmed mechanism, forced deterministically --------------------


def test_land_restages_the_flip_under_the_confirmed_mechanism(tmp_path):
    """AC5: with git's stat cache deliberately poisoned into the exact confirmed state — the
    flip size-preserving, its mtime pinned to the cached second, and the index file's own
    timestamp pushed past that second so the racy-clean content-check cannot fire — the
    commit still captures both flip surfaces.

    Pre-fix `git add -A` staged nothing here and the flip was silently dropped."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    _init_git(tmp_path)
    git = GitCli(tmp_path)

    req_path, index_path = tmp_path / _REQ, tmp_path / _INDEX
    before = req_path.read_text(encoding="utf-8")
    assert "status: open" in before

    # Condition 2, part one: give both flip surfaces a fixed mtime and let the index cache
    # exactly that stat — this stands in for the capture gate's earlier whole-tree stage.
    cached_ns = req_path.stat().st_mtime_ns - 100 * 10**9
    for p in (req_path, index_path):
        os.utime(p, ns=(cached_ns, cached_ns))
    git._run("update-index", "--really-refresh", check=True)

    # Condition 3: push the index file's own timestamp well past the cached entry mtime, so
    # the entry reads as non-racy and git's racy-clean content-check cannot fire. (In the
    # live defect this gap is opened by the capture-gate extract running pytest.)
    non_racy = cached_ns + 300 * 10**9
    os.utime(tmp_path / ".git" / "index", ns=(non_racy, non_racy))

    # Condition 1: the size-preserving flip, exactly as ReqDoneFlipper writes it …
    req_path.write_text(before.replace("status: open", "status: done"), encoding="utf-8")
    index_path.write_text(
        index_path.read_text(encoding="utf-8").replace("OPEN", "DONE"), encoding="utf-8"
    )
    assert len(req_path.read_text(encoding="utf-8")) == len(before), "flip must be size-preserving"
    # … landing back inside the second git already has cached.
    for p in (req_path, index_path):
        os.utime(p, ns=(cached_ns, cached_ns))

    # Sanity: the plain whole-tree stage really is blind to it (the defect, still live here).
    git._run("add", "-A", "--", ":(exclude).devsteward", check=True)
    assert git._run("diff", "--cached", "--name-only").stdout.split() == [], (
        "the forced coincidence no longer fools `git add -A` — this test has stopped "
        "reproducing the mechanism it exists to pin"
    )

    # The engine's commit, told which paths it just wrote, captures them anyway.
    sha = git.commit_code("REQ-001: flip", force_paths=[req_path, index_path])
    assert sha is not None

    committed = _git(tmp_path, "show", f"{sha}:{_REQ}")
    assert "status: done" in committed
    assert "DONE" in _git(tmp_path, "show", f"{sha}:{_INDEX}")
    assert _porcelain(tmp_path) == ""


def test_flipper_paths_reach_the_commit(tmp_path, monkeypatch):
    """AC5 (the wiring, not the git behaviour): the executor hands `on_verified`'s returned
    paths to the commit as `force_paths` rather than discarding the return value — the seam
    the test above depends on. Previously `on_verified(step)`'s result was thrown away."""
    seen: list[set[str]] = []
    original = GitCli.commit_code

    def spy(self, message, *, force_paths=()):
        seen.append({Path(p).name for p in force_paths})
        return original(self, message, force_paths=force_paths)

    monkeypatch.setattr(GitCli, "commit_code", spy)

    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    _init_git(tmp_path)
    res = _executor(tmp_path, writes={
        "tests/test_dep.py": _CAPTURED_TEST,
        "data.txt": "captured\n",
    }).advance_once()

    assert res.outcome is RunOutcome.DONE
    assert seen, "commit_code was never reached"
    assert {"REQ-001.md", "REQUIREMENTS_INDEX.md"} <= set().union(*seen), (
        f"on_verified's written paths were dropped before the commit; saw {seen}"
    )


def test_force_paths_tolerates_absent_and_untracked_paths(tmp_path):
    """AC5 (the fix must not introduce a new failure mode): `git add --renormalize` treats an
    unmatched pathspec as fatal, so a `force_paths` entry that does not exist — a project with
    no index file, say — would turn a benign absence into a hard land failure. Absent paths are
    filtered out; an untracked one is staged normally by the whole-tree add."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    _init_git(tmp_path)
    git = GitCli(tmp_path)

    (tmp_path / "brand_new.md").write_text("never committed\n", encoding="utf-8")
    sha = git.commit_code(
        "REQ-001: mixed force paths",
        force_paths=[
            tmp_path / "brand_new.md",          # exists, untracked
            tmp_path / _REQ,                    # exists, tracked
            tmp_path / "docs" / "gone.md",      # does not exist
        ],
    )

    assert sha is not None
    assert "brand_new.md" in _git(tmp_path, "show", "--name-only", "--pretty=format:", sha)
    assert _porcelain(tmp_path) == ""


# -- AC4: the standing soak ----------------------------------------------------


def test_land_soak_never_leaves_the_tree_dirty():
    """AC4 (`check: live`): SOAK_LANDS consecutive independent `advance_once()` lands, each
    over a freshly scaffolded temp git repo, all land DONE with an empty `git status
    --porcelain` and with the flip present in the committed tree at HEAD.

    Declared resources: a working `git` binary and a writable temp dir — both present in any
    develop-gate environment, so this never skips (REQ-068: a skipping `live` test is a hard
    red, not a silent pass)."""
    assert shutil.which("git"), "declared resource missing: git"

    failures: list[str] = []
    for i in range(SOAK_LANDS):
        root = Path(tempfile.mkdtemp(prefix=f"req088-soak{i}-"))
        try:
            _scaffold(root, test="python -m pytest tests/test_dep.py")
            _init_git(root)
            ex = _executor(root, writes={
                "tests/test_dep.py": _CAPTURED_TEST,
                "data.txt": "captured\n",
            })
            try:
                res = ex.advance_once()
            except RecoverableError as exc:
                failures.append(f"land {i}: rolled back — {exc}")
                continue
            if res.outcome is not RunOutcome.DONE:
                failures.append(f"land {i}: outcome {res.outcome} ({res.detail!r})")
                continue
            dirty = _porcelain(root)
            if dirty:
                failures.append(f"land {i}: dirty tree after land — {dirty!r}")
                continue
            if "status: done" not in _git(root, "show", f"{res.commit}:{_REQ}"):
                failures.append(f"land {i}: commit {res.commit} does not carry the flip")
            elif "DONE" not in _git(root, "show", f"{res.commit}:{_INDEX}"):
                failures.append(f"land {i}: commit {res.commit} does not carry the index sync")
            elif Ledger(root).status_of("REQ-001:develop") is not StepStatus.DONE:
                failures.append(f"land {i}: ledger did not record DONE")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    assert not failures, (
        f"{len(failures)}/{SOAK_LANDS} lands failed to capture their own work:\n  "
        + "\n  ".join(failures)
    )
