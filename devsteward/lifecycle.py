"""Operator verbs that shape the queue: ``activate``, ``repeat`` (REQ-026, renamed from
``recover`` by REQ-054), ``rework`` (REQ-033), ``revalidate`` (REQ-055).

Pure status mutations, kept out of the content-agnostic core:

* :func:`activate` flips a REQ from ``draft``/``dropped`` to ``open``, editing the REQ
  frontmatter **and** its ``REQUIREMENTS_INDEX.md`` row in lockstep so the index↔REQ
  same-commit invariant stays green (REQ-002, D1). It leaves both files *uncommitted*
  (D3) — declaration is committed deliberately by the operator/skill.
* :func:`repeat` flips a REQ's ``FAILED`` ledger step(s) to the ``RECOVER`` status
  (a :class:`StepStatus`, not a REQ-frontmatter status — D4) so the executor re-attempts
  them. It does not touch the working tree (D6): the failed attempt's partial edits are
  left for the resuming skill to assess. The verb is named for its dominant use — the
  work was sound and an external cause failed the step, so the action is *run it again*
  (REQ-054); the internal ``RECOVER`` status symbol keeps its name (REQ-054 D4).
* :func:`rework` is the human-authorized return edge from a red validation (REQ-033): on
  an in-flight REQ whose latest validation is red, it flips ``REQ-NNN:develop``
  ``DONE → RECOVER`` and ``REQ-NNN:validate`` ``BLOCKED → PENDING``, answers any open
  decision parked on the validate step, and appends a ``rework`` event carrying the red
  validation's evidence path and failure brief. It amends REQ-030 Decision 8 without
  repealing it (the engine still never auto-loops on red — this is the *recorded human
  answer* to the parked question) and, like ``repeat``, touches neither git nor the REQ
  file (D5).

* :func:`revalidate` is the validate-layer mirror of ``rework`` (REQ-055): the
  **external-cause** return edge. When a red validation was caused by something outside the
  work (a broken lab fixture, a missing credential, a downed host) that the human then
  fixed, the develop *stands* — so it flips ``REQ-NNN:validate`` ``BLOCKED → PENDING`` while
  leaving ``REQ-NNN:develop`` at ``DONE``, answers the parked decision, and appends a
  ``revalidate`` event. Same precondition as ``rework``, opposite action; like it, touches
  neither git nor the REQ file.

No verb introduces a new ``claude`` invocation or skill — the reopened work is picked up
by the existing ``/advance`` skill via the status flip (``rework`` reopens develop as
``RECOVER``, so the executor carries its usual ``--repeat`` resume signal; ``revalidate``
re-arms only validate, which ``steward validate`` / ``steward run`` then re-runs).
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
class RepeatResult:
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


@dataclass
class RevalidateResult:
    req_id: str
    validate_step: str  # flipped BLOCKED -> PENDING (develop is left untouched at DONE)
    evidence: str | None  # the red validation's evidence dir
    brief: str  # the red validation's failure brief
    decision: str | None  # the parked validate decision answered, if any
    scope: list[str] | None  # the red/unrecorded AC ids to re-capture; None = full re-run
    carried: list[dict] | None  # per carried green AC {ac, check, source_evidence, ...}


def _scope_revalidation(
    req, latest_validation: dict | None
) -> tuple[list[str] | None, list[dict] | None]:
    """Red-only re-open (REQ-075 AC1/Decision 1): split the REQ's ``artifact``/``manual`` ACs
    into the set to **re-capture** and the green set to **carry forward**, from the red
    validation's per-AC results.

    An AC is carried iff the red validation recorded it green; a red or *unrecorded* AC is
    re-opened. Degenerate cases collapse to today's full re-run — no per-AC results, or
    *every* declared AC red → ``(None, None)``, the caller then omits the scope entirely.

    Returns ``(scope_ids, carried)`` where ``carried`` names, per green AC, the source
    evidence path + originating validation event (its ``ts``) and, for a ``manual`` AC, the
    recorded sign-off — the provenance the next run's validation event will carry.
    """
    declared = [c for c in req.acceptance if c.check in ("artifact", "manual")]
    if latest_validation is None or not declared:
        return None, None
    recorded = {
        r.get("ac"): r
        for r in latest_validation.get("results", [])
        if r.get("ac") not in (None, "-")
    }
    source_evidence = latest_validation.get("evidence")
    source_event = latest_validation.get("ts")
    signoffs = {s.get("ac"): s for s in latest_validation.get("signoffs", [])}

    scope_ids: list[str] = []
    carried: list[dict] = []
    for c in declared:
        rec = recorded.get(c.id)
        if rec is not None and rec.get("ok"):
            entry = {
                "ac": c.id,
                "check": c.check,
                "source_evidence": source_evidence,
                "source_event": source_event,
            }
            if c.check == "manual" and c.id in signoffs:
                entry["signoff"] = signoffs[c.id]
            carried.append(entry)
        else:
            scope_ids.append(c.id)
    # No green set → nothing to scope down to / carry: a full re-run, today's behavior.
    if not carried:
        return None, None
    return scope_ids, carried


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


def repeat(ledger: Ledger, req_id: str) -> RepeatResult:
    """Flip ``req_id``'s ``FAILED`` ledger step(s) to ``RECOVER`` and record an event (D4).

    Refuses (``LifecycleError``) when the REQ has no failed step. Leaves the working tree
    as the failed attempt left it (D6) — no git is touched. The internal status symbol and
    the ``step_recover`` event name are unchanged (REQ-054 D4); only the operator verb is.
    """
    failed = sorted(
        sid for sid, st in ledger.all_statuses().items()
        if sid.startswith(f"{req_id}:") and st is StepStatus.FAILED
    )
    if not failed:
        raise LifecycleError(
            f"{req_id} has no failed step to repeat "
            f"(repeat only re-arms a step the executor marked failed)."
        )
    for sid in failed:
        ledger.set_status(sid, StepStatus.RECOVER)
    ledger.save()
    ledger.append_event("step_recover", req=req_id, steps=failed)
    return RepeatResult(req_id, failed)


def _resolve_red_validation(cfg: Config, ledger: Ledger, req_id: str, *, verb: str):
    """Shared precondition for the two red-validation return edges (``rework`` /
    ``revalidate``): resolve the REQ and assert a *real* red parked on its validate step.

    Returns ``(validate_step, brief, evidence)`` on success. Raises :class:`LifecycleError`
    (CLI → non-zero) on the identical refusal taxonomy both verbs share: an unknown id, a
    ``done`` REQ (points at supersede — done is never weakened, D3), a REQ with no validate
    step, or a validate step not ``BLOCKED`` on a red. ``verb`` only shapes the message.
    """
    reqs = {r.id: r for r in load_reqs(cfg.req_dir)}
    req = reqs.get(req_id)
    if req is None:
        raise LifecycleError(f"{req_id} is not a known requirement (no REQ file found).")
    if req.status.lower() == "done":
        raise LifecycleError(
            f"{req_id} is done — a finished requirement's red re-validation is never "
            f"{verb}ed (done is never weakened). Change direction by superseding it with "
            f"a new REQ (`supersedes: {req_id}`)."
        )

    validate = f"{req_id}:validate"
    # A validate step exists iff the REQ declares an artifact/manual AC (REQ-030) — read it
    # from the REQ's own acceptance block, not the ledger overlay (an untouched validate
    # step has no recorded status yet).
    if not any(c.check in ("artifact", "manual") for c in req.acceptance):
        raise LifecycleError(
            f"{req_id} has no validate step to {verb} — it declares no artifact/manual "
            f"acceptance criterion, so no validation can have gone red."
        )

    # The substantive test (D3, AC2): a *real* red — the latest validation event is
    # ``ok: false`` and the step is parked. A manual park that only awaits its oracle
    # records no validation event; a green/never-run validation records none or ok:true.
    latest = ledger.latest_validation(req_id)
    is_red = latest is not None and latest.get("ok") is False
    if not (is_red and ledger.status_of(validate) is StepStatus.BLOCKED):
        raise LifecycleError(
            f"{req_id} has no red validation to {verb} — {validate} is not blocked on a "
            f"red System-Test result. Run `steward validate {req_id}` to validate it, or "
            f"`steward repeat {req_id}` if a step actually failed."
        )

    brief = "\n".join(
        r.get("detail", "") for r in latest.get("results", []) if not r.get("ok")
    ) or "validation red"
    return validate, brief, latest.get("evidence")


def _answer_validate_decision(ledger: Ledger, validate: str, answer: str) -> str | None:
    """Answer any open decision parked on ``validate`` (D1) — this is what unblocks the
    step. Returns the answered decision id, or ``None`` if none was parked."""
    for dec in ledger.open_decisions():
        if dec.step == validate:
            ledger.answer_decision(dec.id, answer)
            return dec.id
    return None


def rework(cfg: Config, ledger: Ledger, req_id: str) -> ReworkResult:
    """Return a red validation to develop for a fix-and-revalidate cycle (REQ-033) — the
    **internal-cause** edge: the develop was hollow, so reopen it.

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
    validate, brief, evidence = _resolve_red_validation(
        cfg, ledger, req_id, verb="rework"
    )
    develop = f"{req_id}:develop"

    decision_id = _answer_validate_decision(
        ledger, validate,
        "reworked: human returned the red validation to develop for a fix",
    )

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


def revalidate(cfg: Config, ledger: Ledger, req_id: str) -> RevalidateResult:
    """Re-arm a red validation without redoing develop (REQ-055) — the **external-cause**
    mirror of :func:`rework`: a broken lab fixture / missing credential / downed host was
    fixed, the develop work *stands*, so re-run the validation only.

    Same precondition as ``rework`` (an in-flight REQ parked on a *red* validation),
    opposite action: flip ``REQ-NNN:validate`` ``BLOCKED → PENDING`` while **leaving
    ``REQ-NNN:develop`` untouched at ``DONE``**, answer any open decision parked on the
    validate step, and append a ``revalidate`` event carrying the red validation's evidence
    path and failure brief. Touches neither git nor the REQ file (D1/D4).

    Refuses (:class:`LifecycleError`) on the identical taxonomy as ``rework`` (D2): an
    unknown id, a ``done`` REQ (→ supersede), a REQ with no validate step, or a validate
    step not blocked on a red.
    """
    validate, brief, evidence = _resolve_red_validation(
        cfg, ledger, req_id, verb="revalidate"
    )

    decision_id = _answer_validate_decision(
        ledger, validate,
        "revalidated: external cause fixed, develop stands — re-running validation only",
    )

    # REQ-075 AC1: scope the re-run to only the red/unrecorded ACs, carrying the green
    # one-offs forward (Decision 1/2). Degenerate cases (no per-AC results / all red)
    # return None and the event omits scope — a full re-run, exactly today's behavior.
    req = next((r for r in load_reqs(cfg.req_dir) if r.id == req_id), None)
    scope, carried = _scope_revalidation(req, ledger.latest_validation(req_id))

    # The whole point of the mirror: develop is left at DONE (D1). Only validate re-arms.
    ledger.set_status(validate, StepStatus.PENDING)
    ledger.save()
    event_fields = dict(
        req=req_id,
        validate=validate,
        evidence=evidence,
        brief=brief[:2000],
        decision=decision_id,
    )
    if scope is not None:
        event_fields["scope"] = scope
        event_fields["carried"] = carried
    ledger.append_event("revalidate", **event_fields)
    return RevalidateResult(req_id, validate, evidence, brief, decision_id, scope, carried)
