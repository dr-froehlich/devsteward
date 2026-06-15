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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ...core import claude as claude_mod
from ...core.executor import RunOutcome, StepResult
from ...core.ledger import LEDGER_DIRNAME, Ledger
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

        led.set_cursor(step.id)
        led.set_status(step.id, StepStatus.RUNNING)
        led.save()
        led.append_event("step_started", step=step.id, command=step.command)

        res = self._validate(
            ex, req, step,
            unattended=unattended, on_event=on_event, signoff=signoff,
            driver=driver, in_flight=True,
        )
        if res.outcome is RunOutcome.DONE and ex._merges_after(step):
            # Close the topology like a batch land (the second call from the batch
            # driver's own merge bracket is a no-op once we are back on integration).
            recovery = ex._merge_after_land(step, unattended=unattended)
            if recovery is not None:  # REQ-037: an aborted merge surfaces as a recoverable park
                return StepResult(step, RunOutcome.PARKED, recovery)
        return res

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

    # -- guided two-phase bookkeeping (REQ-034) ---------------------------------

    def start(self, ex, step: Step) -> "StartContext | StepResult":
        """The **start** half (REQ-034 Decision 6): lab check, ready/reconcile the feature
        branch, set RUNNING, prepare the evidence dir.

        Returns a :class:`StartContext` for the record half, or a terminal
        :class:`StepResult` (``REFUSED``/``FAILED``) when validation cannot start (an
        undone lab, a missing REQ, an unreconcilable branch). Both launch shapes call this:
        shape A (``steward validate`` from a shell) then brings the interactive session up;
        shape B (a running session's skill) does the guided work in-session."""
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
        # D5: ready the branch — reconcile a behind-but-merged resume rather than refuse it.
        surfaced = ex.ready_validate_branch(step)
        if surfaced is not None:
            return StepResult(step, RunOutcome.REFUSED, surfaced)
        led.set_cursor(step.id)
        led.set_status(step.id, StepStatus.RUNNING)
        led.save()
        led.append_event("step_started", step=step.id, command=step.command)
        # REQ-037: the System-Tester session runs in the main tree (``ex.root``), so evidence
        # is captured there; the ledger commit syncs it onto the integration branch. (``led``
        # may be bound to an integration worktree, so anchor on ``ex.root``, not ``led.dir``.)
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
        ``_drive_step``, so the parks here self-commit the ledger close and return HEAD to
        the integration branch (Decision 3)."""
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
        res = ex.mechanical_land(step, detail, driver=driver)
        if res.outcome is RunOutcome.DONE and ex._merges_after(step):
            recovery = ex._merge_after_land(step, unattended=(driver == "headless"))
            if recovery is not None:  # REQ-037: an aborted merge surfaces as a recoverable park
                return StepResult(step, RunOutcome.PARKED, recovery)
        return res

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
        return ex.mechanical_land(step, detail, driver=driver)

    # -- pieces -------------------------------------------------------------------

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
        if not artifact_acs:
            return results, all_green
        gate = ReqVerifier(cwd=str(ex.root), full_suite=None, python=self.python)
        try:
            interpreter = resolve_test_interpreter(str(ex.root), self.python)
        except NoUsableEnvError as exc:
            return (
                [{"ac": "-", "check": "artifact", "ok": False,
                  "detail": f"no usable test environment: {exc}"}],
                False,
            )
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
        a standing work-item, not a frozen pipeline. Leaves a clean tree, HEAD back on the
        integration branch, and the feature branch intact and **unmerged** (Decision 4) — a
        subsequent ``steward run`` advances other eligible REQs. No verdict, so no evidence
        event; the decision records the standing item."""
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
        # D3/D4: commit the ledger/evidence close on the feature branch (intact, unmerged),
        # then return HEAD to the integration branch. No merge on a park.
        ex._commit_ledger_close(step, "ledger close — validation pending (async QA)")
        ex.return_to_integration()
        return StepResult(step, RunOutcome.PARKED, question)

    def _park_red(
        self, ex, step: Step, req: ReqFile, results: list[dict], *,
        in_flight: bool, attended: bool = False,
    ) -> StepResult:
        """Red validation parks immediately with the failure brief — no repair loop
        (REQ-030 Decision 8): a red here is a human question (hollow develop or broken lab).
        It points at ``steward rework`` — the V-model return edge (REQ-033/REQ-034 D7).

        ``attended`` marks the guided path (not wrapped by ``_drive_step``): it self-commits
        the ledger close and returns HEAD to the integration branch (Decision 3)."""
        led = ex.ledger
        brief = "\n".join(r["detail"] for r in results if not r["ok"]) or "validation red"
        rework = (
            f"Return it to develop for a fix with `steward rework {req.id}` "
            f"(the V-model return edge)."
        )
        if not in_flight:
            return StepResult(step, RunOutcome.VERIFY_FAILED, f"{brief}\n\n{rework}")
        question = f"{req.id} validation red — needs a human:\n{brief[:1500]}\n\n{rework}"
        dec = Decision(
            id=led.next_decision_id(), step=step.id, question=question, req=req.id
        )
        led.park_decision(dec)
        led.set_status(step.id, StepStatus.BLOCKED)
        led.save()
        if attended:
            ex._commit_ledger_close(step, "ledger close — validation declined (red)")
            ex.return_to_integration()
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
