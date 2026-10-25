"""Typed engine errors that always carry a one-line operator recovery (REQ-049).

REQ-047 Decision 3/4: the firefighting loop's *stranding* failure was a raw
``CalledProcessError`` escaping a mutating command and leaving a half-state with no
recovery verb. The universal transaction boundary (:mod:`devsteward.core.transaction`) and
the central invariants (:mod:`devsteward.core.invariants`) convert every such edge into one
of two typed errors — each carrying ``.recovery``, the single legible instruction the CLI
prints. No raw ``CalledProcessError`` ever reaches the user.

* :class:`PreconditionError` — raised *before* any mutation, by ``check_invariants``: the
  command refused to start (on ``main``, mid-merge/rebase, a stray second ledger). Nothing
  was touched; the recovery says how to make the precondition hold.
* :class:`RecoverableError` — raised *after* a rollback, by the transaction boundary: a
  mutation failed mid-flight and the repo + ledger were restored to the pre-command
  snapshot. The recovery says the state is clean and to fix-and-re-run.
"""

from __future__ import annotations


class StewardError(Exception):
    """Base for the two typed engine errors — each carries an operator ``recovery`` line."""

    def __init__(self, message: str, *, recovery: str):
        super().__init__(message)
        self.recovery = recovery


class PreconditionError(StewardError):
    """A mutation refused to start because an invariant did not hold (INV-1/INV-2).

    Raised by ``check_invariants`` *before* any mutation, so nothing is half-applied; the
    repo and ledger are exactly as the command found them.
    """


class RecoverableError(StewardError):
    """A mutation failed mid-flight and was rolled back to the pre-command snapshot (INV-3).

    Raised by the transaction boundary after restoring ``ORIG_HEAD`` — the failure became a
    clean abort, never a stalemate. Chains from the original exception (``raise … from``).
    """
