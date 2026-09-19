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
    ReworkResult,
    activate as _activate,
    plan_repeat as _plan_repeat,
    repeat as _repeat,
    rework as _rework,
)

__all__ = [
    "LifecycleError",
    "activate",
    "answer_decision",
    "repeat",
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


def repeat(cfg: Config, req_id: str, *, announce=None, stop=None) -> RepeatResult:
    """``steward repeat`` — re-arm whatever stopped the REQ (REQ-098 Decision 3).

    The classification is a pure ledger read (:func:`~devsteward.lifecycle.plan_repeat`) and
    runs **first**, because the two branches need different invariant gates: the ledger flips
    succeed regardless of HEAD (REQ-049 AC3 — a recovery must not depend on which branch is
    checked out), while the land replay commits and so keeps the strict production/mid-merge
    refusal. On the land branch the result carries the executor and the ``StepResult`` so the
    CLI can print its usual checkpoint report.
    """
    ex = build_executor(cfg, announce=announce, stop=stop)
    plan = _plan_repeat(ex.ledger, req_id)  # raises LifecycleError when nothing stopped

    if plan.lands:
        return _replay_land(ex, req_id)

    # REQ-049 AC3: a recovery verb succeeds regardless of HEAD — INV-1 (single ledger) only,
    # not the branch/tree gate — and is atomic. A LifecycleError is a graceful refusal raised
    # before any mutation, so it passes through the boundary untouched (no rollback).
    check_invariants(ex, allow_any_head=True)
    with transaction(ex.git, label=f"repeat {req_id}", pass_through=(LifecycleError,)):
        return _repeat(cfg, ex.ledger, req_id, plan=plan)


def _replay_land(ex, req_id: str) -> RepeatResult:
    """The land-replay branch of ``repeat`` — REQ-065's ``reland`` body, unchanged (D3).

    The session already ran and its artifact gate + human sign-offs are durable in the green
    ``validation`` event, so once the land formality is fixed this re-certifies that same
    green and lands — no re-spawn, no re-prompt. The routine re-runs the (now-fixed) gate as
    a final pre-flight and refuses if it is still red; that refusal is the operator's, so it
    surfaces as a :class:`LifecycleError` with the routine's own diagnostic.
    """
    from .core.executor import RunOutcome

    routine = ex.validate_runner
    if routine is None:
        raise LifecycleError("the generic profile has no validation phase")
    check_invariants(ex)  # REQ-049: refuse on production / mid-merge before any write
    # REQ-049: the replayed land is atomic — a git failure mid-commit rolls repo + ledger back.
    with transaction(ex.git, label=f"repeat {req_id} (land replay)"):
        res = routine.reland(ex, req_id, driver="interactive")
    if res.outcome in (RunOutcome.REFUSED, RunOutcome.FAILED):
        raise LifecycleError(res.detail)
    if res.outcome is RunOutcome.VERIFY_FAILED:
        raise LifecycleError(f"the land replay could not land — {res.detail}")
    return RepeatResult(
        req_id, ["reland"], [f"{req_id}:validate"], land=res, ex=ex,
    )


def rework(cfg: Config, req_id: str, *, reason: str | None = None) -> ReworkResult:
    """``steward rework`` — return a validation to develop from any unfinished state."""
    ex = build_executor(cfg)
    check_invariants(ex, allow_any_head=True)  # REQ-049 AC3: regardless of HEAD; single-ledger only
    with transaction(ex.git, label=f"rework {req_id}", pass_through=(LifecycleError,)):
        return _rework(cfg, ex.ledger, req_id, reason=reason)


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
            f"(or send it back to develop with `steward rework {req}`, or re-arm the "
            f"validation with `steward repeat {req}`)."
        )
    with transaction(ex.git, label=f"decision answer {decision_id}"):
        answered = ex.ledger.answer_decision(decision_id, answer, rationale)
    assert answered is not None  # find_decision above proved it open
    return answered
