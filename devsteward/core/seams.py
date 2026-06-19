"""The four pluggable seams that keep the core content-agnostic.

* :class:`StepSource` — *what are the steps, in what dependency order.*
  Generic profile = an explicit list; REQ profile = derived from REQ files.
* :class:`Verifier` — *did it succeed.* Runs named acceptance tests; green ⇒ done.
* :class:`DecisionGate` — *what to do at a fork.* Park-and-surface when unattended.
* :class:`AccountProvider` — *which credentials / quota.* claude-swap, or single-account.
* :class:`GitTopology` — *trunk-based git access (REQ-048).* Read the current branch (the
  only guard left is "never commit on ``main``") and make the code + ledger commits on the
  integration branch; real ``git`` (``GitCli``) or an in-memory fake.

These are :class:`typing.Protocol` classes: any object with the right methods qualifies,
so profiles and tests can supply plain stand-ins without inheritance.
"""

from __future__ import annotations

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
    answers whether there is quota to proceed."""

    def precheck(self) -> tuple[bool, str]:
        """Return ``(ok, reason)``. ``ok=False`` means stop (out of quota)."""

    def claude_argv(self) -> list[str]:
        """Return the argv prefix, e.g. ``["claude"]`` or ``["cswap", "exec", "claude"]``."""


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
        """The current ``HEAD`` commit sha."""

    def commit_code(self, message: str) -> str | None:
        """Stage everything except ``.devsteward/`` and commit; ``None`` if nothing staged."""

    def commit_ledger(self, message: str) -> str | None:
        """Stage and commit only ``.devsteward/``; ``None`` when the ledger is unchanged."""
