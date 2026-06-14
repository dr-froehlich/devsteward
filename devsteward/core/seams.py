"""The four pluggable seams that keep the core content-agnostic.

* :class:`StepSource` — *what are the steps, in what dependency order.*
  Generic profile = an explicit list; REQ profile = derived from REQ files.
* :class:`Verifier` — *did it succeed.* Runs named acceptance tests; green ⇒ done.
* :class:`DecisionGate` — *what to do at a fork.* Park-and-surface when unattended.
* :class:`AccountProvider` — *which credentials / quota.* claude-swap, or single-account.
* :class:`GitTopology` — *the feature-branch lifecycle.* Read the current branch and
  create/switch/merge it (REQ-020); real ``git`` (``GitCli``) or an in-memory fake.

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
    """Owns the feature-branch lifecycle for implementation steps (REQ-020).

    Unlike the read-only ``branch_resolver`` it supersedes, this *mutates* topology:
    create+switch on the first ``build``/``land`` step, merge ``--no-ff`` after a green
    land. The real implementation (:class:`devsteward.core.git.GitCli`) shells out to
    ``git``; a fake models branch state in memory so the loop runs without a checkout.
    """

    def current_branch(self) -> str:
        ...

    def branch_exists(self, name: str) -> bool:
        ...

    def create_and_switch(self, name: str) -> None:
        ...

    def switch(self, name: str) -> None:
        ...

    def integration_is_ancestor(self, integration: str, feature: str) -> bool:
        """True iff ``integration`` is an ancestor of ``feature`` (no divergence)."""

    def commit_all(self, message: str) -> str | None:
        """Stage everything and commit; return the new sha, or ``None`` if clean."""

    def merge_no_ff(self, feature: str, message: str) -> None:
        ...

    def reconcile_from_integration(
        self, integration: str, feature: str, message: str
    ) -> None:
        """Switch to ``feature`` and merge ``integration`` into it (REQ-034 D5) — bring a
        behind-but-merged feature branch current so a deferred validate-land can proceed."""
