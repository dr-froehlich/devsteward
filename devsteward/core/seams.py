"""The four pluggable seams that keep the core content-agnostic.

* :class:`StepSource` — *what are the steps, in what dependency order.*
  Generic profile = an explicit list; REQ profile = derived from REQ files.
* :class:`Verifier` — *did it succeed.* Runs named acceptance tests; green ⇒ done.
* :class:`DecisionGate` — *what to do at a fork.* Park-and-surface when unattended.
* :class:`AccountProvider` — *which credentials / quota.* claude-swap, or single-account.

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
