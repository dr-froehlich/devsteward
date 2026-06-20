"""The executor loop — the content-agnostic heart.

For each eligible step (all dependencies ``DONE``, status ``PENDING``):

1. set the cursor and announce ``step_started``;
2. precheck the account/quota gate (stop the *run* if out of quota — never fail a step);
3. invoke ``claude -p "<command>"`` headless via the runner;
4. **park-and-surface:** if the skill parked a decision (wrote one to the ledger, or
   emitted the ``[[DEVSTEWARD_PARK]]`` sentinel) leave the step ``BLOCKED`` and move on
   to the next independent step;
5. **verify:** run the step's named acceptance tests — green is mandatory to proceed;
6. **commit** the working tree and **advance** the ledger to ``DONE``.

Both entry points drive headless `claude -p` (the **batch** mode), so forks always
park-and-surface (there is no interactive channel for `AskUserQuestion`) and the engine
owns the single commit here: the skill does the work but leaves the tree dirty, and
`_commit` below makes the one authoritative checkpoint commit — the skill must not also
commit (that would double-commit). `advance_once` does exactly one step; `run` marches
every eligible step. A human-driven `/advance` inside an interactive Claude Code session
is the **interactive** mode — the only context where `AskUserQuestion` applies — and it
closes through :meth:`Executor.checkpoint` (``steward checkpoint``): the *same* verify
gate, mechanical land, and merge as batch. The engine is the verifying bookkeeper in
both modes; only the driver of the cognition varies (REQ-018), and the ``checkpoint``
event records which one drove (``driver: headless | interactive``).
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from . import claude as claude_mod
from .errors import PreconditionError
from .git import GitCli
from .invariants import check_invariants
from .ledger import Ledger
from .model import Decision, Step, StepStatus
from .seams import AccountProvider, GitTopology, StepSource, Verifier
from .transaction import transaction
from .verify import (
    NoUsableEnvError,
    _is_pytest_command,
    _pytest_outcome,
    _rebind_python,
    resolve_test_interpreter,
)

PARK_SENTINEL = "[[DEVSTEWARD_PARK]]"

_TRAILER = "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"


class RunOutcome(str, Enum):
    DONE = "done"
    PARKED = "parked"
    VERIFY_FAILED = "verify-failed"
    FAILED = "failed"
    LIMIT = "limit"
    BLOCKED_DEP = "blocked-dep"
    REFUSED = "refused"


@dataclass
class StepResult:
    step: Step | None
    outcome: RunOutcome
    detail: str = ""
    commit: str | None = None


class Executor:
    """Drives a :class:`StepSource` over a project's :class:`Ledger`."""

    def __init__(
        self,
        root: Path,
        source: StepSource,
        verifier: Verifier,
        accounts: AccountProvider,
        *,
        runner: Callable[..., claude_mod.Result] = claude_mod.run_claude,
        committer: Callable[[Step], str | None] | None = None,
        autocommit: bool = True,
        permission_mode: str | None = claude_mod.DEFAULT_PERMISSION_MODE,
        model: str | None = None,
        effort: str | None = None,
        stop=None,
        production_branch: str = "main",
        integration_branch: str = "dev",
        implementation_phases: tuple[str, ...] = ("develop", "validate"),
        git: GitTopology | None = None,
        on_verified: Callable[[Step], None] | None = None,
        land_gate: Callable[[Step], str | None] | None = None,
        step_claude: dict[str, tuple[str | None, str | None]] | None = None,
        repair_budget: int = 0,
        validate_runner: Callable[..., "StepResult"] | None = None,
        interactive_runner: Callable[..., int] = claude_mod.run_claude_interactive,
    ):
        self.root = Path(root)
        self.source = source
        self.verifier = verifier
        self.accounts = accounts
        # Profile hook run *after* a passing verify and *before* the checkpoint commit, so
        # any status flip it makes (the REQ profile marks the REQ `done`) is gated on green
        # tests and rides in the same commit. None for the generic profile.
        self.on_verified = on_verified
        # REQ-029: a content-aware refusal run *before* the mechanical land commits — returns
        # a surface message to refuse (the step parks) or None to proceed. The REQ profile
        # wires the plan-artifact gate (docs/plans/ must name the REQ id); None = no gate.
        self.land_gate = land_gate
        # REQ-029: per-step-kind (model, effort), e.g. {"develop": (...), "repair": (...)}.
        # A kind absent from the map falls back to the flat self.model/self.effort.
        self.step_claude = step_claude or {}
        # REQ-029: how many fresh repair sessions a red develop gate may spawn before the
        # step parks for a human. 0 (the bare default) = no repair; build_executor wires 2.
        self.repair_budget = repair_budget
        # REQ-030: the System-Test routine — ``(executor, step, *, unattended, on_event)``
        # → StepResult. The REQ profile wires :func:`devsteward.profiles.req.validate
        # .run_validate_step`; None (generic) means no validate phase exists.
        self.validate_runner = validate_runner
        # REQ-034 Decision 6: the foreground *interactive* bring-up for a guided human
        # validation (the editor pattern — TTY inherited, no -p, no detach). Injectable so
        # the tests drive shape A without a real claude / TTY.
        self.interactive_runner = interactive_runner
        self.runner = runner
        self.committer = committer
        self.autocommit = autocommit
        self.permission_mode = permission_mode
        self.model = model
        self.effort = effort
        self.stop = stop
        self.production_branch = production_branch
        self.integration_branch = integration_branch
        self.implementation_phases = implementation_phases
        self.git: GitTopology = git if git is not None else GitCli(self.root)
        self.ledger = Ledger(self.root)

    # -- invariants / read entry point -----------------------------------------

    def current_branch(self) -> str:
        return self.git.current_branch()

    def live_ledger(self) -> Ledger:
        """Return the live ledger (REQ-048: one co-located ledger on ``dev``).

        Trunk-based, there is only ever one ledger — the ``.devsteward/`` at the repo root —
        and nothing rebinds it, so reads and writes resolve the same single source of truth
        from any state. Kept as a stable read entry point for the CLI."""
        return self.ledger

    # The old ``branch_guard()`` (refuse to commit on the production branch) folded into
    # ``check_invariants`` as INV-2 (REQ-049): a precondition raised centrally, before any
    # mutation, as a typed ``PreconditionError`` rather than a per-call-site refusal string.

    def bring_up_guided_session(
        self, step: Step, evidence_rel: str, *, on_event=None
    ) -> int | str:
        """Bring up the interactive guided System-Tester session (REQ-034 Decision 6).

        Refuses — returns a surface *string* — when already inside a Claude session
        (``CLAUDECODE`` set): Claude is never spawned from within Claude. Otherwise spawns
        the interactive session in the foreground (the editor pattern) and returns its exit
        code. The verdict is taken afterward by the engine, so this session — however it
        reports — cannot self-certify (Decision 2)."""
        if claude_mod.in_claude_session():
            return (
                f"refusing to bring up a guided validation session from inside a Claude "
                f"session (CLAUDECODE set) — Claude is never spawned from within Claude. "
                f"Open a plain terminal tab and run `steward validate {step.req}` there, or "
                f"drive the validation in this session via the /system-test skill's "
                f"start/record steps."
            )
        model, effort = self._claude_for("validate")
        command = f"/system-test {step.req} --evidence {evidence_rel} --guided"
        return self.interactive_runner(
            command,
            argv_prefix=self.accounts.claude_argv(),
            cwd=str(self.root),
            model=model,
            effort=effort,
        )

    # -- planning --------------------------------------------------------------

    def steps(self) -> list[Step]:
        return self.source.steps(self.ledger)

    def _claude_for(self, kind: str) -> tuple[str | None, str | None]:
        """The (model, effort) for a session of ``kind`` (``develop``/``repair``), falling
        back to the flat default when the kind is unconfigured (REQ-029 Decision 4)."""
        return self.step_claude.get(kind, (self.model, self.effort))

    #: Step statuses that make a step a candidate for running. ``RECOVER`` joins
    #: ``PENDING`` so a re-armed failed step (REQ-026) is picked up by the next run.
    _RUNNABLE = (StepStatus.PENDING, StepStatus.RECOVER)

    def eligible_steps(self, only: str | None = None) -> list[Step]:
        """Steps that are runnable (PENDING or RECOVER) and whose every dependency is DONE.

        ``only`` restricts the set to one REQ's steps (REQ-026 ``--only``). Returned in
        deterministic id order so runs are reproducible.
        """
        steps = self.steps()
        by_id = {s.id: s for s in steps}
        eligible = []
        for s in steps:
            if only is not None and s.req != only:
                continue
            if self.ledger.status_of(s.id) not in self._RUNNABLE:
                continue
            if all(
                d in by_id and self.ledger.status_of(d) is StepStatus.DONE
                for d in s.depends_on
            ):
                eligible.append(s)
        return sorted(eligible, key=lambda s: s.id)

    def next_eligible(self, only: str | None = None) -> Step | None:
        elig = self.eligible_steps(only=only)
        return elig[0] if elig else None

    def only_ineligibility_reason(self, req_id: str) -> str:
        """Name *why* ``--only req_id`` selected nothing (REQ-026 D8): not active, already
        done, or blocked on an unfinished dependency."""
        steps = [s for s in self.steps() if s.req == req_id]
        if not steps:
            return (
                f"{req_id} has no eligible step — it is not active "
                f"(activate it first with `steward activate {req_id}`, or it does not exist)."
            )
        statuses = [self.ledger.status_of(s.id) for s in steps]
        if all(st is StepStatus.DONE for st in statuses):
            return f"{req_id} has no eligible step — it is already done."
        return (
            f"{req_id} has no eligible step — it is blocked on an unfinished dependency."
        )

    # -- execution -------------------------------------------------------------

    def run_step(
        self,
        step: Step,
        *,
        unattended: bool = True,
        on_event: Callable[[dict], None] | None = None,
    ) -> StepResult:
        led = self.ledger
        # REQ-030: a validate step is the System-Test phase, not a develop session — the
        # profile's routine owns its whole lifecycle (session, engine-run artifact gate,
        # evidence, manual stops, land).
        if step.phase == "validate" and self.validate_runner is not None:
            return self.validate_runner(
                self, step, unattended=unattended, on_event=on_event
            )
        # Batch-park an attended REQ (REQ-029 Decision 9): a REQ that declared a split
        # develop or a concept phase chose to have a human present, so unattended `steward
        # run`/`advance` parks it (naming the need) instead of simulating the attendance.
        if step.attended and unattended:
            return self._park_attended(step)
        # Capture the recovery signal *before* flipping to RUNNING (REQ-026 D5/AC4): if the
        # step was re-armed via `steward repeat`, tell the resuming skill so it assesses
        # the failed attempt's partial edits (already in the tree) instead of starting clean.
        recovering = led.status_of(step.id) is StepStatus.RECOVER
        command = step.command + (" --repeat" if recovering else "")
        led.set_cursor(step.id)
        led.set_status(step.id, StepStatus.RUNNING)
        led.save()
        led.append_event("step_started", step=step.id, command=command, recover=recovering)

        # When a run is interrupted (quota gate / usage limit) the step is re-queued. Keep
        # a recovering step as RECOVER so its recovery signal survives the interruption.
        requeue = StepStatus.RECOVER if recovering else StepStatus.PENDING

        ok, reason = self.accounts.precheck()
        if not ok:
            led.set_status(step.id, requeue)
            led.save()
            led.append_event("quota_block", step=step.id, reason=reason)
            return StepResult(step, RunOutcome.LIMIT, reason)

        model, effort = self._claude_for("develop")
        result = self.runner(
            command,
            argv_prefix=self.accounts.claude_argv(),
            cwd=str(self.root),
            unattended=unattended,
            permission_mode=self.permission_mode,
            model=model,
            effort=effort,
            on_event=on_event,
            on_spawn=(self.stop.register_child if self.stop is not None else None),
        )
        if self.stop is not None:
            self.stop.clear_child()

        if result.outcome is claude_mod.Outcome.USAGE_LIMIT:
            led.set_status(step.id, requeue)
            led.save()
            led.append_event("usage_limit", step=step.id)
            return StepResult(step, RunOutcome.LIMIT, "claude usage limit")

        if result.outcome is claude_mod.Outcome.LAUNCH_FAILURE:
            # claude never started — a launch failure must name its cause, not record an
            # opaque "failed" (the fictional-cswap fingerprint: started/failed same second).
            led.set_status(step.id, StepStatus.FAILED)
            led.save()
            detail = (
                "launch failure — claude did not start (non-zero exit, no stream-json "
                "output). Check the account provider (cswap) and that `claude` is on PATH."
            )
            led.append_event(
                "launch_failed",
                step=step.id,
                returncode=result.returncode,
                reason=detail,
            )
            return StepResult(step, RunOutcome.FAILED, detail)

        if result.outcome in (claude_mod.Outcome.ERROR, claude_mod.Outcome.TIMEOUT):
            led.set_status(step.id, StepStatus.FAILED)
            led.save()
            led.append_event("step_failed", step=step.id, outcome=result.outcome.value)
            return StepResult(step, RunOutcome.FAILED, result.outcome.value)

        # Park-and-surface: did the skill raise a fork?
        parked = self._detect_park(step, result.text)
        if parked is not None:
            return StepResult(step, RunOutcome.PARKED, parked.question)

        # Verify: named acceptance tests must be green (REQ-028 semantics in the profile).
        verified, detail = self.verifier.verify(step)
        led.append_event("verify", step=step.id, ok=verified, detail=detail[:2000])
        if not verified:
            # Red gate (REQ-029 Decision 3): spawn up to `repair_budget` fresh repair
            # sessions, then park. With no budget (the bare default) surface the failure.
            if self.repair_budget <= 0:
                led.set_status(step.id, StepStatus.FAILED)
                led.save()
                return StepResult(step, RunOutcome.VERIFY_FAILED, detail)
            repaired = self._repair_loop(
                step, detail, unattended=unattended, on_event=on_event
            )
            if repaired is not None:
                return repaired  # parked after budget, or a limit/failure during repair
            # A repair turned the gate green; re-read the passing detail for the record.
            verified, detail = self.verifier.verify(step)
            led.append_event("verify", step=step.id, ok=verified, detail=detail[:2000])

        # Green gate → the engine lands the REQ mechanically (no claude). REQ-029.
        # REQ-030 Decision 6: a develop step with a trailing validate step defers the
        # land — the work is committed, but the flip/index/merge wait for validation.
        if not step.lands:
            return self.commit_deferred(step, detail)
        return self.mechanical_land(step, detail)

    def checkpoint(self, step: Step) -> StepResult:
        """The full verify → land → merge close-out for an interactively driven step
        (no ``claude`` invocation) — REQ-018.

        Interactive ``/advance`` does the thinking and leaves the tree dirty; this command
        (``steward checkpoint``) re-runs the named acceptance tests through the same
        REQ-028 gate as a batch land, performs the shared :meth:`mechanical_land` on green
        (flip ``done``, index sync, the one authoritative commit, ledger advance — with
        ``driver: interactive`` on the checkpoint event), and finishes the topology like
        batch: the trailing ledger write is committed as a follow-up and the feature
        branch is merged ``--no-ff`` into the integration branch (no merge is attempted
        on the integration branch itself). It replaces the old manual hand-edit of
        ``state.yaml`` that let the ledger drift out of sync with a committed ``done``
        (the REQ-025 failure shape).

        On a red gate the red ``verify`` event and the ``FAILED`` step status are the
        honest trail of the attempt, but there are **zero land-side writes** — no flip,
        no index touch, no commit, no cursor move, no checkpoint event — so a re-run
        after a fix lands with no ``recover``.
        """
        check_invariants(self)  # REQ-049: refuse on production / mid-merge before any write
        led = self.ledger
        if led.status_of(step.id) is StepStatus.DONE:
            # REQ-040 Decision 3: the bookkeeper is idempotent. A re-checkpoint of an
            # already-done step (the 2026-06-15 mis-diagnosed re-run) refuses with zero
            # ledger writes — no verify event, no flip, no commit, no cursor move — so it
            # cannot append a duplicate develop_committed (with `commit: null`) or a
            # redundant ledger commit. Read the live cursor first: `steward status`.
            return StepResult(
                step,
                RunOutcome.REFUSED,
                f"{step.id} is already done — refusing to re-checkpoint it "
                f"(steward checkpoint is idempotent: no flip, no commit, no ledger "
                f"write). Run `steward status` for the live cursor and the next step.",
            )
        # REQ-049: the verify-gated land is atomic — any git failure mid-commit rolls the
        # repo + ledger back to the pre-command snapshot and surfaces a RecoverableError. A
        # red verify is a *return value* (not an exception), so its FAILED write persists.
        with transaction(self.git, label=f"checkpoint {step.id}"):
            verified, detail = self.verifier.verify(step)
            led.append_event("verify", step=step.id, ok=verified, detail=detail[:2000])
            if not verified:
                led.set_status(step.id, StepStatus.FAILED)
                led.save()
                return StepResult(step, RunOutcome.VERIFY_FAILED, detail)
            if not step.lands:
                # REQ-030 Decision 6: a validate step follows — commit the develop work; the
                # land fires after `steward validate`.
                return self.commit_deferred(step, detail, driver="interactive")
            return self.mechanical_land(step, detail, driver="interactive")

    def mechanical_land(
        self, step: Step, detail: str = "", driver: str = "headless"
    ) -> StepResult:
        """The deterministic post-green tail — **no claude** (REQ-029 Decision 2).

        The single shared routine both the batch develop path (:meth:`run_step`) and the
        interactive ``steward checkpoint`` (REQ-018) land through, so the bookkeeping is
        identical regardless of who drove the work. In order: the land gate (REQ-029
        Decision 6 — refuse if no plan names the REQ), then the verify-gated terminal flip
        (the profile marks the REQ ``done`` *before* the code commit so it rides the one
        checkpoint commit, same-commit discipline), the authoritative code commit, the
        ledger advance, and the trailing ledger commit (REQ-048: trunk-based, so the ledger
        advance lands directly on ``dev`` in its own ``.devsteward/`` commit — there is no
        feature branch to merge and no worktree).

        ``driver`` is recorded on the ``checkpoint`` event (REQ-018 Decision 5): who did
        the cognition — ``headless`` (batch) or ``interactive`` — while certification is
        the engine's in both modes.

        The caller must have already verified the step green; this routine assumes it.
        Returns ``PARKED`` if the land gate refuses (nothing committed), else ``DONE``.
        """
        led = self.ledger
        if self.land_gate is not None:
            refusal = self.land_gate(step)
            if refusal is not None:
                # REQ-056 Decision 2: a land-gate refusal (no plan names the REQ) is a
                # mechanical failure, not a choice — the only action is add-the-plan-and-rerun.
                # Fail to a repeatable step instead of parking a decision: set FAILED (not
                # BLOCKED), park **no** decision, keep the land_refused event, and still commit
                # the ledger close so the tree is clean at rest (REQ-032). VERIFY_FAILED is
                # non-stopping, so a missing plan for one REQ never halts unrelated REQs;
                # `steward repeat REQ` recovers it once the human adds the plan.
                led.set_status(step.id, StepStatus.FAILED)
                led.save()
                led.append_event("land_refused", step=step.id, detail=refusal)
                self._commit_ledger_close(step, "ledger close — land refused")
                return StepResult(step, RunOutcome.VERIFY_FAILED, refusal)
        if self.on_verified is not None:
            self.on_verified(step)
        snapshot = self.git.head_sha()
        sha = self._commit(step)
        self._assert_green_captured(step, sha, snapshot)  # REQ-050: roll back + refuse on a gap
        led.set_cursor(step.id)
        led.set_status(step.id, StepStatus.DONE)
        led.save()
        led.append_event("checkpoint", step=step.id, commit=sha, driver=driver)
        self._commit_ledger_close(step, "ledger checkpoint")
        return StepResult(step, RunOutcome.DONE, detail, commit=sha)

    def commit_deferred(
        self, step: Step, detail: str = "", driver: str = "headless"
    ) -> StepResult:
        """Close a green non-landing step (REQ-030 Decision 6) — commit, no land.

        The develop work is committed on ``dev`` and the ledger advances, but the REQ stays
        active: no ``done`` flip, no index touch, no land gate. Those fire from the trailing
        ``validate`` step's green (:meth:`mechanical_land`).
        """
        led = self.ledger
        snapshot = self.git.head_sha()
        sha = self._commit(step)
        self._assert_green_captured(step, sha, snapshot)  # REQ-050: roll back + refuse on a gap
        led.set_cursor(step.id)
        led.set_status(step.id, StepStatus.DONE)
        led.save()
        led.append_event(
            "develop_committed", step=step.id, commit=sha, driver=driver
        )
        # REQ-032: the trailing ledger write (status done + develop_committed event) is
        # committed as a follow-up to the work commit, so the tree is clean at rest while
        # the develop step waits for its validate sibling (Decision 1 — no dirty handoff).
        self._commit_ledger_close(step, "ledger checkpoint")
        return StepResult(step, RunOutcome.DONE, detail, commit=sha)

    def _park_attended(self, step: Step) -> StepResult:
        """Park an attended step in batch (REQ-029 Decision 9): record a decision naming the
        attended need and leave the step BLOCKED, spawning no claude session."""
        led = self.ledger
        if not any(d.step == step.id for d in led.open_decisions()):
            dec = Decision(
                id=led.next_decision_id(),
                step=step.id,
                question=step.attended_reason
                or f"{step.req or step.id} needs an attended session",
                req=step.req,
            )
            led.park_decision(dec)
        led.set_status(step.id, StepStatus.BLOCKED)
        led.save()
        led.append_event("attended_parked", step=step.id, reason=step.attended_reason)
        return StepResult(step, RunOutcome.PARKED, step.attended_reason)

    def _repair_command(self, step: Step, brief: str) -> str:
        """The prompt for a fresh repair session (REQ-029 Decision 8): the develop command
        plus a ``--repair`` marker and the gate's failure brief, so the skill assesses the
        partial work in the tree *and* knows exactly what failed. No ``--resume``."""
        return (
            f"{step.command} --repair\n\n"
            f"The previous develop attempt left the gate red. Failure brief:\n{brief}\n\n"
            f"Assess the partial work already in the tree, fix the cause, and make the named "
            f"acceptance tests pass."
        )

    def _repair_loop(
        self,
        step: Step,
        brief: str,
        *,
        unattended: bool,
        on_event: Callable[[dict], None] | None,
    ) -> StepResult | None:
        """Spawn up to ``repair_budget`` fresh repair sessions on a red gate (REQ-029
        Decision 3/8). Returns ``None`` once a repair turns the gate green (the caller then
        lands), or a terminal :class:`StepResult` — ``PARKED`` when the budget is exhausted
        still red, or a ``LIMIT``/``FAILED`` raised by a repair session.
        """
        led = self.ledger
        model, effort = self._claude_for("repair")
        for attempt in range(1, self.repair_budget + 1):
            ok, reason = self.accounts.precheck()
            if not ok:
                led.set_status(step.id, StepStatus.PENDING)
                led.save()
                led.append_event("quota_block", step=step.id, reason=reason)
                return StepResult(step, RunOutcome.LIMIT, reason)
            command = self._repair_command(step, brief)
            led.append_event(
                "repair_started", step=step.id, attempt=attempt, model=model
            )
            result = self.runner(
                command,
                argv_prefix=self.accounts.claude_argv(),
                cwd=str(self.root),
                unattended=unattended,
                permission_mode=self.permission_mode,
                model=model,
                effort=effort,
                on_event=on_event,
                on_spawn=(self.stop.register_child if self.stop is not None else None),
            )
            if self.stop is not None:
                self.stop.clear_child()

            if result.outcome is claude_mod.Outcome.USAGE_LIMIT:
                led.set_status(step.id, StepStatus.PENDING)
                led.save()
                led.append_event("usage_limit", step=step.id)
                return StepResult(step, RunOutcome.LIMIT, "claude usage limit")
            if result.outcome in (
                claude_mod.Outcome.ERROR,
                claude_mod.Outcome.TIMEOUT,
                claude_mod.Outcome.LAUNCH_FAILURE,
            ):
                led.set_status(step.id, StepStatus.FAILED)
                led.save()
                led.append_event(
                    "repair_failed", step=step.id, attempt=attempt,
                    outcome=result.outcome.value,
                )
                return StepResult(step, RunOutcome.FAILED, result.outcome.value)

            parked = self._detect_park(step, result.text)
            if parked is not None:
                return StepResult(step, RunOutcome.PARKED, parked.question)

            verified, detail = self.verifier.verify(step)
            led.append_event(
                "verify", step=step.id, ok=verified, detail=detail[:2000], repair=attempt
            )
            if verified:
                return None  # resolved — the caller lands
            brief = detail  # feed the next attempt the latest failure

        # Budget exhausted, still red → fail to a repeatable step (REQ-056 Decision 1).
        # State D is just state A after the budget runs out: there is no choice to record,
        # only "look, fix, run it again." Set FAILED (not BLOCKED), park **no** decision,
        # keep the repair_exhausted event, and return the same non-stopping VERIFY_FAILED as
        # the no-budget red gate — the run drains other independent steps and `steward repeat
        # REQ` recovers it, handing the resuming session the dirty tree (the ledger write is
        # left uncommitted, exactly as state A leaves it).
        led.set_status(step.id, StepStatus.FAILED)
        led.save()
        led.append_event(
            "repair_exhausted", step=step.id, attempts=self.repair_budget
        )
        return StepResult(step, RunOutcome.VERIFY_FAILED, brief)

    def step_by_id(self, step_id: str) -> Step | None:
        """Look up a derived step by id (``steward checkpoint`` resolves its target here)."""
        for s in self.steps():
            if s.id == step_id:
                return s
        return None

    def _detect_park(self, step: Step, text: str) -> Decision | None:
        """A fork is parked if the skill wrote a new open decision for this step, or
        emitted the park sentinel in its output (the engine then parks it)."""
        self.ledger.reload()
        for d in self.ledger.open_decisions():
            if d.step == step.id:
                # The skill already parked it; ensure the step is BLOCKED.
                self.ledger.set_status(step.id, StepStatus.BLOCKED)
                self.ledger.save()
                return d
        if PARK_SENTINEL in (text or ""):
            question = text.split(PARK_SENTINEL, 1)[1].strip().splitlines()[0]
            dec = Decision(
                id=self.ledger.next_decision_id(),
                step=step.id,
                question=question or "unspecified fork raised by skill",
                req=step.req,
            )
            self.ledger.park_decision(dec)
            return dec
        return None

    def _commit(self, step: Step) -> str | None:
        if self.committer is not None:
            return self.committer(step)
        if not self.autocommit:
            return None
        title = step.title or step.id
        message = f"{step.id}: {title}\n\n{_TRAILER}"
        # REQ-048: the code commit (code + REQ flip + index) never carries the ledger — the
        # cursor advances in its own trailing .devsteward/ commit. REQ-049: a git failure
        # here is *not* swallowed — it propagates to the transaction boundary, which rolls
        # the half-commit back and surfaces a RecoverableError (no silent None half-state).
        return self.git.commit_code(message)

    def _commit_ledger_close(self, step: Step | None, subject: str) -> str | None:
        """Commit the trailing ledger write (and any captured evidence) on ``dev`` as a
        follow-up, so a terminal step outcome leaves a clean tree (REQ-032).

        REQ-048 (trunk-based): the ledger is the single ``.devsteward/`` at the repo root and
        the commit lands directly on ``dev`` — no worktree, no branch. A clean ledger makes
        **no empty commit** (:meth:`GitCli.commit_ledger` returns ``None``). REQ-049: a git
        failure here is not swallowed — it propagates to the enclosing transaction boundary,
        which restores the pre-command snapshot and raises a RecoverableError (the in-memory
        fake never raises, so a non-git test harness still runs clean).
        """
        ref = (step.req or step.id) if step is not None else "ledger"
        return self.git.commit_ledger(f"{ref}: {subject}\n\n{_TRAILER}")

    # -- commit integrity (REQ-050) --------------------------------------------

    def _assert_green_captured(self, step: Step, sha: str | None, snapshot: str) -> None:
        """Refuse a land whose green the recorded commit does not reproduce (REQ-050).

        After the work commit, re-run the step's named acceptance gate against a *clean
        extract of the commit* (``git archive`` — only its tracked content, with no
        ``.gitignore``d or never-staged working-tree state). If a named test no longer
        passes, the green the verifier just certified depended on files the commit did not
        capture; roll the work commit back to ``snapshot`` and refuse with a typed
        :class:`PreconditionError` naming the gap — nothing certified, nothing advanced.

        The rollback is **explicit**: a ``PreconditionError`` passes *through* the
        transaction boundary without one (REQ-049), so relying on the boundary would strand
        the work commit — the half-state Stage C exists to forbid. We restore the snapshot
        ourselves, *then* raise the (now pass-through) precondition with its precise recovery.

        Real-git only and a safety net: with no repo (the in-memory fake), no named tests,
        or no usable extraction, there is nothing to reproduce, so it is a no-op.

        **Not the validate land.** This is a *develop*-land invariant: a regression AC's green
        is pure tracked source/test content, so re-running it from a clean commit extract is a
        faithful capture check. A *validate* step's ``verify`` is the ``artifact`` AC tests
        (``check: artifact``), whose green is established once against the **live lab** and
        recorded as captured evidence — it legitimately does *not* live in ``git archive``
        content, so a bare-extract re-run can only skip-or-worse. Applying the tracked-content
        gate there is a category error (it contradicts the REQ-030 artifact model and would
        reject every lab-backed validation), so the validate phase is exempt — its integrity
        contract (the evidence was captured and committed) is owned by the validate profile and
        its ledger close, not by this commit-extract reproduction.
        """
        if sha is None or not step.verify:
            return
        if step.phase == "validate":
            return
        if not (self.root / ".git").is_dir():
            return  # the in-memory fake / no repo — nothing to extract
        gap = self._green_gap_at(step, sha)
        if gap is None:
            return
        if snapshot:
            self.git.reset_hard(snapshot)
        raise PreconditionError(
            f"the commit recorded for {step.req or step.id} does not reproduce its "
            f"green — {gap}",
            recovery=(
                "the green depends on uncaptured files (gitignored or never staged) — "
                "commit them, or fix .gitignore so they are tracked, then re-run. The work "
                "commit was rolled back; nothing was certified."
            ),
        )

    def _green_gap_at(self, step: Step, sha: str) -> str | None:
        """Run the step's named acceptance tests against a clean extract of commit ``sha``;
        return a one-line gap description if any no longer passes, else ``None``.

        The interpreter is resolved against the *real* repo: the environment (the venv) is
        never part of a commit's self-sufficiency — only its source/test files are — so the
        tests run under the same interpreter, in a throwaway dir holding only what the commit
        captured. An unusable env or an unavailable extraction is the verifier's / operator's
        concern, not a capture gap, so it fails open (returns ``None``)."""
        try:
            interpreter = resolve_test_interpreter(str(self.root), self._verify_python())
        except NoUsableEnvError:
            return None
        timeout = float(getattr(self.verifier, "timeout", 1800.0))
        with tempfile.TemporaryDirectory(prefix="devsteward-selfcheck-") as tmp:
            if not self._extract_commit(sha, tmp):
                return None
            for cmd in step.verify:
                resolved = _rebind_python(cmd, interpreter)
                gap = self._reproduces_green(cmd, resolved, tmp, timeout)
                if gap is not None:
                    return gap
        return None

    def _verify_python(self) -> str | None:
        """The configured test interpreter the verifier resolves under (``verify.python``),
        if the verifier exposes one (the REQ profile's :class:`ReqVerifier` does)."""
        return getattr(self.verifier, "python", None)

    def _extract_commit(self, sha: str, dest: str) -> bool:
        """Extract only the tracked content of ``sha`` into ``dest`` — no gitignored or
        untracked working-tree state — via ``git archive`` piped to ``tar``. Returns
        ``False`` (fail-open) if the extraction tooling is unavailable."""
        try:
            archive = subprocess.run(
                ["git", "-C", str(self.root), "archive", sha],
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["tar", "-x", "-C", dest],
                input=archive.stdout,
                capture_output=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return False
        return True

    def _reproduces_green(
        self, cmd: str, resolved: str, cwd: str, timeout: float
    ) -> str | None:
        """Return a gap description if ``resolved`` does not *pass* from ``cwd`` (the commit
        extract), else ``None``. A pytest command is judged by its per-test outcome (a
        zero-collection, skip, failure, or error is a gap, mirroring the land gate's
        ``skip ≠ green``); a non-pytest command by exit code."""
        if _is_pytest_command(resolved):
            o = _pytest_outcome(resolved, cwd, timeout)
            if o.collected == 0:
                return f"{cmd!r} collects nothing from the recorded commit ({o.tail})"
            if o.skipped or o.failed or o.errors:
                return (
                    f"{cmd!r} no longer passes from the recorded commit "
                    f"({o.failed} failed, {o.errors} errors, {o.skipped} skipped of "
                    f"{o.collected})"
                )
            return None
        try:
            proc = subprocess.run(
                resolved, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return f"{cmd!r} timed out running against the recorded commit"
        if proc.returncode != 0:
            return f"{cmd!r} exits {proc.returncode} from the recorded commit"
        return None

    # -- step driver -----------------------------------------------------------

    def _drive_step(
        self,
        step: Step,
        *,
        unattended: bool,
        on_event: Callable[[dict], None] | None,
    ) -> StepResult:
        """Run one step on ``dev`` (REQ-048: trunk-based — no branch prepare, no merge).

        A green land commits the code and the ledger inline (:meth:`mechanical_land`); a park
        is a terminal outcome, so commit its ledger close here (the parked decision, the red
        event, any captured evidence) — a clean ledger makes no empty commit — so the next
        step in a batch run starts from a clean tree rather than riding this step's writes.
        Shared by both drivers.

        REQ-049: the whole step is one transaction — a git failure anywhere in the session,
        verify, land, or ledger close rolls the repo + ledger back to the pre-step snapshot
        and surfaces a RecoverableError. Terminal *outcomes* (PARKED/FAILED/VERIFY_FAILED)
        are return values, not exceptions, so they persist; only a real failure rolls back.
        """
        with transaction(self.git, label=f"step {step.id}"):
            res = self.run_step(step, unattended=unattended, on_event=on_event)
            if res.outcome is RunOutcome.PARKED:
                self._commit_ledger_close(step, "ledger close — parked")
        return res

    # -- drivers ---------------------------------------------------------------

    def advance_once(
        self,
        *,
        only: str | None = None,
        unattended: bool = True,
        on_event: Callable[[dict], None] | None = None,
    ) -> StepResult | None:
        """Run exactly one eligible step headless (or None if nothing is eligible).

        ``only`` restricts selection to one REQ's steps (REQ-026): the next eligible step
        of ``REQ-NNN`` even when a lower-id REQ is also eligible.
        """
        check_invariants(self)  # REQ-049: refuse up front on production / mid-merge (raises)
        step = self.next_eligible(only=only)
        if step is None:
            return None
        return self._drive_step(step, unattended=unattended, on_event=on_event)

    def run(
        self,
        *,
        only: str | None = None,
        max_steps: int | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> list[StepResult]:
        """Unattended: march eligible steps headless, parking on forks.

        A parked step is BLOCKED (not eligible), so the loop naturally advances to the
        next independent step and stops when nothing is eligible. ``only`` restricts the
        whole run to one REQ's steps (REQ-026).
        """
        check_invariants(self)  # REQ-049: refuse up front on production / mid-merge (raises)
        results: list[StepResult] = []
        count = 0
        while True:
            if self.stop is not None and self.stop.should_stop():
                # Graceful stop (REQ-025 D7/AC9): a Ctrl-C during the previous step set the
                # flag — finish nothing new, exit so the just-completed step stays the last.
                break
            if max_steps is not None and count >= max_steps:
                break
            step = self.next_eligible(only=only)
            if step is None:
                break
            res = self._drive_step(step, unattended=True, on_event=on_event)
            results.append(res)
            count += 1
            if res.outcome is RunOutcome.REFUSED:
                # A step refused (e.g. a validate waiting on an undone lab): stop for a human.
                break
            if res.outcome is RunOutcome.LIMIT:
                # Out of quota: stop the whole run (step is back to PENDING).
                break
            if res.outcome is RunOutcome.FAILED:
                # Hard failure: stop so a human can look (step stays FAILED).
                break
        return results
