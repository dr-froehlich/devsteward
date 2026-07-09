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
from pathlib import Path


def _parse_status_paths(z: str) -> set[str]:
    """The set of paths in a ``git status --porcelain -z`` payload (REQ-076).

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
        untracked), ``.devsteward/`` excluded — the transaction-boundary baseline REQ-076
        scopes the code commit against."""
        out = self._run(
            "status", "--porcelain", "-z", "--", ":(exclude).devsteward"
        ).stdout
        return _parse_status_paths(out)

    def _stage_code(
        self, baseline: set[str] | None, include: set[str] | None = None
    ) -> None:
        """Stage the code (never ``.devsteward/``) for the commit or write-tree (REQ-076).

        ``baseline is None`` — the ``checkpoint`` path (dirty-at-entry, no session to
        distinguish from): stage the whole dirty tree as before. A ``baseline`` set — a headless
        authoring command whose ``claude`` session ran *after* the boundary: rebuild the index
        from ``HEAD`` (so a concurrent file already staged at the boundary cannot ride in) and
        stage only the paths that became dirty *after* the baseline, i.e. this session's own
        work. A path already dirty at the boundary (a concurrent REQ's in-progress work) is left
        untouched.

        ``include`` (REQ-077): paths the engine authored as its own authoritative bookkeeping —
        the REQ frontmatter ``done``-flip and the index ``DONE``-sync — that must ride the commit
        **regardless of the baseline**. The boundary subtraction is meant to drop a *concurrent*
        session's dirt; it must never drop the flip, which ``on_verified`` writes *after* the
        boundary to a path that may itself have been baseline-dirty (the FlowSteward REQ-098/099
        drop). Force-staged on top of the scoped delta; a no-op in the ``baseline is None`` path
        (``add -A`` already covers them) and when empty."""
        if baseline is None:
            self._run("add", "-A", "--", ":(exclude).devsteward", check=True)
            return
        to_stage = sorted(self.dirty_paths() - baseline)
        self._run("reset", "-q", check=True)  # rebuild the index from HEAD
        if to_stage:
            self._run("add", "-A", "--", *to_stage, check=True)
        if include:
            # The engine's own flip — never subtracted by the boundary scope (REQ-077).
            self._run("add", "-A", "--", *sorted(include), check=True)

    def commit_code(
        self,
        message: str,
        baseline: set[str] | None = None,
        include: set[str] | None = None,
    ) -> str | None:
        """Stage the code (never ``.devsteward/``) and commit. Returns the new sha, or ``None``
        when there is nothing to commit.

        ``baseline`` (REQ-076): the dirty-path set captured at the transaction boundary, before
        this command's authoring session ran. When supplied, the commit is **scoped** to the
        session's own delta — a file already dirty at the boundary (a concurrent session's
        in-progress work for a different REQ) is not swept in, so same-commit discipline holds.
        ``None`` (the ``checkpoint`` path) stages the whole dirty tree as before.

        ``include`` (REQ-077): the engine's flip paths, force-staged past the boundary scope so
        the REQ frontmatter ``done``-flip + index ``DONE``-sync always land in this one commit —
        the same-commit discipline the boundary subtraction would otherwise break.

        The code-carrying commit (code + REQ frontmatter ``done``-flip + index ``DONE``-sync,
        same-commit discipline) never carries the ledger — the cursor advances in its own
        trailing commit (:meth:`commit_ledger`), so the code history stays clean and a commit
        can be checked for green self-sufficiency (REQ-050)."""
        self._stage_code(baseline, include)
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

    def write_code_tree(self, baseline: set[str] | None = None) -> str | None:
        """Stage the code (:meth:`_stage_code`) and serialize the index to a tree object,
        returning its sha (REQ-076 — the capture-gate mirror of :meth:`commit_code`).

        The REQ-063 self-check runs against this tree, so it must be built from the **same**
        staging routine ``commit_code`` uses — identical ``baseline`` in, byte-identical scoped
        tree out — or the gate would certify a different tree than lands. ``None`` if the index
        serializes nothing."""
        self._stage_code(baseline)
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
