"""The four pluggable seams that keep the core content-agnostic.

* :class:`StepSource` — *what are the steps, in what dependency order.*
  Generic profile = an explicit list; REQ profile = derived from REQ files.
* :class:`Verifier` — *did it succeed.* Runs named acceptance tests; green ⇒ done.
* :class:`DecisionGate` — *what to do at a fork.* Park-and-surface when unattended.
* :class:`AccountProvider` — *which credentials / quota.* Delegates the budget gate to the
  external ``clauder`` CLI (REQ-058), or single-account.
* :class:`GitTopology` — *trunk-based git access (REQ-048).* Read the current branch (the
  only guard left is "never commit on ``main``") and make the code + ledger commits on the
  integration branch; real ``git`` (``GitCli``) or an in-memory fake.

These are :class:`typing.Protocol` classes: any object with the right methods qualifies,
so profiles and tests can supply plain stand-ins without inheritance.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable

from .ledger import Ledger
from .model import Step


@runtime_checkable
class StepSource(Protocol):
    """Produces the steps for a project, in no particular order (the executor sorts by
    dependency)."""

    def steps(self, ledger: Ledger) -> list[Step]:
        ...


@runtime_checkable
class Verifier(Protocol):
    """Runs a step's acceptance tests. Returns ``(ok, detail)``."""

    def verify(self, step: Step) -> tuple[bool, str]:
        ...


@runtime_checkable
class AccountProvider(Protocol):
    """Supplies the argv prefix for an account/quota-aware ``claude`` invocation, and
    answers whether there is quota to proceed.

    **Optional budget oracle (REQ-080).** A provider *may* also offer
    ``budget_verdict() -> (BudgetVerdict, reason)`` — a single non-waiting probe of the
    budget — plus a ``wait_count`` counting the gate waits it has actually slept through
    (:class:`devsteward.core.accounts.ClauderAccountProvider` does both). The executor reads
    them via ``getattr`` and degrades to "no oracle" when absent, so a minimal provider like
    :class:`~devsteward.core.accounts.SingleAccountProvider` implements neither and simply
    never rides out a mid-run limit. Deliberately kept off the required protocol: waiting out
    a budget window is a *clauder-backed* capability, not something every provider can claim.
    """

    def precheck(self) -> tuple[bool, str]:
        """Return ``(ok, reason)``. ``ok=False`` means stop (out of quota)."""

    def claude_argv(self) -> list[str]:
        """Return the argv prefix — ``["claude"]``. The provider may switch the active
        account in :meth:`precheck` (clauder/cswap are switchers), but the launch is plain."""


@runtime_checkable
class GitTopology(Protocol):
    """Trunk-based git access for the executor (REQ-048).

    The engine works on one branch (the integration branch, ``dev``): no feature branch, no
    switch, no worktree, no merge — so this seam is just *read the current branch* and *make
    the two commits*. The real implementation (:class:`devsteward.core.git.GitCli`) shells
    out to ``git``; a fake records the commits in memory so the loop runs without a checkout.
    """

    def current_branch(self) -> str:
        """The checked-out branch (the ``main``-refusal guard reads this)."""

    def head_sha(self) -> str:
        """The current ``HEAD`` commit sha (the snapshot the transaction boundary restores)."""

    def dirty_paths(self) -> set[str]:
        """Code paths (``.devsteward/`` excluded) dirty relative to ``HEAD`` — read by the
        post-land clean-tree assertion (REQ-077 guard)."""

    def commit_code(
        self, message: str, *, force_paths: Iterable[Path | str] = ()
    ) -> str | None:
        """Stage the whole dirty tree (never ``.devsteward/``) and commit; ``None`` if
        nothing staged. Deliberately unscoped (REQ-079): one engine session per repo at a
        time is doctrine, so everything dirty is this step's work.

        ``force_paths`` names paths the caller *knows* it just wrote, to be staged
        content-blind rather than on git's stat cache (REQ-088 Cause B)."""

    def write_code_tree(self) -> str | None:
        """Stage the code and serialize it to a tree sha — the capture-gate mirror of
        :meth:`commit_code`, built from the same staging routine."""

    def commit_ledger(self, message: str) -> str | None:
        """Stage and commit only ``.devsteward/``; ``None`` when the ledger is unchanged."""

    def reset_hard(self, sha: str) -> None:
        """Restore the working tree and ``HEAD`` to ``sha`` (the transaction rollback, REQ-049)."""
