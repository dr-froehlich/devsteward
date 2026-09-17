"""The operator's state-changing verbs as plain callables — one body per verb (REQ-097).

``steward`` exposes each verb twice: as a click command and, since REQ-097, as an action on
the dashboard. Decision 5 of that REQ fixes the rule that keeps the two surfaces from
diverging: **every state change goes through the engine's own functions — the same ones the
CLI verbs call — with the CLI's preconditions and refusals.** This module is where that
single body lives. A click command in :mod:`devsteward.cli` is a thin printer around one of
these functions, and the dashboard's route is a thin form handler around the same function.

Each function builds the executor, runs :func:`check_invariants` exactly as the CLI did
(``allow_any_head=True`` for the recovery verbs — REQ-049 AC3: a recovery must succeed
regardless of HEAD), and runs the mutation inside the universal :func:`transaction`
boundary. Graceful refusals raise :class:`LifecycleError` — the CLI maps it to a non-zero
``ClickException``, the dashboard to a flashed refusal — and never mutate anything.
Nothing here spawns a Claude session: these are ledger and file writes only.
"""

from __future__ import annotations

from .build import build_executor
from .config import Config
from .core.invariants import check_invariants
from .core.model import Decision, DecisionStatus
from .core.transaction import transaction
from .lifecycle import (
    ActivateResult,
    LifecycleError,
    RepeatResult,
    RevalidateResult,
    ReworkResult,
    activate as _activate,
    repeat as _repeat,
    revalidate as _revalidate,
    rework as _rework,
)

__all__ = [
    "LifecycleError",
    "activate",
    "answer_decision",
    "reland",
    "repeat",
    "revalidate",
    "rework",
]


def activate(cfg: Config, req_id: str) -> ActivateResult:
    """``steward activate`` — flip a draft/dropped REQ to open, frontmatter + index in lockstep."""
    ex = build_executor(cfg)
    # REQ-049: the frontmatter flip + index row move atomically (same-commit discipline — a
    # mid-edit crash must not leave them out of sync); regardless of HEAD (allow_any_head).
    check_invariants(ex, allow_any_head=True)
    with transaction(ex.git, label=f"activate {req_id}", pass_through=(LifecycleError,)):
        return _activate(cfg, req_id)


def repeat(cfg: Config, req_id: str) -> RepeatResult:
    """``steward repeat`` — re-arm a FAILED step (its partial work left intact)."""
    ex = build_executor(cfg)
    # REQ-049 AC3: a recovery verb succeeds regardless of HEAD — INV-1 (single ledger) only,
    # not the branch/tree gate — and is atomic. A LifecycleError is a graceful refusal raised
    # before any mutation, so it passes through the boundary untouched (no rollback).
    check_invariants(ex, allow_any_head=True)
    with transaction(ex.git, label=f"repeat {req_id}", pass_through=(LifecycleError,)):
        return _repeat(ex.ledger, req_id)


def rework(cfg: Config, req_id: str) -> ReworkResult:
    """``steward rework`` — return a red validation to develop, carrying the green ACs."""
    ex = build_executor(cfg)
    check_invariants(ex, allow_any_head=True)  # REQ-049 AC3: regardless of HEAD; single-ledger only
    with transaction(ex.git, label=f"rework {req_id}", pass_through=(LifecycleError,)):
        return _rework(cfg, ex.ledger, req_id)


def revalidate(cfg: Config, req_id: str) -> RevalidateResult:
    """``steward revalidate`` — re-run only the red ACs; develop stays done."""
    ex = build_executor(cfg)
    check_invariants(ex, allow_any_head=True)  # REQ-049 AC3: regardless of HEAD; single-ledger only
    with transaction(ex.git, label=f"revalidate {req_id}", pass_through=(LifecycleError,)):
        return _revalidate(cfg, ex.ledger, req_id)


def reland(cfg: Config, req_id: str, *, announce=None, stop=None):
    """``steward reland`` — replay the mechanical land after a land-gate refusal (REQ-065).

    Returns ``(executor, StepResult)`` on a landed replay so the CLI can print its report.
    A refusal, a failure or a red re-gate raises :class:`LifecycleError` with the routine's
    own diagnostic — the same text the CLI prints.
    """
    from .core.executor import RunOutcome

    ex = build_executor(cfg, announce=announce, stop=stop)
    routine = ex.validate_runner
    if routine is None:
        raise LifecycleError("the generic profile has no validation phase")
    check_invariants(ex)  # REQ-049: refuse on production / mid-merge before any write
    # REQ-049: the replayed land is atomic — a git failure mid-commit rolls repo + ledger back.
    with transaction(ex.git, label=f"reland {req_id}"):
        res = routine.reland(ex, req_id, driver="interactive")
    if res.outcome in (RunOutcome.REFUSED, RunOutcome.FAILED):
        raise LifecycleError(res.detail)
    if res.outcome is RunOutcome.VERIFY_FAILED:
        raise LifecycleError(f"reland could not land — {res.detail}")
    return ex, res


def answer_decision(
    cfg: Config, decision_id: str, answer: str, rationale: str | None = None
) -> Decision:
    """``steward decision-answer`` — record an answer against a parked fork, unblocking its step."""
    ex = build_executor(cfg)
    # REQ-049 AC3: answering a parked decision succeeds regardless of HEAD — the historical
    # stranding (a parked decision stuck on the wrong branch, no command able to recover it)
    # is unreachable: single-ledger (INV-1) only, no branch/tree gate.
    check_invariants(ex, allow_any_head=True)
    d = ex.ledger.find_decision(decision_id)
    if d is None or d.status is not DecisionStatus.OPEN:
        raise LifecycleError(f"no open decision {decision_id}")
    # REQ-057 Decision 5: a validation-phase hold is *not* a fork to answer here. A `manual`-AC
    # await (state F) or a red validation parks on a `:validate` step and has dedicated verbs.
    # Answering it would flip the validate step BLOCKED -> PENDING; unattended it re-runs, still
    # can't reach the human, and re-parks — the circular trap REQ-056 removed for D/H. Refuse
    # *before* any mutation (so the step stays BLOCKED, no re-park) and redirect to the real verb.
    if d.step.endswith(":validate"):
        req = d.req or d.step.split(":", 1)[0]
        raise LifecycleError(
            f"{decision_id} is a validation hold on {d.step}, not a fork to answer. "
            f"Record the human sign-off with `steward validate {req}` "
            f"(or, for a red validation, `steward rework {req}` / `steward revalidate {req}`)."
        )
    with transaction(ex.git, label=f"decision answer {decision_id}"):
        answered = ex.ledger.answer_decision(decision_id, answer, rationale)
    assert answered is not None  # find_decision above proved it open
    return answered
