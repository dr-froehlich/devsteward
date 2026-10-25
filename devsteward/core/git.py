"""The :class:`GitTopology` implementation that shells out to real ``git``.

Trunk-based (REQ-048): all work lands on the integration branch (`dev`). The engine never
creates a feature branch, never switches, and never spins up a worktree — so this seam
collapses to three operations: read the current branch (the only remaining guard is "never
commit on `main`"), commit the code, and commit the ledger. The two commits are kept
separate — code (+ REQ frontmatter flip + index row, same-commit discipline) excludes
``.devsteward/``; the ledger advance is its own ``.devsteward/``-only commit — so the code
history stays independent of the cursor and a commit can be checked for self-sufficiency
(REQ-050). :class:`GitCli` is the real implementation; ``conftest`` supplies an in-memory
fake so the loop runs without a real checkout.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path


def _parse_status_paths(z: str) -> set[str]:
    """The set of paths in a ``git status --porcelain -z`` payload.

    Each record is ``XY<space>PATH``; a rename/copy (``R``/``C`` in the status field) carries
    the source path as a separate trailing NUL-token, which is counted too. ``-z`` means the
    paths are literal (never quoted), so no unescaping is needed."""
    paths: set[str] = set()
    tokens = z.split("\0")
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok:
            i += 1
            continue
        status, path = tok[:2], tok[3:]
        paths.add(path)
        if "R" in status or "C" in status:
            # A rename/copy record is followed by its source path in the next token.
            i += 1
            if i < len(tokens) and tokens[i]:
                paths.add(tokens[i])
        i += 1
    return paths


class GitCli:
    """A :class:`devsteward.core.seams.GitTopology` backed by the ``git`` CLI."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _run(self, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=check,
        )

    def current_branch(self) -> str:
        """The checked-out branch, or ``"HEAD"`` when detached (never a real branch)."""
        return self._run("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def head_sha(self) -> str:
        """The current ``HEAD`` commit sha (the snapshot the transaction boundary restores)."""
        return self._run("rev-parse", "HEAD").stdout.strip()

    def dirty_paths(self) -> set[str]:
        """The set of code paths dirty relative to ``HEAD`` (staged or unstaged, tracked or
        untracked), ``.devsteward/`` excluded — read by the post-land clean-tree assertion
        (REQ-077 guard, kept by REQ-079): after the code commit nothing may remain dirty."""
        out = self._run(
            "status", "--porcelain", "-z", "--", ":(exclude).devsteward"
        ).stdout
        return _parse_status_paths(out)

    def _stage_code(self, force_paths: Iterable[Path | str] = ()) -> None:
        """Stage the **whole dirty tree** (never ``.devsteward/``) for the commit or
        write-tree — modified tracked files and untracked new files alike (REQ-079).

        This is deliberately unscoped. REQ-076's boundary-delta subtraction ("dirty at the
        transaction boundary = a concurrent stranger's") misfiled the engine's own flip
        writes (FlowSteward REQ-098/099) and the step's own prior failed attempts on the
        ``steward repeat`` path (FlowSteward REQ-103 — 1 of 10 files committed); REQ-079
        subtracted the heuristic. Concurrency is doctrine, not machinery: one engine
        session per repo at a time.

        ``force_paths`` names paths the caller just wrote and must stage **content-blind**
        (REQ-088 Cause B). ``git add -A`` decides what changed from the stat cache, comparing
        only *second*-granular mtime and size (git is built without ``USE_NSEC`` by default).
        The ``done`` flip is size-preserving on both surfaces — ``status: open`` → ``status:
        done`` and ``| OPEN |`` → ``| DONE |`` are 4 bytes either way — so when it lands in
        the same wall-clock second as the stat cached by the capture gate's earlier stage,
        git sees an identical ``(seconds, size)`` pair and stages **nothing**. Git's
        racy-clean content-check does not rescue it: that only fires for an entry whose
        cached mtime is at or after the index file's own timestamp, and the capture-gate
        extract pushes the index write seconds past the flip. ``--renormalize`` re-reads the
        content and bypasses the stat shortcut entirely.

        Scoped to the caller's own writes on purpose: a repo-wide ``--renormalize`` would
        re-run clean filters over every tracked file and could stage unrelated line-ending
        normalization in a consumer repo. Everything else stays covered by REQ-077's
        post-land clean-tree assertion, which fails loudly rather than silently."""
        self._run("add", "-A", "--", ":(exclude).devsteward", check=True)
        rel = [self._relative(p) for p in force_paths if (self.root / p).exists()]
        if rel:
            self._run("add", "--renormalize", "--", *rel, check=True)

    def _relative(self, path: Path | str) -> str:
        """``path`` as a repo-relative POSIX string (absolute paths come from the seams).

        Callers filter to paths that exist first: ``git add --renormalize`` treats an
        unmatched pathspec as fatal, and a project with no index file would otherwise turn a
        benign absence into a hard land failure. An untracked path is fine — the whole-tree
        ``add -A`` has already staged it and ``--renormalize`` is a no-op over it."""
        p = Path(path)
        return (p.relative_to(self.root) if p.is_absolute() else p).as_posix()

    def commit_code(
        self, message: str, *, force_paths: Iterable[Path | str] = ()
    ) -> str | None:
        """Stage the whole dirty tree (never ``.devsteward/``) and commit. Returns the new
        sha, or ``None`` when there is nothing to commit.

        The code-carrying commit (code + REQ frontmatter ``done``-flip + index ``DONE``-sync,
        same-commit discipline) never carries the ledger — the cursor advances in its own
        trailing commit (:meth:`commit_ledger`), so the code history stays clean and a commit
        can be checked for green self-sufficiency (REQ-050)."""
        self._stage_code(force_paths)
        if not self._run("diff", "--cached", "--name-only").stdout.strip():
            return None
        self._run("commit", "-m", message, check=True)
        return self.head_sha()

    def file_at_head(self, relpath: str) -> str | None:
        """The committed contents of ``relpath`` at ``HEAD``, or ``None`` when it is not tracked
        there (or there is no commit yet). REQ-077: the marker↔ledger lint guard reads the
        **committed** marker, not the working tree — a flip written to the worktree but never
        committed looks consistent on disk and would mask the drift."""
        proc = self._run("show", f"HEAD:{relpath}")
        return proc.stdout if proc.returncode == 0 else None

    def write_code_tree(self) -> str | None:
        """Stage the code (:meth:`_stage_code`) and serialize the index to a tree object,
        returning its sha — the capture-gate mirror of :meth:`commit_code`.

        The REQ-063 self-check runs against this tree, so it must be built from the **same**
        staging routine ``commit_code`` uses — byte-identical whole tree — or the gate would
        certify a different tree than lands. ``None`` if the index serializes nothing."""
        self._stage_code()
        out = self._run("write-tree", check=True)
        return out.stdout.strip() or None

    def commit_ledger(self, message: str) -> str | None:
        """Stage and commit only ``.devsteward/`` (the cursor advance + any captured
        evidence). Returns the new sha, or ``None`` when the ledger is unchanged (so a clean
        ledger makes no empty commit)."""
        self._run("add", "-A", "--", ".devsteward", check=True)
        if not self._run("diff", "--cached", "--name-only").stdout.strip():
            return None
        self._run("commit", "-m", message, check=True)
        return self.head_sha()

    def reset_hard(self, sha: str) -> None:
        """Restore committed and tracked state to ``sha`` (REQ-049 transaction rollback).

        ``git reset --hard`` undoes commits made since ``sha`` *and* discards tracked-file
        edits, restoring the pre-command state byte-identically. Untracked files created
        mid-command are left in place (visible, not "applied")."""
        self._run("reset", "--hard", sha, check=True)
