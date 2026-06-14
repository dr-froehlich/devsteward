"""The :class:`GitTopology` implementation that shells out to real ``git``.

The branch guards (REQ-011/019) only ever *read* the current branch, so a single
injectable ``branch_resolver`` callable sufficed. REQ-020 makes the executor *mutate*
topology — create+switch a feature branch on the first implementation step, merge it back
after a green land — so the read-only resolver is promoted to a full :class:`GitTopology`
seam (see ``seams.py``). :class:`GitCli` is the real implementation; ``conftest`` supplies
an in-memory fake so the loop is exercised without a real checkout.
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

    def branch_exists(self, name: str) -> bool:
        return (
            self._run("rev-parse", "--verify", "--quiet", f"refs/heads/{name}").returncode
            == 0
        )

    def create_and_switch(self, name: str) -> None:
        self._run("checkout", "-b", name, check=True)

    def switch(self, name: str) -> None:
        self._run("checkout", name, check=True)

    def integration_is_ancestor(self, integration: str, feature: str) -> bool:
        """True iff ``integration`` is an ancestor of ``feature`` (no divergence).

        When the integration branch has advanced past the point the feature was cut and
        the feature does not contain those commits, it is *not* an ancestor — the branch
        has diverged and must be surfaced, not silently reused.
        """
        return (
            self._run("merge-base", "--is-ancestor", integration, feature).returncode == 0
        )

    def commit_all(self, message: str) -> str | None:
        """Stage everything and commit. Returns the new sha, or ``None`` if clean."""
        self._run("add", "-A", check=True)
        if not self._run("status", "--porcelain").stdout.strip():
            return None
        self._run("commit", "-m", message, check=True)
        return self._run("rev-parse", "HEAD").stdout.strip()

    def merge_no_ff(self, feature: str, message: str) -> None:
        self._run("merge", "--no-ff", "-m", message, feature, check=True)

    def reconcile_from_integration(
        self, integration: str, feature: str, message: str
    ) -> None:
        """Bring ``integration``'s commits into ``feature`` (REQ-034 Decision 5).

        A deferred validation parks the feature branch unmerged while the integration
        branch keeps advancing ("the end of the run guarantees ``dev`` advanced"); when the
        human resumes, the branch is *behind* and ``integration`` is no longer one of its
        ancestors. Rather than refuse it as diverged (Finding 1), switch to it and merge
        ``integration`` ``--no-ff`` in, making the behind-but-merged branch current again so
        the deferred land can proceed. The engine owns this topology, as it already owns the
        build branch (REQ-020).
        """
        self.switch(feature)
        self._run("merge", "--no-ff", "-m", message, integration, check=True)
