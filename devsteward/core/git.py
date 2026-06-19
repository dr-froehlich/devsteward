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

    def commit_code(self, message: str) -> str | None:
        """Stage everything **except** ``.devsteward/`` and commit. Returns the new sha, or
        ``None`` when there is nothing to commit.

        The code-carrying commit (code + REQ frontmatter ``done``-flip + index ``DONE``-sync,
        same-commit discipline) never carries the ledger — the cursor advances in its own
        trailing commit (:meth:`commit_ledger`), so the code history stays clean and a commit
        can be checked for green self-sufficiency (REQ-050)."""
        self._run("add", "-A", "--", ":(exclude).devsteward", check=True)
        if not self._run("diff", "--cached", "--name-only").stdout.strip():
            return None
        self._run("commit", "-m", message, check=True)
        return self.head_sha()

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
