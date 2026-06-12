"""Operator verbs that shape the queue: ``activate``, ``recover`` (REQ-026), ``rework``
(REQ-033).

Pure status mutations, kept out of the content-agnostic core:

* :func:`activate` flips a REQ from ``draft``/``dropped`` to ``open``, editing the REQ
  frontmatter **and** its ``REQUIREMENTS_INDEX.md`` row in lockstep so the index↔REQ
  same-commit invariant stays green (REQ-002, D1). It leaves both files *uncommitted*
  (D3) — declaration is committed deliberately by the operator/skill.
* :func:`recover` flips a REQ's ``FAILED`` ledger step(s) to the new ``RECOVER`` status
  (a :class:`StepStatus`, not a REQ-frontmatter status — D4) so the executor re-attempts
  them. It does not touch the working tree (D6): the failed attempt's partial edits are
  left for the resuming skill to assess.
* :func:`rework` is the human-authorized return edge from a red validation (REQ-033): on
  an in-flight REQ whose latest validation is red, it flips ``REQ-NNN:develop``
  ``DONE → RECOVER`` and ``REQ-NNN:validate`` ``BLOCKED → PENDING``, answers any open
  decision parked on the validate step, and appends a ``rework`` event carrying the red
  validation's evidence path and failure brief. It amends REQ-030 Decision 8 without
  repealing it (the engine still never auto-loops on red — this is the *recorded human
  answer* to the parked question) and, like ``recover``, touches neither git nor the REQ
  file (D5).

No verb introduces a new ``claude`` invocation or skill — the reopened work is picked up
by the existing ``/advance`` skill via the status flip (``rework`` reopens develop as
``RECOVER``, so the executor carries its usual ``--recover`` resume signal).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .core.ledger import Ledger
from .core.model import StepStatus
from .profiles.req import index as index_mod
from .profiles.req.reqfile import load_reqs, set_frontmatter_status


class LifecycleError(Exception):
    """A refusal the CLI maps to a non-zero ``ClickException``."""


# REQ-001: never weaken a finished requirement — change direction by superseding.
_REFUSE_REOPEN = {"done", "superseded"}
# A status that already produces work — activating it is a no-op, not an error.
_ALREADY_ACTIVE = {"open", "in-progress", "blocked"}


@dataclass
class ActivateResult:
    req_id: str
    old_status: str
    new_status: str
    changed: bool
    message: str


@dataclass
class RecoverResult:
    req_id: str
    steps: list[str]  # the step ids flipped FAILED -> RECOVER


@dataclass
class ReworkResult:
    req_id: str
    develop_step: str  # flipped DONE -> RECOVER
    validate_step: str  # flipped BLOCKED -> PENDING
    evidence: str | None  # the red validation's evidence dir (the repair context)
    brief: str  # the red validation's failure brief
    decision: str | None  # the parked validate decision answered, if any


def activate(cfg: Config, req_id: str) -> ActivateResult:
    """Flip ``req_id`` to ``open`` in both the REQ frontmatter and the index row (D1).

    - unknown id → :class:`LifecycleError`;
    - ``done``/``superseded`` → :class:`LifecycleError` pointing at supersede (D2);
    - already-active (``open``/``in-progress``/``blocked``) → no-op (``changed=False``);
    - ``draft``/``dropped`` → set both to ``open`` (D2: ``dropped`` is the one terminal
      that legitimately reverses). The files are left uncommitted (D3).
    """
    reqs = {r.id: r for r in load_reqs(cfg.req_dir)}
    req = reqs.get(req_id)
    if req is None:
        raise LifecycleError(f"{req_id} is not a known requirement (no REQ file found).")
    old = req.status.lower()
    if old in _REFUSE_REOPEN:
        raise LifecycleError(
            f"{req_id} is {old} — a finished requirement is never reopened. Change "
            f"direction by superseding it with a new REQ (`supersedes: {req_id}`)."
        )
    if old in _ALREADY_ACTIVE:
        return ActivateResult(
            req_id, old, old, changed=False,
            message=f"{req_id} already active ({old}) — no-op.",
        )
    # draft / dropped -> open, both files in lockstep.
    set_frontmatter_status(req.path, "open")
    index_mod.set_status(cfg.index_path, req_id, "open")
    return ActivateResult(
        req_id, old, "open", changed=True,
        message=f"activated {req_id} ({old} -> open).",
    )


def recover(ledger: Ledger, req_id: str) -> RecoverResult:
    """Flip ``req_id``'s ``FAILED`` ledger step(s) to ``RECOVER`` and record an event (D4).

    Refuses (``LifecycleError``) when the REQ has no failed step. Leaves the working tree
    as the failed attempt left it (D6) — no git is touched.
    """
    failed = sorted(
        sid for sid, st in ledger.all_statuses().items()
        if sid.startswith(f"{req_id}:") and st is StepStatus.FAILED
    )
    if not failed:
        raise LifecycleError(
            f"{req_id} has no failed step to recover "
            f"(recover only re-arms a step the executor marked failed)."
        )
    for sid in failed:
        ledger.set_status(sid, StepStatus.RECOVER)
    ledger.save()
    ledger.append_event("step_recover", req=req_id, steps=failed)
    return RecoverResult(req_id, failed)


def rework(cfg: Config, ledger: Ledger, req_id: str) -> ReworkResult:
    """Return a red validation to develop for a fix-and-revalidate cycle (REQ-033).

    On an in-flight REQ whose latest validation event is red (an artifact red or a
    *declined* manual sign-off), flip ``REQ-NNN:develop`` to ``RECOVER`` and
    ``REQ-NNN:validate`` to ``PENDING``, answer any open decision parked on the validate
    step, and append a ``rework`` event carrying the red validation's evidence path and
    failure brief. Touches neither git nor the REQ file (D5).

    Refuses (:class:`LifecycleError`, mapped to a non-zero exit by the CLI) when there is
    no red validation to rework: an unknown id, a ``done`` REQ (points at supersede — done
    is never weakened, D3), a REQ with no validate step, or a validate step that is not
    blocked on a red.
    """
    reqs = {r.id: r for r in load_reqs(cfg.req_dir)}
    req = reqs.get(req_id)
    if req is None:
        raise LifecycleError(f"{req_id} is not a known requirement (no REQ file found).")
    if req.status.lower() == "done":
        raise LifecycleError(
            f"{req_id} is done — a finished requirement's red re-validation is never "
            f"reworked (done is never weakened). Change direction by superseding it with "
            f"a new REQ (`supersedes: {req_id}`)."
        )

    develop = f"{req_id}:develop"
    validate = f"{req_id}:validate"
    # A validate step exists iff the REQ declares an artifact/manual AC (REQ-030) — read it
    # from the REQ's own acceptance block, not the ledger overlay (an untouched validate
    # step has no recorded status yet).
    if not any(c.check in ("artifact", "manual") for c in req.acceptance):
        raise LifecycleError(
            f"{req_id} has no validate step to rework — it declares no artifact/manual "
            f"acceptance criterion, so no validation can have gone red."
        )

    # The substantive test (D3, AC2): a *real* red — the latest validation event is
    # ``ok: false`` and the step is parked. A manual park that only awaits its oracle
    # records no validation event; a green/never-run validation records none or ok:true.
    latest = ledger.latest_validation(req_id)
    is_red = latest is not None and latest.get("ok") is False
    if not (is_red and ledger.status_of(validate) is StepStatus.BLOCKED):
        raise LifecycleError(
            f"{req_id} has no red validation to rework — {validate} is not blocked on a "
            f"red System-Test result. Run `steward validate {req_id}` to validate it, or "
            f"`steward recover {req_id}` if a step actually failed."
        )

    brief = "\n".join(
        r.get("detail", "") for r in latest.get("results", []) if not r.get("ok")
    ) or "validation red"
    evidence = latest.get("evidence")

    # Answer the parked validate decision (D1) — this also unblocks validate -> PENDING.
    decision_id: str | None = None
    for dec in ledger.open_decisions():
        if dec.step == validate:
            ledger.answer_decision(
                dec.id, "reworked: human returned the red validation to develop for a fix"
            )
            decision_id = dec.id
            break

    ledger.set_status(develop, StepStatus.RECOVER)
    ledger.set_status(validate, StepStatus.PENDING)
    ledger.save()
    ledger.append_event(
        "rework",
        req=req_id,
        develop=develop,
        validate=validate,
        evidence=evidence,
        brief=brief[:2000],
        decision=decision_id,
    )
    return ReworkResult(req_id, develop, validate, evidence, brief, decision_id)
