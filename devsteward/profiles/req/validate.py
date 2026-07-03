"""REQ-030 — the System-Test (validation) phase: the REQ profile's validate routine.

The nine-hollow-REQs failure was code and tests sharing one set of hallucinated
assumptions — a coupled oracle cannot disconfirm. This phase decouples it: a fresh
**System Tester** session that never sees the builder's diff preps the lab and captures
artifacts, then the **engine** runs each ``artifact`` AC's named test command itself and
consumes only that pass/fail signal — the session can never talk the gate green
(Decision 2, symmetric with the develop gate). ``manual`` ACs are a decision stop: the
human supplies the verdict, the engine composes the provenance (Decision 4).

Validation is a **recorded evidence event**, not a regression-suite member (Decision 3):
captured artifacts live under ``.devsteward/evidence/REQ-NNN/<timestamp>/``, the
``events.jsonl`` event carries per-AC results and each artifact's relative path + sha256,
and ``verified_by`` gets the engine-composed dated summary. A lab skip or a missing
artifact is a hard red, and a red validation **parks immediately — no repair loop**
(Decision 8): a red here means the develop was hollow or the lab is broken, both human
questions.

:func:`ReqValidateRoutine.__call__` is the single code path (Decision 9): the executor's
batch loop reaches it through the ``validate_runner`` seam, ``steward validate`` calls it
directly (attended, with a sign-off provider), and a done REQ gets a fresh evidence
append through :meth:`ReqValidateRoutine.revalidate` without its status being disturbed.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ...core import claude as claude_mod
from ...core.executor import RunOutcome, StepResult
from ...core.ledger import LEDGER_DIRNAME, Ledger
from ...core.transaction import transaction
from ...core.model import AcceptanceCheck, Decision, Step, StepStatus
from ...core.verify import (
    NoUsableEnvError,
    resolve_test_interpreter,
)
from .reqfile import ReqFile, load_reqs
from .verify import ReqVerifier

EVIDENCE_DIRNAME = "evidence"


@dataclass
class Signoff:
    """A human verdict on one ``manual`` AC (REQ-030 D4 / REQ-034): the checkbox is the
    human's — the engine composes the rest of the provenance (date, reviewer line, event
    detail) mechanically.

    Three terminal outcomes (REQ-034 Decision 7): ``approved`` → green (land); ``approved``
    false → declined (red, routes to ``steward rework``); ``deferred`` → pending (async QA
    park, Decision 3). ``deferred`` wins over ``approved`` — a human who steps away has not
    approved."""

    approved: bool
    reviewer: str
    scope: str = ""
    deferred: bool = False

    @property
    def outcome(self) -> str:
        if self.deferred:
            return "pending"
        return "approved" if self.approved else "declined"


#: Attended sign-off source: called once per ``manual`` AC, returns the human's verdict.
SignoffProvider = Callable[[AcceptanceCheck], Signoff]


@dataclass
class StartContext:
    """What the **start** half of the guided two-phase bookkeeping (REQ-034 Decision 6)
    hands the **record** half: the prepared evidence dir and the resolved step/req. The
    bring-up (shape A) or the in-session guided work (shape B) happens between the two."""

    req: "ReqFile"
    step: Step
    evidence_dir: Path
    evidence_rel: str
    in_flight: bool


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class ReqValidateRoutine:
    """The executor's ``validate_runner`` seam for the REQ profile.

    ``python`` is the project's configured test interpreter (``verify.python``) the
    artifact gate resolves commands under — the same REQ-028 environment discipline as
    the develop gate.
    """

    def __init__(self, req_dir: Path, python: str | None = None):
        self.req_dir = Path(req_dir)
        self.python = python

    # -- entry points -----------------------------------------------------------

    def __call__(
        self,
        ex,
        step: Step,
        *,
        unattended: bool = True,
        on_event=None,
        signoff: SignoffProvider | None = None,
        driver: str | None = None,
    ) -> StepResult:
        """Execute the pending validate step of an in-flight REQ (Decision 9)."""
        driver = driver or ("headless" if unattended else "interactive")
        led = ex.ledger
        req = self._req(step.req)
        if req is None:
            return StepResult(step, RunOutcome.FAILED, f"{step.req}: REQ file not found")

        # Lab availability (Decision 7): honest deferral surfaced, not silent green —
        # no red event, no parked decision (the registry already records the answer).
        pending_labs = self._pending_labs(req)
        if pending_labs:
            return StepResult(
                step,
                RunOutcome.REFUSED,
                f"{req.id} validation waiting on {', '.join(pending_labs)} — "
                f"the declared lab is not done yet",
            )

        # REQ-065: pre-flight the land gate before spending the session. A formality red
        # (missing concept doc / plan) must refuse here, never after the paid session and
        # its human sign-offs.
        preflight = self._preflight_gate(ex, step)
        if preflight is not None:
            return preflight

        led.set_cursor(step.id)
        led.set_status(step.id, StepStatus.RUNNING)
        led.save()
        led.append_event("step_started", step=step.id, command=step.command)

        # REQ-048: a green validate lands inline (mechanical_land commits code + ledger on
        # ``dev``) — there is no feature branch to merge.
        return self._validate(
            ex, req, step,
            unattended=unattended, on_event=on_event, signoff=signoff,
            driver=driver, in_flight=True,
        )

    def revalidate(
        self,
        ex,
        req_id: str,
        *,
        on_event=None,
        signoff: SignoffProvider | None = None,
        driver: str = "interactive",
    ) -> StepResult:
        """Append a fresh evidence event for a **done** REQ (Decisions 5/9).

        Runs the same session + engine gate + sign-off mechanics and records the dated
        evidence event — but leaves the REQ file untouched: status *and* ``verified_by``
        stay the frozen landing provenance (REQ-035), and the index, ledger steps, and git
        are never touched. The event log is the durable re-validation record; the
        release-gate human decides what to re-run.
        """
        req = self._req(req_id)
        if req is None:
            return StepResult(None, RunOutcome.FAILED, f"{req_id}: REQ file not found")
        pending_labs = self._pending_labs(req)
        if pending_labs:
            return StepResult(
                None,
                RunOutcome.REFUSED,
                f"{req.id} validation waiting on {', '.join(pending_labs)} — "
                f"the declared lab is not done yet",
            )
        step = Step(
            id=f"{req.id}:validate",
            command=f"/system-test {req.id}",
            verify=tuple(c.test for c in req.acceptance if c.check == "artifact"),
            title=f"{req.title} — validate (re-run)",
            req=req.id,
            phase="validate",
        )
        return self._validate(
            ex, req, step,
            unattended=False, on_event=on_event, signoff=signoff,
            driver=driver, in_flight=False,
        )

    def reconcile_stale_validation_decision(self, led: Ledger, req_id: str) -> list:
        """Close any lingering **open** ``:validate`` decision on a **done** REQ — the D2
        recovery (REQ-073 Decision 3).

        Reachable only on the revalidate route (the caller has already established the REQ is
        ``done``). A ``done`` REQ still surfacing an open ``:validate`` decision is a diverged
        ledger — the land already happened and is in the event log — so the decision is
        reconciled without re-running the System Tester or touching provenance (REQ-035).
        Returns the decisions it closed (empty if the ledger was already clean).
        """
        validate_id = f"{req_id}:validate"
        stale = [d for d in led.open_decisions() if d.step == validate_id]
        for dec in stale:
            led.reconcile_validation_decision(dec.id)
        return stale

    def reland(
        self, ex, req_id: str, *, driver: str = "interactive"
    ) -> StepResult:
        """REQ-065 — replay ``mechanical_land`` for a validate step left ``FAILED`` by a
        land-gate refusal, **without** re-running the session.

        The session ran; its artifact gate and human sign-offs are durable in the green
        ``validation`` event. Once the formality (concept doc / plan) is fixed, replaying the
        land re-certifies that same recorded green — strictly correct, and far cheaper than
        ``steward repeat`` (which would re-spawn the session and re-collect every sign-off).

        Narrow, safe preconditions (Decision 4): ``REQ-NNN:validate`` is ``FAILED``, the
        latest ``land_refused`` event for the step is at-or-after the latest ``ok:True``
        ``validation`` event, and that green validation exists. Anything else — a red
        validation, a non-validate / never-run step, a ``DONE``/``PENDING``/``RUNNING`` step —
        is a hard ``REFUSED`` with a routing diagnostic. Re-runs the (now-fixed) gate as a
        final pre-flight; if it still refuses, the step stays ``FAILED``.
        """
        led: Ledger = ex.ledger
        req = self._req(req_id)
        if req is None:
            return StepResult(None, RunOutcome.FAILED, f"{req_id}: REQ file not found")
        validate_id = f"{req_id}:validate"
        if led.status_of(validate_id) is not StepStatus.FAILED:
            return StepResult(None, RunOutcome.REFUSED, self._reland_refusal(req_id, led))

        green: dict | None = None
        refused: dict | None = None
        for ev in led.events():
            if (
                ev.get("event") == "validation"
                and ev.get("req") == req_id
                and ev.get("ok") is True
            ):
                green = ev
            if ev.get("event") == "land_refused" and ev.get("step") == validate_id:
                refused = ev
        if green is None or refused is None or refused["ts"] < green["ts"]:
            return StepResult(None, RunOutcome.REFUSED, self._reland_refusal(req_id, led))

        # Reconstruct the land detail + carry the recorded sign-offs forward (Decision 2).
        results = green.get("results", [])
        signoffs = green.get("signoffs", [])
        evidence_rel = green.get("evidence", "")
        detail = "; ".join(
            r["detail"].splitlines()[0] for r in results if r.get("detail")
        ) or "validated"

        step = Step(
            id=validate_id,
            command=f"/system-test {req_id}",
            verify=tuple(c.test for c in req.acceptance if c.check == "artifact"),
            title=f"{req.title} — validate (reland)",
            req=req_id,
            phase="validate",
        )
        # Re-run the now-fixed gate as a final pre-flight; still red → refuse, leave FAILED.
        if ex.land_gate is not None:
            refusal = ex.land_gate(step)
            if refusal is not None:
                return StepResult(
                    step,
                    RunOutcome.REFUSED,
                    f"reland refused — the land gate still refuses {req_id}: {refusal}",
                )

        led.set_status(validate_id, StepStatus.RUNNING)
        led.save()
        led.append_event("reland", step=validate_id, req=req_id, replays=evidence_rel)
        self._write_verified_by(req, results, signoffs, evidence_rel, driver)
        for dec in led.open_decisions():
            if dec.step == validate_id:
                led.answer_decision(dec.id, "resolved by reland (recorded green replayed)")
        # The gate was pre-flighted just above — do not run it again in mechanical_land.
        return ex.mechanical_land(step, detail, driver=driver, run_gate=False)

    def _reland_refusal(self, req_id: str, led: Ledger) -> str:
        """The diagnostic for a reland outside its narrow precondition shape (Decision 4)."""
        validate_id = f"{req_id}:validate"
        status = led.status_of(validate_id)
        return (
            f"steward reland only applies to a {validate_id} step left FAILED by a "
            f"land-gate refusal (its last events a green validation followed by a "
            f"land_refused) — {validate_id} is {status.value}. For a red validation use "
            f"`steward revalidate {req_id}`; for a develop step use `steward repeat {req_id}`."
        )

    # -- guided two-phase bookkeeping (REQ-034) ---------------------------------

    def start(self, ex, step: Step) -> "StartContext | StepResult":
        """The **start** half (REQ-034 Decision 6): lab check, set RUNNING, prepare the
        evidence dir (REQ-048: trunk-based — no branch to ready).

        Returns a :class:`StartContext` for the record half, or a terminal
        :class:`StepResult` (``REFUSED``/``FAILED``) when validation cannot start (an
        undone lab, a missing REQ). Both launch shapes call this: shape A (``steward
        validate`` from a shell) then brings the interactive session up; shape B (a running
        session's skill) does the guided work in-session."""
        led = ex.ledger
        req = self._req(step.req)
        if req is None:
            return StepResult(step, RunOutcome.FAILED, f"{step.req}: REQ file not found")
        pending_labs = self._pending_labs(req)
        if pending_labs:
            return StepResult(
                step,
                RunOutcome.REFUSED,
                f"{req.id} validation waiting on {', '.join(pending_labs)} — "
                f"the declared lab is not done yet",
            )
        # REQ-065: pre-flight the land gate (see ``__call__``) — refuse a formality red
        # before readying the evidence dir or bringing up the guided session.
        preflight = self._preflight_gate(ex, step)
        if preflight is not None:
            return preflight
        led.set_cursor(step.id)
        led.set_status(step.id, StepStatus.RUNNING)
        led.save()
        led.append_event("step_started", step=step.id, command=step.command)
        # REQ-048: the System-Tester session and evidence both live in the one tree on ``dev``
        # (``ex.root``); the ledger commit captures the evidence in place.
        evidence_dir = ex.root / LEDGER_DIRNAME / EVIDENCE_DIRNAME / req.id / _now_stamp()
        evidence_dir.mkdir(parents=True, exist_ok=True)
        return StartContext(
            req=req,
            step=step,
            evidence_dir=evidence_dir,
            evidence_rel=str(evidence_dir.relative_to(ex.root)),
            in_flight=True,
        )

    def record(
        self,
        ex,
        ctx: "StartContext",
        *,
        signoff: SignoffProvider | None,
        on_event=None,
        driver: str = "interactive",
    ) -> StepResult:
        """The **end/record** half (REQ-034 Decisions 6/7): run the engine artifact gate on
        whatever the guided session captured, take the human verdict, append the evidence
        event + ``verified_by``, and route the three terminal outcomes — green → mechanical
        land; declined → red park pointing at ``steward rework``; pending → async QA park.

        Called directly by a mid-session skill (shape B) and by :meth:`guided_validate`
        after the foreground bring-up (shape A). Neither is wrapped by the executor's
        ``_drive_step``, so the parks here self-commit the ledger close (REQ-048: all on
        ``dev`` — no branch to return from)."""
        led: Ledger = ex.ledger
        req, step = ctx.req, ctx.step
        artifact_acs = [c for c in req.acceptance if c.check == "artifact"]
        manual_acs = [c for c in req.acceptance if c.check == "manual"]

        results, all_green = self._artifact_gate(
            ex, req, artifact_acs, ctx.evidence_dir
        )

        signoffs: list[dict] = []
        if manual_acs and all_green:
            if signoff is None:
                # No verdict source → the human has not answered yet: async QA park (D3).
                return self._park_pending(ex, step, req, manual_acs)
            for ac in manual_acs:
                verdict = signoff(ac)
                if verdict.deferred:
                    # Pending — the human stepped away mid-validation (D3/D7). Park async;
                    # nothing recorded, the work-item stands.
                    return self._park_pending(ex, step, req, manual_acs)
                signoffs.append(
                    {
                        "ac": ac.id,
                        "approved": verdict.approved,
                        "reviewer": verdict.reviewer,
                        "scope": verdict.scope,
                        "date": _today(),
                    }
                )
                results.append(
                    {
                        "ac": ac.id,
                        "check": "manual",
                        "ok": verdict.approved,
                        "detail": (
                            f"sign-off by {verdict.reviewer}"
                            + (f" — {verdict.scope}" if verdict.scope else "")
                            if verdict.approved
                            else f"declined by {verdict.reviewer}"
                        ),
                    }
                )
                if not verdict.approved:
                    all_green = False

        artifacts = [
            {"path": str(p.relative_to(ex.root)), "sha256": _sha256(p)}
            for p in sorted(ctx.evidence_dir.rglob("*"))
            if p.is_file()
        ]
        led.append_event(
            "validation",
            step=step.id,
            req=req.id,
            ok=all_green,
            driver=driver,
            rerun=False,
            evidence=ctx.evidence_rel,
            results=results,
            artifacts=artifacts,
            signoffs=signoffs,
        )

        if not all_green:
            return self._park_red(
                ex, step, req, results, in_flight=True, attended=True
            )

        self._write_verified_by(req, results, signoffs, ctx.evidence_rel, driver)
        detail = "; ".join(r["detail"].splitlines()[0] for r in results) or "validated"
        for dec in led.open_decisions():
            if dec.step == step.id:
                led.answer_decision(
                    dec.id, "resolved by green validation (sign-off recorded)"
                )
        # REQ-048: lands inline on ``dev`` — no feature branch to merge. REQ-065: the gate
        # was pre-flighted in ``start()``, so it is not run again here.
        return ex.mechanical_land(step, detail, driver=driver, run_gate=False)

    def guided_validate(
        self,
        ex,
        step: Step,
        *,
        signoff: SignoffProvider | None = None,
        on_event=None,
        driver: str = "interactive",
    ) -> StepResult:
        """Shape A (REQ-034 Decision 6): the standard `steward validate` from a plain shell —
        start → bring up the interactive guided session attached to the terminal (the editor
        pattern) → record. Surfaces the nesting refusal when run inside a Claude session."""
        ctx = self.start(ex, step)
        if isinstance(ctx, StepResult):
            return ctx
        outcome = ex.bring_up_guided_session(step, ctx.evidence_rel, on_event=on_event)
        if isinstance(outcome, str):
            # CLAUDECODE refusal — never spawn Claude from within Claude. The start half's
            # RUNNING survives for a clean re-entry from a plain shell.
            return StepResult(step, RunOutcome.REFUSED, outcome)
        # REQ-049: the post-session land/park is atomic — a git failure rolls the repo +
        # ledger back to the pre-record snapshot. The interactive bring-up above is left
        # outside the boundary (a Ctrl-C there must not discard captured evidence). The batch
        # path (``__call__`` → ``_validate``) runs under ``_drive_step``'s own transaction.
        with transaction(ex.git, label=f"validate {step.req}"):
            return self.record(ex, ctx, signoff=signoff, on_event=on_event, driver=driver)

    # -- the one validation pass -------------------------------------------------

    def _validate(
        self,
        ex,
        req: ReqFile,
        step: Step,
        *,
        unattended: bool,
        on_event,
        signoff: SignoffProvider | None,
        driver: str,
        in_flight: bool,
    ) -> StepResult:
        led: Ledger = ex.ledger
        artifact_acs = [c for c in req.acceptance if c.check == "artifact"]
        manual_acs = [c for c in req.acceptance if c.check == "manual"]
        evidence_dir = (
            ex.root / LEDGER_DIRNAME / EVIDENCE_DIRNAME / req.id / _now_stamp()
        )
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_rel = str(evidence_dir.relative_to(ex.root))

        # 1. The System Tester session (Decision 2) — fresh, diff-free, lab prep and
        #    artifact capture only. No session when there is nothing to capture.
        if artifact_acs:
            failure = self._run_session(
                ex, step, evidence_rel,
                unattended=unattended, on_event=on_event, in_flight=in_flight,
            )
            if failure is not None:
                return failure

        # 2. The engine runs each artifact AC's named test command itself (Decision 2) —
        #    the same skip-is-red / zero-collected-is-red teeth as the develop gate.
        results, all_green = self._artifact_gate(ex, req, artifact_acs, evidence_dir)

        # 3. Manual ACs (Decision 4): a decision stop. Unattended parks naming the
        #    pending human oracle; attended records the verdict the provider supplies.
        signoffs: list[dict] = []
        if manual_acs and all_green:
            if unattended or signoff is None:
                return self._park_manual(ex, step, req, manual_acs, in_flight=in_flight)
            for ac in manual_acs:
                verdict = signoff(ac)
                signoffs.append(
                    {
                        "ac": ac.id,
                        "approved": verdict.approved,
                        "reviewer": verdict.reviewer,
                        "scope": verdict.scope,
                        "date": _today(),
                    }
                )
                results.append(
                    {
                        "ac": ac.id,
                        "check": "manual",
                        "ok": verdict.approved,
                        "detail": (
                            f"sign-off by {verdict.reviewer}"
                            + (f" — {verdict.scope}" if verdict.scope else "")
                            if verdict.approved
                            else f"declined by {verdict.reviewer}"
                        ),
                    }
                )
                if not verdict.approved:
                    all_green = False

        # 4. The dated evidence event (Decision 3) — durable, greppable, survives lab
        #    teardown. Recorded for green *and* red; only a manual park records nothing.
        artifacts = [
            {"path": str(p.relative_to(ex.root)), "sha256": _sha256(p)}
            for p in sorted(evidence_dir.rglob("*"))
            if p.is_file()
        ]
        led.append_event(
            "validation",
            step=step.id,
            req=req.id,
            ok=all_green,
            driver=driver,
            rerun=not in_flight,
            evidence=evidence_rel,
            results=results,
            artifacts=artifacts,
            signoffs=signoffs,
        )

        if not all_green:
            return self._park_red(ex, step, req, results, in_flight=in_flight)

        # 5. Green. A **done** re-validation (REQ-035) is non-mutating: the appended
        #    evidence event (step 4 / REQ-030 D3) is the durable, dated re-validation
        #    record, so the REQ file is left untouched — status *and* verified_by stay the
        #    frozen landing provenance ("done is never weakened", REQ-001). Only the
        #    in-flight landing path composes verified_by (the provenance being established)
        #    and lands through the same mechanical routine as batch.
        detail = "; ".join(r["detail"].splitlines()[0] for r in results) or "validated"
        if not in_flight:
            return StepResult(step, RunOutcome.DONE, detail)
        self._write_verified_by(req, results, signoffs, evidence_rel, driver)
        # A decision parked by an earlier unattended pass (the manual stop) is resolved
        # by this green validation — close it so the ledger does not surface a stale fork.
        for dec in led.open_decisions():
            if dec.step == step.id:
                led.answer_decision(
                    dec.id, "resolved by green validation (sign-off recorded)"
                )
        # REQ-065: the gate was pre-flighted in ``__call__``, so it is not run again here.
        return ex.mechanical_land(step, detail, driver=driver, run_gate=False)

    # -- pieces -------------------------------------------------------------------

    def _preflight_gate(self, ex, step: Step) -> StepResult | None:
        """REQ-065 — run the full ``CompositeLandGate`` *before* the validate session.

        A refusal becomes a terminal ``REFUSED`` result and leaves the ledger and tree
        untouched (no ``RUNNING``, no ``step_started``, no spawned session): a formality red
        must never cost a paid session and its human oracles. ``None`` when the gate is clear
        (or absent) so the caller proceeds to set ``RUNNING`` and run the session.
        """
        if ex.land_gate is None:
            return None
        refusal = ex.land_gate(step)
        if refusal is None:
            return None
        return StepResult(step, RunOutcome.REFUSED, refusal)

    def _req(self, req_id: str | None) -> ReqFile | None:
        for r in load_reqs(self.req_dir):
            if r.id == req_id:
                return r
        return None

    def _pending_labs(self, req: ReqFile) -> list[str]:
        by_id = {r.id: r for r in load_reqs(self.req_dir)}
        pending = []
        for lab in req.process.get("lab", []):
            lab_req = by_id.get(lab)
            if lab_req is None or lab_req.status != "done":
                pending.append(lab)
        return pending

    def _run_session(
        self, ex, step: Step, evidence_rel: str, *, unattended, on_event, in_flight
    ) -> StepResult | None:
        """Spawn the System Tester session; return a terminal result on limit/failure."""
        led = ex.ledger
        ok, reason = ex.accounts.precheck()
        if not ok:
            if in_flight:
                led.set_status(step.id, StepStatus.PENDING)
                led.save()
            led.append_event("quota_block", step=step.id, reason=reason)
            return StepResult(step, RunOutcome.LIMIT, reason)
        model, effort = ex._claude_for("validate")
        command = f"{step.command} --evidence {evidence_rel}"
        result = ex.runner(
            command,
            argv_prefix=ex.accounts.claude_argv(),
            cwd=str(ex.root),
            unattended=unattended,
            permission_mode=ex.permission_mode,
            model=model,
            effort=effort,
            on_event=on_event,
            on_spawn=(ex.stop.register_child if ex.stop is not None else None),
        )
        if ex.stop is not None:
            ex.stop.clear_child()
        if result.outcome is claude_mod.Outcome.USAGE_LIMIT:
            if in_flight:
                led.set_status(step.id, StepStatus.PENDING)
                led.save()
            led.append_event("usage_limit", step=step.id)
            return StepResult(step, RunOutcome.LIMIT, "claude usage limit")
        if result.outcome is not claude_mod.Outcome.OK:
            if in_flight:
                led.set_status(step.id, StepStatus.FAILED)
                led.save()
            led.append_event(
                "step_failed", step=step.id, outcome=result.outcome.value
            )
            return StepResult(step, RunOutcome.FAILED, result.outcome.value)
        return None

    def _artifact_gate(
        self, ex, req: ReqFile, artifact_acs: list[AcceptanceCheck], evidence_dir: Path
    ) -> tuple[list[dict], bool]:
        """Engine-run artifact ACs; only this pass/fail signal feeds the gate (D2/D3)."""
        results: list[dict] = []
        all_green = True
        # REQ-051: lab fixtures must be committed upstream and the System Tester must never
        # improvise one. A missing/improvised fixture is a hard red captured in the evidence
        # event — extends the "no artifact captured → hard red" teeth below.
        fixture_results, fixtures_ok = self._check_fixtures(ex, req)
        results.extend(fixture_results)
        if not fixtures_ok:
            all_green = False
        if not artifact_acs:
            return results, all_green
        gate = ReqVerifier(cwd=str(ex.root), full_suite=None, python=self.python)
        try:
            interpreter = resolve_test_interpreter(str(ex.root), self.python)
        except NoUsableEnvError as exc:
            results.append(
                {"ac": "-", "check": "artifact", "ok": False,
                 "detail": f"no usable test environment: {exc}"}
            )
            return results, False  # keep any fixture-gap rows already recorded
        for ac in artifact_acs:
            ok, detail = gate._gate_named(ac.test, interpreter)
            results.append({"ac": ac.id, "check": "artifact", "ok": ok, "detail": detail})
            if not ok:
                all_green = False
        # Missing artifact is a hard red, never a pass (Decision 3): a validation that
        # captured nothing has not proved the behaviour happened.
        if all_green and not any(p.is_file() for p in evidence_dir.rglob("*")):
            results.append(
                {
                    "ac": "-",
                    "check": "artifact",
                    "ok": False,
                    "detail": (
                        f"no artifact captured under {evidence_dir.name}/ — a missing "
                        f"artifact is a hard red"
                    ),
                }
            )
            all_green = False
        return results, all_green

    def _check_fixtures(self, ex, req: ReqFile) -> tuple[list[dict], bool]:
        """REQ-051 (REQ-047 Decision 6): every declared lab fixture must be committed
        upstream, and the System Tester must never improvise one.

        For each ``process.fixtures`` path the System-Test phase needs, the oracle is *git
        cleanliness* (real git, not the session's word):

        * **untracked files under the path → the tester improvised.** An uncommitted fixture
          is exactly the divergence REQ-047 forbids, so it is a hard red — and the improvised
          file is discarded so no uncommitted fixture is left in the tree.
        * **no tracked files under the path → the fixture is missing.** A hard red naming the
          gap; the tester must commit it upstream, never create-and-don't-commit.

        Real-git only and fail-open: a no-op when there are no declared fixtures or no repo
        (the in-memory fake), mirroring the REQ-050 self-check — a safety net must not brick a
        legitimate validation. The returned result rows ride into the dated evidence event, so
        the gap is captured durably."""
        fixtures = req.process.get("fixtures", [])
        if not fixtures:
            return [], True
        if not (ex.root / ".git").is_dir():
            return [], True  # the in-memory fake / no repo — nothing to enforce
        results: list[dict] = []
        all_green = True
        for rel in fixtures:
            tracked = self._git_lines(ex.root, "ls-files", "--", rel)
            untracked = self._git_lines(
                ex.root, "ls-files", "--others", "--exclude-standard", "--", rel
            )
            if untracked:
                # The tester improvised — discard it so the tree carries no uncommitted fixture.
                for u in untracked:
                    p = ex.root / u
                    if p.is_file():
                        p.unlink()
                results.append(
                    {
                        "ac": "-",
                        "check": "artifact",
                        "ok": False,
                        "detail": (
                            f"the System Tester improvised an uncommitted fixture under "
                            f"{rel} ({', '.join(untracked)}) — lab fixtures must be committed "
                            f"upstream; the improvised file was discarded, commit the fixture "
                            f"instead"
                        ),
                    }
                )
                all_green = False
            elif not tracked:
                results.append(
                    {
                        "ac": "-",
                        "check": "artifact",
                        "ok": False,
                        "detail": (
                            f"required lab fixture {rel} is missing (not committed) — a "
                            f"missing fixture is a hard red; commit it upstream before "
                            f"validating"
                        ),
                    }
                )
                all_green = False
        return results, all_green

    @staticmethod
    def _git_lines(root: Path, *args: str) -> list[str]:
        """Run a read-only ``git`` query against ``root``; return its non-blank output lines,
        or ``[]`` on any failure (fail-open — the fixture gate is a safety net)."""
        try:
            out = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            return []
        return [ln for ln in out.splitlines() if ln.strip()]

    def _park_manual(
        self, ex, step: Step, req: ReqFile, manual_acs, *, in_flight: bool
    ) -> StepResult:
        """Unattended manual AC → decision stop naming the pending human oracle (D4)."""
        led = ex.ledger
        ids = ", ".join(c.id for c in manual_acs)
        question = (
            f"{req.id} validation: manual AC {ids} awaits its human oracle — "
            f"run `steward validate {req.id}` attended to record the sign-off."
        )
        if not in_flight:
            return StepResult(step, RunOutcome.REFUSED, question)
        if not any(d.step == step.id for d in led.open_decisions()):
            dec = Decision(
                id=led.next_decision_id(), step=step.id, question=question, req=req.id
            )
            led.park_decision(dec)
        led.set_status(step.id, StepStatus.BLOCKED)
        led.save()
        return StepResult(step, RunOutcome.PARKED, question)

    def _park_pending(
        self, ex, step: Step, req: ReqFile, manual_acs
    ) -> StepResult:
        """Pending human validation → async QA park (REQ-034 Decision 3): a waiting human is
        a standing work-item, not a frozen pipeline. Leaves a clean tree on ``dev`` (REQ-048)
        — a subsequent ``steward run`` advances other eligible REQs. No verdict, so no
        evidence event; the decision records the standing item."""
        led = ex.ledger
        ids = ", ".join(c.id for c in manual_acs)
        question = (
            f"{req.id} validation pending — async QA: manual AC {ids} awaits the human "
            f"sign-off. Run `steward validate {req.id}` from a plain shell when ready; "
            f"meanwhile other REQs proceed (the waiting human does not freeze the pipeline)."
        )
        if not any(d.step == step.id for d in led.open_decisions()):
            dec = Decision(
                id=led.next_decision_id(), step=step.id, question=question, req=req.id
            )
            led.park_decision(dec)
        led.set_status(step.id, StepStatus.BLOCKED)
        led.save()
        # REQ-048 (was D3/D4): commit the ledger/evidence close on ``dev``. A pending human
        # validation is a standing work-item; the next ``steward run`` advances other REQs.
        ex._commit_ledger_close(step, "ledger close — validation pending (async QA)")
        return StepResult(step, RunOutcome.PARKED, question)

    def _park_red(
        self, ex, step: Step, req: ReqFile, results: list[dict], *,
        in_flight: bool, attended: bool = False,
    ) -> StepResult:
        """Red validation parks immediately with the failure brief — no repair loop
        (REQ-030 Decision 8): a red here is a human question (hollow develop or broken lab).
        It names **both** V-model return edges as a choice keyed on the root cause (REQ-055):
        ``steward rework`` when the develop was hollow (internal cause — redo it), or
        ``steward revalidate`` when an external lab/setup issue was fixed and the develop
        stands (re-run the validation only). It does not presume the cause.

        ``attended`` marks the guided path (not wrapped by ``_drive_step``): it self-commits
        the ledger close on ``dev`` (REQ-048)."""
        led = ex.ledger
        brief = "\n".join(r["detail"] for r in results if not r["ok"]) or "validation red"
        choice = (
            f"Pick the edge that fits the root cause: if the develop was hollow, return it "
            f"to develop for a fix with `steward rework {req.id}`; if an external lab/setup "
            f"issue was fixed and the develop stands, re-run the validation only with "
            f"`steward revalidate {req.id}`."
        )
        if not in_flight:
            return StepResult(step, RunOutcome.VERIFY_FAILED, f"{brief}\n\n{choice}")
        question = f"{req.id} validation red — needs a human:\n{brief[:1500]}\n\n{choice}"
        dec = Decision(
            id=led.next_decision_id(), step=step.id, question=question, req=req.id
        )
        led.park_decision(dec)
        led.set_status(step.id, StepStatus.BLOCKED)
        led.save()
        if attended:
            ex._commit_ledger_close(step, "ledger close — validation declined (red)")
            return StepResult(step, RunOutcome.PARKED, question)
        return StepResult(step, RunOutcome.PARKED, brief)

    def _write_verified_by(
        self, req: ReqFile, results, signoffs, evidence_rel: str, driver: str
    ) -> None:
        from .reqfile import set_frontmatter_verified_by

        n_artifact = sum(1 for r in results if r["check"] == "artifact" and r["ok"])
        bits = [f"{_today()} validation green ({driver})"]
        if n_artifact:
            bits.append(f"{n_artifact} artifact AC(s) engine-run")
        for s in signoffs:
            line = f"{s['ac']} signed off by {s['reviewer']}"
            if s["scope"]:
                line += f" — {s['scope']}"
            bits.append(line)
        bits.append(f"evidence {evidence_rel}")
        set_frontmatter_verified_by(req.path, "; ".join(bits))
