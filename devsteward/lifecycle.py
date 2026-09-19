"""Operator verbs that shape the queue: ``activate``, ``repeat`` (REQ-026, renamed from
``recover`` by REQ-054) and ``rework`` (REQ-033).

Pure status mutations, kept out of the content-agnostic core:

* :func:`activate` flips a REQ from ``draft``/``dropped`` to ``open``, editing the REQ
  frontmatter **and** its ``REQUIREMENTS_INDEX.md`` row in lockstep so the index↔REQ
  same-commit invariant stays green (REQ-002, D1). It leaves both files *uncommitted*
  (D3) — declaration is committed deliberately by the operator/skill.
* :func:`repeat` — *run the same step again.* It re-arms whatever stopped the REQ, reading
  the ledger to decide which body applies (REQ-098 Decision 3): a ``FAILED`` step goes back
  to ``RECOVER`` (REQ-026/054), a validate step parked on a **red** re-arms with REQ-075's
  scope and the green ACs carried forward, a validate step parked on a **manual hold**
  re-arms for a full run, and a validate step ``FAILED`` by a land-gate refusal after a
  *green* validation replays that recorded land (REQ-065). It does not touch the working
  tree (D6): a failed attempt's partial edits are left for the resuming skill to assess.
* :func:`rework` — *go back to the previous step.* The human-authorized return edge from
  the validate step to develop (REQ-033): it flips ``REQ-NNN:develop`` ``DONE → RECOVER``
  and ``REQ-NNN:validate`` → ``PENDING``, answers any decision parked on the validate step,
  and appends a ``rework`` event carrying a repair brief. Touches neither git nor the REQ
  file (D5).

**REQ-098 — two moves, not four.** ``steward revalidate`` and ``steward reland`` are gone.
Their bodies are not: they live inside :func:`repeat`, reached by reading the ledger rather
than by making the operator recognise a state and name a verb. Two facts changed with them.
(1) ``rework`` no longer demands a *real red* — REQ-033 Decision 3 and REQ-055 Decision 2
scoped both return edges to "in-flight reds only", and the guard turned out to protect
nothing: the red it demanded carried no information the operator did not already have, so
they paid for a validation whose verdict they knew in order to type the verb they wanted.
It now returns a validate step from **any state except done** (Decision 2). (2) ``rework``
takes an optional ``reason`` (Decision 4) — without a red there is no System-Tester
write-up, so the operator's one line is the resuming session's only repair context.

The **ledger event vocabulary is unchanged** (Decision 5): ``repeat`` still writes
``step_recover`` for a failed step, ``revalidate`` for a validate re-arm and ``reland`` for
a land replay; ``rework`` still writes ``rework``. Existing consumer ledgers must keep
replaying — the event names are the engine's, the verb names are the operator's.

No verb introduces a new ``claude`` invocation or skill — the reopened work is picked up by
the existing ``/advance`` skill via the status flip (``rework`` reopens develop as
``RECOVER``, so the executor carries its usual ``--repeat`` resume signal; a validate re-arm
is re-run by ``steward validate`` / ``steward run``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

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

#: What a ``rework`` event says when no red validation and no ``--reason`` supplied a brief
#: (REQ-098 Decision 4). The resuming ``/advance`` session reads it as its only context.
DEFAULT_REWORK_BRIEF = "returned to develop by the operator"


@dataclass
class ActivateResult:
    req_id: str
    old_status: str
    new_status: str
    changed: bool
    message: str


@dataclass
class RepeatPlan:
    """What :func:`repeat` would do to ``req_id``, read from the ledger (REQ-098 D3).

    A pure read, so the caller can pick the right invariant gate *before* anything mutates:
    the ledger flips succeed regardless of HEAD (REQ-049 AC3), while the land replay commits
    and so keeps the strict production/mid-merge refusal.
    """

    req_id: str
    #: ``FAILED`` steps to re-arm to ``RECOVER``. Never contains the land-replay step.
    failed: list[str] = field(default_factory=list)
    #: The validate step this plan re-arms or lands, when it touches one.
    validate: str | None = None
    #: ``revalidate`` (parked on a red) | ``unhold`` (parked on a manual hold) |
    #: ``reland`` (a recorded green to replay) | ``None`` (failed steps only).
    mode: str | None = None

    @property
    def lands(self) -> bool:
        """True when this repeat replays a recorded green land (REQ-065's body)."""
        return self.mode == "reland"


@dataclass
class RepeatResult:
    req_id: str
    #: What the verb did, in the order it did it: ``recover`` | ``revalidate`` |
    #: ``unhold`` | ``reland``. A repeat may do more than one (a REQ can hold a failed
    #: develop *and* a stopped validate; the executor's dependency order runs develop first).
    kinds: list[str]
    #: Every step id this verb moved.
    steps: list[str]
    #: The subset flipped ``FAILED -> RECOVER`` — what the "run it again" line names.
    recovered: list[str] = field(default_factory=list)
    evidence: str | None = None  # the red validation's evidence dir, red branch only
    brief: str = ""  # the red validation's failure brief, red branch only
    decision: str | None = None  # the parked validate decision answered, if any
    scope: list[str] | None = None  # the red/unrecorded AC ids to re-capture
    carried: list[dict] | None = None  # per carried green AC {ac, check, source_evidence, …}
    #: The land replay's :class:`~devsteward.core.executor.StepResult` and the executor that
    #: produced it — filled by :func:`devsteward.verbs.repeat` on the ``reland`` branch only,
    #: because replaying a land needs the executor this module deliberately does not build.
    land: object | None = None
    ex: object | None = None


@dataclass
class ReworkResult:
    req_id: str
    develop_step: str  # flipped DONE -> RECOVER
    validate_step: str  # flipped -> PENDING (any hold cleared by the transition)
    evidence: str | None  # the red validation's evidence dir, when a red exists
    brief: str  # the --reason, else the red's failure brief, else the default text
    decision: str | None  # the parked validate decision answered, if any
    scope: list[str] | None  # the red/unrecorded AC ids to re-capture; None = full re-run
    carried: list[dict] | None  # per carried green AC {ac, check, source_evidence, ...}
    #: The validate status the return edge started from — what the operator went back *from*.
    from_status: str = ""


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


# -- shared reads ---------------------------------------------------------------------


def _load_req(cfg: Config, req_id: str):
    req = next((r for r in load_reqs(cfg.req_dir) if r.id == req_id), None)
    if req is None:
        raise LifecycleError(f"{req_id} is not a known requirement (no REQ file found).")
    return req


def _declares_validation(req) -> bool:
    """A validate step exists iff the REQ declares an ``artifact``/``manual`` AC (REQ-030).

    Read from the REQ's own acceptance block, not the ledger overlay — an untouched validate
    step has no recorded status yet.
    """
    return any(c.check in ("artifact", "manual") for c in req.acceptance)


def _red_park(ledger: Ledger, req_id: str, validate: str) -> dict | None:
    """The red validation a return edge may carry, or ``None``.

    A *park* is both halves: the latest validation event is ``ok: false`` **and** the step
    sits ``BLOCKED`` on it. A ``FAILED`` validate step is not a park however red its history
    — its partial attempt is tree state the ``repeat`` doctrine leaves alone, so REQ-098
    routes it through the plain re-arm rather than the carry (REQ-098, the `rework` section).
    """
    latest = ledger.latest_validation(req_id)
    if latest is None or latest.get("ok") is not False:
        return None
    if ledger.status_of(validate) is not StepStatus.BLOCKED:
        return None
    return latest


def _red_brief(latest: dict) -> str:
    return "\n".join(
        r.get("detail", "") for r in latest.get("results", []) if not r.get("ok")
    ) or "validation red"


def _green_then_refused(ledger: Ledger, req_id: str) -> bool:
    """A validate step left ``FAILED`` by a land-gate refusal *after* a green validation —
    the land replay's precondition (REQ-065 Decision 4), read here so :func:`repeat` can
    route to it. Mirrors ``ReqValidateRoutine.reland``'s own scan, so the verb and the
    routine can never disagree about which shape qualifies."""
    validate = f"{req_id}:validate"
    green = refused = None
    for ev in ledger.events():
        if (
            ev.get("event") == "validation"
            and ev.get("req") == req_id
            and ev.get("ok") is True
        ):
            green = ev.get("ts")
        elif ev.get("event") == "land_refused" and ev.get("step") == validate:
            refused = ev.get("ts")
    return bool(green and refused and refused >= green)


def _answer_validate_decision(ledger: Ledger, validate: str, answer: str) -> str | None:
    """Answer any open decision parked on ``validate`` (D1) — this is what unblocks the
    step. Returns the answered decision id, or ``None`` if none was parked."""
    for dec in ledger.open_decisions():
        if dec.step == validate:
            ledger.answer_decision(dec.id, answer)
            return dec.id
    return None


# -- repeat: run the same step again --------------------------------------------------


def plan_repeat(ledger: Ledger, req_id: str) -> RepeatPlan:
    """Read what stopped ``req_id`` and name the body that re-arms it (REQ-098 D3).

    A pure read — nothing mutates here. The cases, in the order they are recognised:

    * every ``FAILED`` step of the REQ → ``RECOVER`` (REQ-026/054);
    * *unless* the only stopped step is a validate step whose last events are a green
      validation followed by a ``land_refused`` → the land replay (REQ-065). The land replay
      is exclusive on purpose: re-certifying a green while a *develop* step sits failed would
      land work the gate has not seen, so a REQ stopped in both places takes the plain
      re-arm and reaches the replay on the next repeat;
    * a validate step ``BLOCKED`` on a red → ``PENDING`` with REQ-075's scope (``revalidate``);
    * a validate step ``BLOCKED`` on a manual hold → ``PENDING``, hold cleared (``unhold``).

    Refuses when nothing stopped: every step ``DONE``, ``PENDING``, ``RECOVER`` or
    ``RUNNING``. ``PENDING`` is the honest boundary — a validation that was never started has
    not stopped, it has not begun, and its forward path is ``steward validate``.
    """
    validate = f"{req_id}:validate"
    statuses = ledger.all_statuses()
    failed = sorted(
        sid for sid, st in statuses.items()
        if sid.startswith(f"{req_id}:") and st is StepStatus.FAILED
    )
    mode: str | None = None
    val_status = statuses.get(validate)

    if val_status is StepStatus.FAILED:
        if failed == [validate] and _green_then_refused(ledger, req_id):
            return RepeatPlan(req_id, [], validate, "reland")
    elif val_status is StepStatus.BLOCKED:
        mode = "revalidate" if _red_park(ledger, req_id, validate) else "unhold"

    if not failed and mode is None:
        raise LifecycleError(
            f"{req_id} has nothing to repeat — no failed step, and its validate step is "
            f"neither held nor parked on a red. `steward repeat` re-arms a step that "
            f"stopped; to send a validation back to develop use `steward rework {req_id}`."
        )
    return RepeatPlan(req_id, failed, validate if mode else None, mode)


def repeat(
    cfg: Config, ledger: Ledger, req_id: str, *, plan: RepeatPlan | None = None
) -> RepeatResult:
    """Re-arm whatever stopped ``req_id`` and record the matching event (REQ-098 D3).

    ``plan`` lets the caller pass the classification it already computed (see
    :func:`plan_repeat`) so the ledger is read once. The land-replay mode is **not** applied
    here: replaying a land needs the executor, which this module deliberately does not build
    — :func:`devsteward.verbs.repeat` owns that branch.

    The working tree is never touched (D6) and neither is the REQ file: a failed attempt's
    partial edits stay for the resuming skill to assess. The internal ``RECOVER`` status
    symbol and the ``step_recover`` / ``revalidate`` event names are unchanged (REQ-054 D4,
    REQ-098 D5); only the operator verb is.
    """
    plan = plan or plan_repeat(ledger, req_id)
    if plan.lands:
        raise LifecycleError(
            f"{req_id}'s repeat is a land replay — it needs the executor, so it is applied "
            f"by `devsteward.verbs.repeat`, not by this function."
        )

    kinds: list[str] = []
    moved: list[str] = []
    evidence: str | None = None
    brief = ""
    decision: str | None = None
    scope: list[str] | None = None
    carried: list[dict] | None = None

    if plan.failed:
        for sid in plan.failed:
            ledger.set_status(sid, StepStatus.RECOVER)
        kinds.append("recover")
        moved.extend(plan.failed)

    if plan.mode in ("revalidate", "unhold"):
        validate = plan.validate
        assert validate is not None  # plan.mode implies a validate step
        if plan.mode == "revalidate":
            latest = ledger.latest_validation(req_id)
            assert latest is not None  # _red_park proved it
            evidence = latest.get("evidence")
            brief = _red_brief(latest)
            # REQ-075 AC1: scope the re-run to the red/unrecorded ACs, carrying the green
            # one-offs forward. Degenerate cases (no per-AC results / all red) return None
            # and the event omits the scope — a full re-run.
            scope, carried = _scope_revalidation(
                _load_req(cfg, req_id), latest
            )
            answer = (
                "repeated: the red validation was re-armed — develop stands, "
                "the validation runs again"
            )
        else:
            brief = "held validation re-armed by the operator — a full re-run"
            answer = "repeated: the held validation was re-armed for a full re-run"
        # REQ-074: the transition itself clears the hold note.
        ledger.set_status(validate, StepStatus.PENDING)
        decision = _answer_validate_decision(ledger, validate, answer)
        kinds.append(plan.mode)
        moved.append(validate)

    ledger.save()

    if plan.failed:
        ledger.append_event("step_recover", req=req_id, steps=plan.failed)
    if plan.mode in ("revalidate", "unhold"):
        event_fields = dict(
            req=req_id,
            validate=plan.validate,
            evidence=evidence,
            brief=brief[:2000],
            decision=decision,
        )
        if scope is not None:
            event_fields["scope"] = scope
            event_fields["carried"] = carried
        ledger.append_event("revalidate", **event_fields)

    return RepeatResult(
        req_id, kinds, moved, list(plan.failed),
        evidence, brief, decision, scope, carried,
    )


# -- rework: go back to the previous step ----------------------------------------------


def _resolve_rework_target(cfg: Config, ledger: Ledger, req_id: str) -> tuple[str, str]:
    """``rework``'s precondition is a **state**, not a red (REQ-098 Decision 2).

    Returns ``(develop_step, validate_step)``. Raises :class:`LifecycleError` (CLI →
    non-zero, nothing mutated) on the four refusals: an unknown id, a ``done`` REQ (points at
    supersede — done is never weakened, REQ-001), a REQ with no validate step, a develop step
    that is not ``DONE`` (there is nothing to go *back* from — that is ``repeat``'s move), and
    a validate step that is ``RUNNING`` (someone's live session) or ``DONE``.

    This withdraws the "real red" precondition REQ-033 Decision 3 and REQ-055 Decision 2
    recorded. Those decisions were made with the red case in view and without the
    never-started / held case in hand; living with them showed the guard cost a validation
    whose verdict the operator already knew and protected nothing.
    """
    req = _load_req(cfg, req_id)
    if req.status.lower() == "done":
        raise LifecycleError(
            f"{req_id} is done — a finished requirement is never returned to develop (done "
            f"is never weakened). Change direction by superseding it with a new REQ "
            f"(`supersedes: {req_id}`)."
        )
    if not _declares_validation(req):
        raise LifecycleError(
            f"{req_id} has no validate step to rework — it declares no artifact/manual "
            f"acceptance criterion, so there is no validation to return to develop."
        )

    develop, validate = f"{req_id}:develop", f"{req_id}:validate"
    dev_status = ledger.status_of(develop)
    if dev_status is not StepStatus.DONE:
        raise LifecycleError(
            f"{develop} is {dev_status.value} — rework returns a *validation* to develop, "
            f"and this develop step is not closed, so there is nothing to go back from. "
            f"Work it (`/advance {req_id} develop`), or re-arm it with "
            f"`steward repeat {req_id}` if it failed."
        )

    val_status = ledger.status_of(validate)
    if val_status is StepStatus.RUNNING:
        raise LifecycleError(
            f"{validate} is running — a validation in flight is not returned to develop. "
            f"Record its verdict (`steward validate-record {req_id}`) or let the session "
            f"finish, then rework."
        )
    if val_status is StepStatus.DONE:
        raise LifecycleError(
            f"{validate} is done — its validation already landed, and a landed validation "
            f"is never weakened. Change direction by superseding {req_id} with a new REQ."
        )
    return develop, validate


def rework(
    cfg: Config, ledger: Ledger, req_id: str, *, reason: str | None = None
) -> ReworkResult:
    """*Go back to the previous step* — return ``req_id``'s validation to develop (REQ-033,
    widened by REQ-098 Decision 2).

    Flips ``REQ-NNN:develop`` ``DONE → RECOVER`` and ``REQ-NNN:validate`` → ``PENDING``
    (which clears any hold, REQ-074), answers any decision parked on the validate step, and
    appends a ``rework`` event. Works from **every unfinished validate state** — never
    started, blocked on a manual hold, blocked on a red, or failed — because in the fused
    model (REQ-029) "go back" only ever means validate → develop, and which of those states
    the step is in changes nothing about what the operator wants. Touches neither git nor the
    REQ file (D5).

    **What the event carries** (REQ-098 Decision 4). ``brief`` is ``reason`` when given, else
    the red validation's failure brief when a red exists, else
    :data:`DEFAULT_REWORK_BRIEF`. ``evidence`` is present only when a red validation recorded
    one; ``scope``/``carried`` are written only when a red exists. So the resuming
    ``/advance`` session reads the System Tester's evidence dir when there is one and the
    operator's line when there is not — it is never sent back knowing only that it was.

    **REQ-089 Decision 6 — the carry.** The operator's real workflow is: a red pauses a long
    manual walkthrough, a develop session fixes the cause, and the *same* validation resumes
    without re-walking what already passed. So a red rework runs REQ-075's
    :func:`_scope_revalidation` and writes ``scope`` + ``carried`` onto its event;
    :func:`~devsteward.profiles.req.validate._pending_revalidate` reads a scope-bearing
    ``rework`` exactly as it reads a ``revalidate``. The carry is **unconditional**
    (Decision 7) — every AC the red validation recorded green carries, with no per-AC opt-out.
    Its accepted hazard is a sign-off of code the fix then changed; the defence is provenance
    (``source_evidence`` + ``source_event`` on each carried AC) and the
    ``scoped re-run (REQ-075): …`` announcement the resumed session prints *before* the
    walkthrough. A rework from a hold or a never-started step carries nothing, so it adds no
    new exposure.
    """
    develop, validate = _resolve_rework_target(cfg, ledger, req_id)
    from_status = ledger.status_of(validate)

    red = _red_park(ledger, req_id, validate)
    evidence = red.get("evidence") if red else None
    if reason:
        brief = reason
    elif red:
        brief = _red_brief(red)
    else:
        brief = DEFAULT_REWORK_BRIEF

    decision_id = _answer_validate_decision(
        ledger, validate,
        "reworked: operator returned the validation to develop for a fix",
    )

    scope, carried = (
        _scope_revalidation(_load_req(cfg, req_id), red) if red else (None, None)
    )

    ledger.set_status(develop, StepStatus.RECOVER)
    ledger.set_status(validate, StepStatus.PENDING)
    ledger.save()
    event_fields = dict(
        req=req_id,
        develop=develop,
        validate=validate,
        evidence=evidence,
        brief=brief[:2000],
        decision=decision_id,
    )
    if scope is not None:
        event_fields["scope"] = scope
        event_fields["carried"] = carried
    ledger.append_event("rework", **event_fields)
    return ReworkResult(
        req_id, develop, validate, evidence, brief, decision_id, scope, carried,
        from_status.value,
    )
