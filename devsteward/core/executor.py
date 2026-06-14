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
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable

from . import claude as claude_mod
from .git import GitCli
from .ledger import Ledger
from .model import Decision, Step, StepStatus
from .seams import AccountProvider, GitTopology, StepSource, Verifier

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


class _ResolverShim(GitCli):
    """Back-compat: an old caller passing a ``branch_resolver`` callable gets its reads of
    the current branch from that callable, while mutating ops still hit real ``git``."""

    def __init__(self, root: Path, resolver: Callable[[Path], str]):
        super().__init__(root)
        self._resolver = resolver

    def current_branch(self) -> str:
        return self._resolver(self.root)


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
        feature_branch_template: str = "req-{num}-{slug}",
        git: GitTopology | None = None,
        branch_resolver: Callable[[Path], str] | None = None,
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
        self.feature_branch_template = feature_branch_template
        if git is not None:
            self.git: GitTopology = git
        elif branch_resolver is not None:
            self.git = _ResolverShim(self.root, branch_resolver)
        else:
            self.git = GitCli(self.root)
        self.ledger = Ledger(self.root)

    # -- branch guard ----------------------------------------------------------

    def current_branch(self) -> str:
        return self.git.current_branch()

    def branch_guard(self) -> str | None:
        """Refusal message if HEAD is the production branch, else ``None``.

        A whole-run precondition (the engine never switches branches), so the drivers
        consult it once up front — before any ``claude`` invocation.
        """
        if self.current_branch() == self.production_branch:
            return (
                f"refusing to autocommit on the production branch "
                f"'{self.production_branch}' — DevSteward never commits to production; "
                f"switch to the integration branch or a feature branch and re-run."
            )
        return None

    def feature_branch_name(self, step: Step) -> str:
        """The managed feature-branch name for ``step`` (config-driven, REQ-020 D8)."""
        num = (step.req or "").removeprefix("REQ-")
        return self.feature_branch_template.format(num=num, slug=step.slug, req=step.req)

    def prepare_branch(self, step: Step) -> str | None:
        """Manage the implementation feature branch (REQ-020), replacing REQ-019's refusal.

        Returns a *surface* message to abort the step (a diverged branch — a real
        conflict), else ``None`` to proceed. The over-eager auto-branching REQ-019 stopped
        branched on *declaration*; this is gated strictly on ``phase ∈ {build, land}``,
        never on a ``design`` step, which is what makes the automation safe.

        - ``design`` / generic (phase-less) steps run where they are (declaration stays on
          the integration branch);
        - already off the integration branch (a feature branch — production is caught
          earlier by :meth:`branch_guard`): resume the step here, no branch created;
        - on the integration branch: lazily create+switch to the REQ's feature branch, or
          reuse it if a partial prior run left it — unless it has *diverged*, which is
          surfaced, not silently merged over (D7).
        """
        if step.phase not in self.implementation_phases:
            return None
        if self.current_branch() != self.integration_branch:
            return None
        name = self.feature_branch_name(step)
        if self.git.branch_exists(name):
            if not self.git.integration_is_ancestor(self.integration_branch, name):
                self.ledger.append_event("branch_diverged", step=step.id, branch=name)
                return (
                    f"refusing to reuse feature branch '{name}' — it has diverged from "
                    f"'{self.integration_branch}' (the integration branch advanced since "
                    f"the branch was cut). Reconcile it by hand, then re-run."
                )
            self.git.switch(name)
            self.ledger.append_event("branch_reused", step=step.id, branch=name)
        else:
            self.git.create_and_switch(name)
            self.ledger.append_event("branch_created", step=step.id, branch=name)
        return None

    def ready_validate_branch(self, step: Step) -> str | None:
        """Ready the feature branch for a (possibly resumed) validate (REQ-034 Decision 5).

        Unlike :meth:`prepare_branch`, a behind-but-merged feature branch is **reconciled**
        (the integration branch merged into it), not refused as diverged: a deferred
        validate is the *expected* path ("the end of the run guarantees the integration
        branch advanced"), and the branch topology for it is the engine's to manage. Returns
        a surface message only on a genuine failure, else ``None``.

        - In-flight (already on the feature branch — develop left us there): no-op.
        - Resumed (a pending park returned HEAD to the integration branch): switch to the
          feature branch and, when it has fallen behind, reconcile it from the integration
          branch (records ``branch_reconciled``).
        """
        if self.current_branch() != self.integration_branch:
            return None  # in-flight: develop already put us on the feature branch
        name = self.feature_branch_name(step)
        if not self.git.branch_exists(name):
            return None  # no branch to ready (e.g. a develop that ran on integration)
        if self.git.integration_is_ancestor(self.integration_branch, name):
            self.git.switch(name)
            self.ledger.append_event("branch_reused", step=step.id, branch=name)
        else:
            self.git.reconcile_from_integration(
                self.integration_branch,
                name,
                f"{step.req}: reconcile {name} from {self.integration_branch} "
                f"for deferred validation\n\n{_TRAILER}",
            )
            self.ledger.append_event("branch_reconciled", step=step.id, branch=name)
        return None

    def return_to_integration(self) -> None:
        """Return HEAD to the integration branch (REQ-034 Decision 3) — idempotent.

        A pending/red human validation is async QA, not a project freeze: HEAD goes back to
        the integration branch so a subsequent ``steward run`` advances other eligible REQs,
        with the feature branch left intact and unmerged (Decision 4)."""
        if self.current_branch() != self.integration_branch:
            self.git.switch(self.integration_branch)

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
        # step was re-armed via `steward recover`, tell the resuming skill so it assesses
        # the failed attempt's partial edits (already in the tree) instead of starting clean.
        recovering = led.status_of(step.id) is StepStatus.RECOVER
        command = step.command + (" --recover" if recovering else "")
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
        refusal = self.branch_guard()
        if refusal is not None:  # never commit a checkpoint onto the production branch
            return StepResult(step, RunOutcome.REFUSED, refusal)
        led = self.ledger
        verified, detail = self.verifier.verify(step)
        led.append_event("verify", step=step.id, ok=verified, detail=detail[:2000])
        if not verified:
            led.set_status(step.id, StepStatus.FAILED)
            led.save()
            return StepResult(step, RunOutcome.VERIFY_FAILED, detail)
        if not step.lands:
            # REQ-030 Decision 6: a validate step follows — commit the develop work on
            # the feature branch; the land (and the merge) fire after `steward validate`.
            return self.commit_deferred(step, detail, driver="interactive")
        res = self.mechanical_land(step, detail, driver="interactive")
        if res.outcome is RunOutcome.DONE and self._merges_after(step):
            self._merge_after_land(step)
        return res

    def mechanical_land(
        self, step: Step, detail: str = "", driver: str = "headless"
    ) -> StepResult:
        """The deterministic post-green tail — **no claude** (REQ-029 Decision 2).

        The single shared routine both the batch develop path (:meth:`run_step`) and the
        interactive ``steward checkpoint`` (REQ-018) land through, so the bookkeeping is
        identical regardless of who drove the work. In order: the land gate (REQ-029
        Decision 6 — refuse if no plan names the REQ), then the verify-gated terminal flip
        (the profile marks the REQ ``done`` *before* the commit so it rides the one
        checkpoint commit), the single authoritative commit, and the ledger advance.

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
                dec = Decision(
                    id=led.next_decision_id(),
                    step=step.id,
                    question=refusal,
                    req=step.req,
                )
                led.park_decision(dec)
                led.set_status(step.id, StepStatus.BLOCKED)
                led.save()
                led.append_event("land_refused", step=step.id, detail=refusal)
                return StepResult(step, RunOutcome.PARKED, refusal)
        if self.on_verified is not None:
            self.on_verified(step)
        sha = self._commit(step)
        led.set_cursor(step.id)
        led.set_status(step.id, StepStatus.DONE)
        led.save()
        led.append_event("checkpoint", step=step.id, commit=sha, driver=driver)
        return StepResult(step, RunOutcome.DONE, detail, commit=sha)

    def commit_deferred(
        self, step: Step, detail: str = "", driver: str = "headless"
    ) -> StepResult:
        """Close a green non-landing step (REQ-030 Decision 6) — commit, no land.

        The develop work is committed on the feature branch and the ledger advances, but
        the REQ stays active: no ``done`` flip, no index touch, no land gate, no merge.
        Those fire from the trailing ``validate`` step's green (:meth:`mechanical_land`).
        """
        led = self.ledger
        sha = self._commit(step)
        led.set_cursor(step.id)
        led.set_status(step.id, StepStatus.DONE)
        led.save()
        led.append_event(
            "develop_committed", step=step.id, commit=sha, driver=driver
        )
        # REQ-032: the trailing ledger write (status done + develop_committed event) is
        # committed as a follow-up to the work commit, so the feature branch is clean at
        # rest while it waits for its validate sibling (Decision 1 — no dirty handoff).
        self._commit_ledger_close(step, "ledger checkpoint")
        return StepResult(step, RunOutcome.DONE, detail, commit=sha)

    def _merges_after(self, step: Step) -> bool:
        """Whether a green land on ``step`` closes the feature branch (``--no-ff`` merge).

        Only a *landing* implementation step merges — a develop step that deferred to a
        validate step leaves the branch open for it (REQ-030 Decision 6); generic
        (phase-less) steps never managed topology in the first place.
        """
        return step.lands and step.phase in self.implementation_phases

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

        # Budget exhausted, still red → park for a human (REQ-029 Decision 3).
        dec = Decision(
            id=led.next_decision_id(),
            step=step.id,
            question=(
                f"{step.req or step.id}: gate still red after {self.repair_budget} "
                f"repair attempts — needs a human"
            ),
            req=step.req,
        )
        led.park_decision(dec)
        led.set_status(step.id, StepStatus.BLOCKED)
        led.save()
        led.append_event(
            "repair_exhausted", step=step.id, attempts=self.repair_budget
        )
        return StepResult(step, RunOutcome.PARKED, dec.question)

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
        try:
            return self.git.commit_all(message)
        except subprocess.CalledProcessError:
            return None

    def _commit_ledger_close(self, step: Step, subject: str) -> str | None:
        """Commit the trailing ledger write (and any captured evidence) on the active
        branch as a follow-up, so a terminal step outcome leaves a clean tree (REQ-032).

        ``git.commit_all`` stages ``-A`` and returns ``None`` when the tree is already
        clean, so a no-op path makes **no empty commit** (Decision 4). It rides the step's
        own branch context — the feature branch when one exists, else the integration
        branch (Decision 3); the drivers' up-front :meth:`branch_guard` keeps every caller
        off the production branch, so no extra guard is needed here. Tolerant of a missing
        repo / failed commit the same way :meth:`_commit` is, so a non-git test harness or
        a committer-stubbed land does not crash on the trailing close.
        """
        try:
            return self.git.commit_all(f"{step.req or step.id}: {subject}\n\n{_TRAILER}")
        except subprocess.CalledProcessError:
            return None

    # -- branch lifecycle ------------------------------------------------------

    def _drive_step(
        self,
        step: Step,
        *,
        unattended: bool,
        on_event: Callable[[dict], None] | None,
    ) -> StepResult:
        """Bracket :meth:`run_step` with topology management (REQ-020): prepare the feature
        branch before, auto-merge after a green land. Shared by both drivers."""
        surfaced = self.prepare_branch(step)
        if surfaced is not None:
            self.ledger.append_event("branch_surfaced", step=step.id, detail=surfaced)
            return StepResult(step, RunOutcome.REFUSED, surfaced)
        res = self.run_step(step, unattended=unattended, on_event=on_event)
        if res.outcome is RunOutcome.DONE and self._merges_after(step):
            self._merge_after_land(step)
        elif res.outcome is RunOutcome.PARKED:
            # REQ-032: a park is a terminal outcome — every park path (attended, skill,
            # land-gate refusal, repair-exhausted, in-flight validate red/manual) funnels
            # back here. Commit the parked decision, the red event, and any captured
            # evidence so the batch loop's next step branches off a clean tree rather than
            # riding this step's ledger writes (the mixed-provenance leak). A REFUSED
            # (diverged branch) deliberately halts the run for a human and is left as-is.
            self._commit_ledger_close(step, "ledger close — parked")
        return res

    def _merge_after_land(self, step: Step) -> None:
        """Reconcile the trailing ledger write and merge the feature branch (D4, D6).

        ``run_step`` writes the final cursor (``status: done`` + the ``checkpoint`` event)
        *after* its land commit, leaving ``state.yaml``/``events.jsonl`` dirty on the
        feature branch. Commit that as a **follow-up** (never ``--amend`` — amending would
        change the land-commit hash the just-recorded ``checkpoint`` points at), then merge
        ``--no-ff`` so the integration branch is clean at rest with an auditable boundary.
        """
        feature = self.current_branch()
        if feature == self.integration_branch:
            return  # nothing was branched (e.g. land ran on the integration branch)
        title = step.title or step.id
        self.git.commit_all(f"{step.req}: ledger checkpoint\n\n{_TRAILER}")
        self.git.switch(self.integration_branch)
        self.git.merge_no_ff(
            feature,
            f"Merge {feature} into {self.integration_branch} — {step.req} {title}\n\n{_TRAILER}",
        )
        self.ledger.append_event(
            "branch_merged", step=step.id, branch=feature, into=self.integration_branch
        )
        # REQ-032: commit the branch_merged event as its own follow-up on the integration
        # branch (Decision 2 — the proven hand-made shape, never an `--amend` that would
        # move the hash the just-recorded events point at), so the integration branch is
        # actually clean at rest, as this method's docstring has always promised.
        self._commit_ledger_close(step, "ledger close — branch_merged event")

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
        refusal = self.branch_guard()
        if refusal is not None:
            self.ledger.append_event("branch_refused", branch=self.current_branch())
            return StepResult(self.next_eligible(only=only), RunOutcome.REFUSED, refusal)
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
        refusal = self.branch_guard()
        if refusal is not None:
            self.ledger.append_event("branch_refused", branch=self.current_branch())
            return [StepResult(self.next_eligible(only=only), RunOutcome.REFUSED, refusal)]
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
                # A diverged feature branch was surfaced (D7): stop so a human reconciles.
                break
            if res.outcome is RunOutcome.LIMIT:
                # Out of quota: stop the whole run (step is back to PENDING).
                break
            if res.outcome is RunOutcome.FAILED:
                # Hard failure: stop so a human can look (step stays FAILED).
                break
        return results
