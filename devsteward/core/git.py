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

    def commit_all(self, message: str, *, exclude_ledger: bool = False) -> str | None:
        """Stage everything and commit. Returns the new sha, or ``None`` if clean.

        ``exclude_ledger`` (REQ-037) stages everything **except** ``.devsteward/`` — the
        code-carrying commit on a feature branch must never carry the ledger, which lives on
        the integration branch. Implemented with a pathspec exclude so a ledger working-copy
        change (if any) is left untouched in the tree, not committed onto the feature branch.
        """
        if exclude_ledger:
            self._run("add", "-A", "--", ":(exclude).devsteward", check=True)
            staged = self._run("diff", "--cached", "--name-only").stdout.strip()
            if not staged:
                return None
        else:
            self._run("add", "-A", check=True)
            if not self._run("status", "--porcelain").stdout.strip():
                return None
        self._run("commit", "-m", message, check=True)
        return self._run("rev-parse", "HEAD").stdout.strip()

    def merge_no_ff(self, feature: str, message: str) -> None:
        self._run("merge", "--no-ff", "-m", message, feature, check=True)

    # -- REQ-037: the ledger lives on the integration branch -------------------

    def _wt_path(self, integration: str) -> Path:
        """The managed linked-worktree path for the integration branch — a sibling of the
        repo root (outside it, so it is never swept by an ``add -A`` in the main tree)."""
        return self.root.parent / f".{self.root.name}.devsteward-{integration}-wt"

    def _worktree_for_branch(self, branch: str) -> str | None:
        """The path of an existing linked worktree checked out on ``branch``, or ``None``."""
        out = self._run("worktree", "list", "--porcelain").stdout
        path: str | None = None
        for line in out.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree ") :].strip()
            elif line.startswith("branch ") and line.endswith(f"/{branch}"):
                if path and Path(path) != self.root:
                    return path
        return None

    def integration_worktree(self, integration: str) -> str | None:
        """Ensure a linked worktree checked out on ``integration`` and return its path, or
        ``None`` when the main tree is already on ``integration`` (no worktree needed).

        REQ-037 Decision 1: while the main tree sits on a feature branch, the engine writes
        and commits the ledger here, on the integration branch — so a feature→integration
        merge carries no ``.devsteward/`` and cannot conflict on it.
        """
        if self.current_branch() == integration:
            return None
        existing = self._worktree_for_branch(integration)
        if existing:
            return existing
        path = self._wt_path(integration)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self._run("worktree", "remove", "--force", str(path))
        self._run("worktree", "add", "--quiet", str(path), integration, check=True)
        return str(path)

    def ledger_diff_against(self, integration: str, branch: str) -> str:
        """The ``.devsteward/`` paths that ``branch`` changed relative to ``integration``
        (three-dot, i.e. since their merge base) — empty when the branch carries no ledger.
        Used by ``steward lint`` to flag a ledger-on-feature-branch regression (REQ-037)."""
        return self._run(
            "diff", "--name-only", f"{integration}...{branch}", "--", ".devsteward"
        ).stdout.strip()

    def clean_untracked_ledger(self) -> None:
        """Remove untracked ``.devsteward/`` files from the main tree (the evidence the
        System-Tester session captured, already committed on the integration branch via the
        worktree) so the subsequent switch back to the integration branch is conflict-free."""
        self._run("clean", "-fdq", "--", ".devsteward")

    def dirty_tracked_ledger(self) -> str:
        """The tracked ``.devsteward/`` paths with an *uncommitted* change in the main tree
        (newline-joined), or ``""`` when clean (REQ-043 Decision 2).

        Untracked entries (porcelain ``??``) are excluded — they are swept by
        :meth:`clean_untracked_ledger`; only a *tracked* modification makes ``git checkout``
        refuse to switch and crash, which is the precondition the close-out must surface
        rather than ride into an uncaught ``CalledProcessError``.
        """
        out = self._run("status", "--porcelain", "--", ".devsteward").stdout
        return "\n".join(
            line[3:] for line in out.splitlines()
            if line.strip() and not line.startswith("??")
        ).strip()

    def remove_integration_worktree(self, integration: str) -> None:
        """Drop the managed integration worktree if present (idempotent) — called before the
        main tree switches back to the integration branch, since git forbids the same branch
        in two worktrees at once."""
        existing = self._worktree_for_branch(integration) or str(self._wt_path(integration))
        if Path(existing).exists():
            self._run("worktree", "remove", "--force", existing)
        self._run("worktree", "prune")

    def commit_ledger_at(self, worktree: str, message: str) -> str | None:
        """Stage and commit only ``.devsteward/`` inside ``worktree`` (on the integration
        branch). Returns the new sha, or ``None`` when the ledger is unchanged."""
        wt = Path(worktree)
        subprocess.run(["git", "add", "-A", "--", ".devsteward"], cwd=wt, check=True,
                       capture_output=True, text=True)
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=wt,
                                check=False, capture_output=True, text=True).stdout.strip()
        if not staged:
            return None
        subprocess.run(["git", "commit", "-m", message], cwd=wt, check=True,
                       capture_output=True, text=True)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, check=False,
                              capture_output=True, text=True).stdout.strip()

    # -- REQ-037 Decision 2: atomic, recoverable topology mutations ------------

    def fetch(self) -> bool:
        """Best-effort ``git fetch`` of all remotes. Returns ``True`` if a fetch ran (a
        remote exists), ``False`` when there is no remote (a purely local repo)."""
        if not self._run("remote").stdout.strip():
            return False
        self._run("fetch", "--quiet", "--all")
        return True

    def feature_behind_remote(self, feature: str) -> bool:
        """True iff ``origin/<feature>`` exists and carries commits ``feature`` lacks (a
        deploy host pushed a live fix, REQ-038) — a *handled* case, not a crash."""
        if not self.branch_exists_remote(feature):
            return False
        n = self._run("rev-list", "--count", f"{feature}..origin/{feature}").stdout.strip()
        return n.isdigit() and int(n) > 0

    def branch_exists_remote(self, feature: str) -> bool:
        return (
            self._run("rev-parse", "--verify", "--quiet",
                      f"refs/remotes/origin/{feature}").returncode == 0
        )

    def incorporate_remote(self, feature: str) -> str | None:
        """Bring ``origin/<feature>``'s commits into the local ``feature`` (the remote is
        ahead — a deploy host pushed a live fix, REQ-038), fast-forwarding when possible and
        merging otherwise (the local feature also advanced, e.g. the done-flip). Atomic: on a
        conflict it aborts and returns a recovery instruction (``None`` on success), so a
        behind-remote feature is a *handled* case, not a crash (REQ-037 AC4 / D2)."""
        self.switch(feature)
        res = self._run("merge", "--no-edit", f"origin/{feature}")
        if res.returncode == 0:
            return None
        self._run("merge", "--abort")
        return (
            f"incorporating origin/{feature} conflicted and was aborted (repo restored). "
            f"Resolve the deploy-host divergence by hand, then re-run."
        )

    def try_merge_no_ff(self, feature: str, message: str) -> str | None:
        """Atomic ``--no-ff`` merge of ``feature`` into the current branch (REQ-037 D2).

        Returns ``None`` on a clean merge. On a residual conflict, ``git merge --abort``
        restores the repo byte-identical (same HEAD, clean tree) and a non-empty *recovery
        instruction* string is returned — never an uncaught ``CalledProcessError``.
        """
        res = self._run("merge", "--no-ff", "-m", message, feature)
        if res.returncode == 0:
            return None
        self._run("merge", "--abort")
        conflicts = self._run("diff", "--name-only", "--diff-filter=U").stdout.strip()
        return (
            f"merge of '{feature}' into '{self.current_branch()}' conflicted and was "
            f"aborted (repo restored to its pre-merge state). Resolve by hand: "
            f"`git merge --no-ff {feature}`, fix the conflicts, commit, then re-run. "
            f"Conflicting paths:\n{conflicts or res.stderr.strip() or '(see git output)'}"
        )

    def try_reconcile_from_integration(
        self, integration: str, feature: str, message: str
    ) -> str | None:
        """Atomic variant of :meth:`reconcile_from_integration`: switch to ``feature`` and
        merge ``integration`` in; on conflict abort and return a recovery instruction
        (``None`` on success). Never strands the repo mid-merge (REQ-037 D2)."""
        self.switch(feature)
        res = self._run("merge", "--no-ff", "-m", message, integration)
        if res.returncode == 0:
            return None
        self._run("merge", "--abort")
        return (
            f"reconcile of '{integration}' into '{feature}' conflicted and was aborted "
            f"(repo restored). Resolve by hand then re-run `steward validate`."
        )

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
