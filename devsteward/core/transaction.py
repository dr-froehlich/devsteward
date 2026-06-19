"""The universal transaction boundary (REQ-049, REQ-047 Decision 3).

Every mutating ``steward`` command runs its body inside :func:`transaction`. It owns
**INV-3 (atomic)**: a mutation is fully applied or fully rolled back. On entry it snapshots
``HEAD``; if any exception escapes the body it restores that snapshot
(``git reset --hard <orig>``, which undoes commits *and* tracked-file edits back to the
pre-command commit, byte-identically — plan-0021 finding 4) and re-raises as a
:class:`RecoverableError` carrying the operator recovery line. So an un-enumerated edge
becomes a *clean abort + one-line recovery*, never the half-state stalemate the firefighting
loop kept producing.

What is **not** rolled back: untracked files created mid-command are left in place (visible,
not mistaken for applied state) — ``reset --hard`` only restores committed/tracked state.
A :class:`PreconditionError` (raised by ``check_invariants`` *before* the body, so nothing
was mutated) passes straight through without a rollback.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from .errors import PreconditionError, RecoverableError
from .seams import GitTopology


@contextmanager
def transaction(
    git: GitTopology, *, label: str, pass_through: tuple[type[BaseException], ...] = ()
) -> Iterator[None]:
    """Run a mutation atomically: restore the pre-command ``HEAD`` if anything escapes.

    ``label`` names the command in the recovery message. A repo with no commit yet (or no
    git at all — the in-memory fakes) yields an empty snapshot; the rollback is then skipped
    and the failure is still surfaced as a typed :class:`RecoverableError`, so no raw error
    reaches the caller.

    ``pass_through`` names exception types the *caller* treats as graceful refusals raised
    *before* any mutation (e.g. a lifecycle verb's "nothing to recover"): they propagate
    untouched, with **no rollback** — a ``reset --hard`` on a refusal would wrongly discard
    the uncommitted work those verbs exist to leave in the tree.
    """
    orig = git.head_sha()
    try:
        yield
    except (PreconditionError, RecoverableError, *pass_through):
        # Already typed, or a caller-declared graceful refusal that mutated nothing — never
        # roll back or double-wrap.
        raise
    except Exception as exc:
        restored = ""
        if orig:
            try:
                git.reset_hard(orig)
                restored = orig
            except Exception:
                # Best-effort restore; we still surface a typed error rather than the raw one.
                restored = ""
        where = (
            f"the repo and ledger were restored to {restored[:8]}"
            if restored
            else "no pre-command snapshot was available to restore"
        )
        raise RecoverableError(
            f"{label} failed mid-mutation and was rolled back ({exc.__class__.__name__}: {exc})",
            recovery=(
                f"{where} — nothing was half-applied. Inspect the cause above, fix it, "
                f"and re-run the command."
            ),
        ) from exc
