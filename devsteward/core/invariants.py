"""Central invariants, checked by every mutating command (REQ-049, REQ-047 Decision 4).

Defined once and run before any mutation — not as per-call-site guards — so a new command
inherits the guarantees for free and the firefighting loop's *enumeration* approach is
replaced with *enforcement*. :func:`check_invariants` raises :class:`PreconditionError`
(carrying a recovery line) when an invariant does not hold; nothing is mutated, so there is
nothing to roll back.

* **INV-1 — single source of truth.** The ledger is the one ``.devsteward/`` at the repo
  root; no stray *linked worktree* may exist to host a divergent second ledger (the
  divergence bug-class REQ-048 deleted; this guards its reintroduction). Enforced for
  **writes** *and* reads — the historical ``steward decision`` stranding was INV-1 unenforced
  on a write path.
* **INV-2 — no mutation on an unexpected tree.** Refuse to start a mutation on the production
  branch (folds in the old ``branch_guard``) or mid-merge / mid-rebase. The session's own
  expected dirty work-tree is fine; an *unexpected* conflicted state is a typed precondition
  with recovery text, not a crash.
* **INV-3 — atomic** is owned by the transaction boundary (:mod:`devsteward.core.transaction`),
  not here.

The recovery/decision verbs (``steward decision`` and the recovery commands) pass
``allow_any_head=True``: they must succeed *regardless of HEAD* (REQ-047 AC3), so INV-2's
branch/tree gate does not apply to them — only INV-1, the single source of truth, does. That
is precisely the stranding fix: a parked decision can always be answered, there is no "wrong
branch" for it to strand on.
"""

from __future__ import annotations

from .errors import PreconditionError
from .ledger import LEDGER_DIRNAME, STATE_FILE


def check_invariants(ex, *, allow_any_head: bool = False) -> None:
    """Raise :class:`PreconditionError` if a pre-mutation invariant does not hold.

    ``ex`` is the executor (duck-typed: ``root``, ``current_branch()``,
    ``production_branch``, ``integration_branch``). With ``allow_any_head`` only INV-1 is
    enforced — the recovery/decision verbs run regardless of branch and tree state.
    """
    _check_single_source(ex)  # INV-1, always
    if allow_any_head:
        return
    _check_not_production(ex)  # INV-2 (branch)
    _check_settled_tree(ex)  # INV-2 (no mid-merge/rebase)


def _check_single_source(ex) -> None:
    """INV-1: the ledger resolves to the one ``.devsteward/`` at the repo root — no stray
    linked worktree hosting a divergent second ledger."""
    git_dir = ex.root / ".git"
    if not git_dir.is_dir():
        return  # no real repo (the in-memory fakes / a fresh dir) — nothing to diverge
    worktrees = git_dir / "worktrees"
    if worktrees.is_dir() and any(worktrees.iterdir()):
        stray = ", ".join(sorted(p.name for p in worktrees.iterdir()))
        raise PreconditionError(
            f"a stray linked git worktree exists ({stray}) — trunk-based DevSteward keeps a "
            f"single {LEDGER_DIRNAME}/{STATE_FILE} at the repo root, and a second worktree "
            f"can host a divergent ledger",
            recovery="prune the stray worktree (`git worktree prune`) and re-run from the repo root.",
        )


def _check_not_production(ex) -> None:
    """INV-2 (branch): never mutate on the production branch — DevSteward only commits on the
    integration branch (the old ``branch_guard``, folded in)."""
    if ex.current_branch() == ex.production_branch:
        raise PreconditionError(
            f"refusing to mutate on the production branch '{ex.production_branch}' — "
            f"DevSteward never commits to production",
            recovery=(
                f"switch to the integration branch '{ex.integration_branch}' "
                f"(`git switch {ex.integration_branch}`) and re-run."
            ),
        )


def _check_settled_tree(ex) -> None:
    """INV-2 (tree): never start a mutation mid-merge or mid-rebase — an unexpected
    conflicted state is a typed precondition, not a crash one file later."""
    git_dir = ex.root / ".git"
    if not git_dir.is_dir():
        return
    if (git_dir / "MERGE_HEAD").exists():
        raise PreconditionError(
            "refusing to mutate mid-merge — a merge is in progress (MERGE_HEAD present)",
            recovery="finish the merge (`git commit`) or abort it (`git merge --abort`), then re-run.",
        )
    if (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir():
        raise PreconditionError(
            "refusing to mutate mid-rebase — a rebase is in progress",
            recovery="finish the rebase (`git rebase --continue`) or abort it (`git rebase --abort`), then re-run.",
        )
