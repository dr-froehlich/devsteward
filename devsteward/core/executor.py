"""The executor loop — the content-agnostic heart.

For each eligible step (all dependencies ``DONE``, status ``PENDING``):

1. set the cursor and announce ``step_started``;
2. precheck the account/quota gate — which waits out a saturated budget and re-gates, so a
   step killed by a limit is requeued ``RECOVER`` and *relaunched* through this same gate
   rather than ending the run (REQ-080); never fail a step over quota;
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

import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from . import attribution
from . import claude as claude_mod
from .accounts import BudgetVerdict
from .git import GitCli
from .invariants import check_invariants
from .ledger import LEDGER_DIRNAME, Ledger
from .model import Decision, DecisionStatus, Step, StepStatus
from .seams import AccountProvider, GitTopology, StepSource, Verifier
from .transaction import transaction
from .verify import (
    NoUsableEnvError,
    _is_pytest_command,
    _pytest_outcome,
    _rebind_interpreter,
    resolve_test_interpreter,
)

PARK_SENTINEL = "[[DEVSTEWARD_PARK]]"

# REQ-091: where a spawn's model must be answered. Named as **keys and a filename, never a
# value** — REQ-090's rule (no model identifier in engine Python) holds in the diagnostic and
# error paths too, which is exactly where a "helpful" example string would creep back in.
MODEL_CONFIG_KEY = "claude.model"
MODEL_CONFIG_FILE = f"{LEDGER_DIRNAME}/config.yaml"


def unconfigured_model_notice(kind: str) -> str:
    """Why a ``{kind}`` session has no model, and where to answer it (REQ-091).

    REQ-090 made "unset means claude's own default" a legitimate behaviour; it became a trap
    only because it was *silent* — twelve stamped projects spawned every develop, repair and
    validate session on a model nobody chose, and the operator could see *that* it happened
    but not *why*. This is the sentence that closes that asymmetry.
    """
    return (
        f"no model is configured for the {kind} session — set `{MODEL_CONFIG_KEY}` "
        f"(or `claude.steps.{kind}.model` for this kind alone) in {MODEL_CONFIG_FILE}"
    )


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
    #: REQ-080: for a ``LIMIT`` outcome only — may ``run`` ride through it rather than stop?
    #: True when a budget oracle answered and the consecutive-limit guard has not tripped, so
    #: the next loop iteration's ``precheck`` gate can wait the window out and relaunch. The
    #: outcome is still LIMIT (the step *was* interrupted); only the loop's reaction varies —
    #: which is why this is a field and not a second outcome.
    resumable: bool = False


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
        # REQ-088: returns the paths it wrote, so the land can stage them content-blind.
        on_verified: Callable[[Step], set[Path] | None] | None = None,
        land_gate: Callable[[Step], str | None] | None = None,
        step_claude: dict[str, tuple[str | None, str | None]] | None = None,
        repair_budget: int = 0,
        validate_runner: Callable[..., "StepResult"] | None = None,
        interactive_runner: Callable[..., int] = claude_mod.run_claude_interactive,
        verify_env_file: str | None = ".env",
        announce: Callable[[str], None] | None = None,
        attribution_trailer: bool = True,
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
        # REQ-072: the operator's declared env-file (``verify.env_file``, default ``.env``),
        # carried into the capture self-check's tree extract when present so the check runs
        # in the same declared environment the develop gate used. None disables the carry.
        self.verify_env_file = verify_env_file
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
        # REQ-080 Decision 5: the consecutive-limit guard's state — how many limit deaths in
        # a row on `_limit_streak_step` with no intervening gate wait and no step completion.
        self._limit_streak = 0
        self._limit_streak_step: str | None = None
        # REQ-091: the operator-visible sink for engine-side facts (the same stderr channel
        # the account provider already announces quota waits on — one visibility channel, not
        # a second one). None in tests and in a caller that renders nothing.
        self.announce = announce
        # REQ-091 Decision 12: whether engine commits carry the attribution trailer at all.
        # A repo whose contributor policy bans AI trailers turns it off in its own config;
        # there is deliberately no seam for the trailer's *key or format*.
        self.attribution_trailer = attribution_trailer
        # REQ-091 Decision 10: the model the engine last resolved for a session it spawned.
        # The commit trailer reads this — for a spawned step the engine is not guessing, it
        # chose the model itself. Stays None through an interactive `steward checkpoint`
        # (nothing was spawned), which is exactly when the env-var / unknown path applies.
        self._spawn_model: str | None = None

    #: REQ-080 Decision 5: limit deaths in a row on one step — with clauder saying "proceed"
    #: throughout and no step completing — before the run stops instead of relaunching again.
    #: Bounds the tight spin where the account state and clauder's view disagree, and bounds
    #: Decision 2's accepted risk (a genuine code error coinciding with an exhausted budget).
    max_consecutive_limits = 3

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
        self, step: Step, evidence_rel: str, *, on_event=None, ac_flag: str = ""
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
                f"drive it warm (REQ-081): `steward validate-start {step.req}` in this "
                f"session, capture the evidence here, then record the verdict from a plain "
                f"shell with `steward validate-record {step.req}`."
            )
        # The guided bring-up is interactive by construction (a foreground session with the
        # operator at the TTY), so an unconfigured model warns rather than refuses.
        model, effort, _ = self._resolve_spawn("validate", step=step, unattended=False)
        # REQ-075 AC1: ``ac_flag`` names the scoped ACs (``--ac AC1,AC3``) on a red-only
        # re-run; empty for a full validation.
        command = f"/system-test {step.req} --evidence {evidence_rel}{ac_flag} --guided"
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

    def _announce(self, msg: str) -> None:
        """Say something to the operator, if anyone is listening (REQ-091)."""
        if self.announce is not None:
            self.announce(msg)

    def _resolve_spawn(
        self, kind: str, *, step: Step | None = None, unattended: bool = True
    ) -> tuple[str | None, str | None, str | None]:
        """Resolve **and surface** the ``(model, effort)`` for a ``kind`` session (REQ-091).

        Returns ``(model, effort, refusal)``. A non-None ``refusal`` means *nothing was
        spawned* and the caller must return it as the step's surface — the engine does not
        start an unattended session on a model nobody chose.

        Three things happen here that did not before:

        * the resolved model is **announced** and recorded as a ``spawn_model`` ledger event,
          so what a session costs is visible at the moment it is spent rather than inferable
          only by reading engine source — which consumers are explicitly forbidden to do;
        * an unset model in an **unattended** run refuses (Decision 2): the expensive failure
          is ``steward run`` marching a queue of REQs on an unintended model for hours with
          nobody watching;
        * an unset model in an **attended** run warns and proceeds, preserving REQ-090's
          "unset means claude's own default" contract for the interactive case. The operator
          sees the warning and can decide in the moment; blocking them would be paternalism.

        A CLI ``--model`` override needs no special case: ``build_executor`` folds it into
        ``step_claude['develop']``, so it arrives here already *configured*.
        """
        model, effort = self._claude_for(kind)
        step_id = step.id if step is not None else None
        if model:
            self._announce(f"{kind} session: model {model}, effort {effort or 'default'}")
            self.ledger.append_event(
                "spawn_model", step=step_id, kind=kind, model=model, effort=effort
            )
            self._spawn_model = model
            return model, effort, None

        notice = unconfigured_model_notice(kind)
        self.ledger.append_event(
            "spawn_model", step=step_id, kind=kind, model=None, effort=effort,
            unattended=unattended,
        )
        if unattended:
            self._announce(f"refusing to spawn: {notice}")
            return None, None, notice
        self._announce(f"warning: {notice} — spawning on claude's own default")
        # Nothing was chosen, so nothing is claimed: the trailer must not inherit a model
        # from some earlier spawn in this process.
        self._spawn_model = None
        return None, effort, None

    def _sign(self, message: str) -> str:
        """Append the attribution trailer to a commit message (REQ-091).

        Naming the model the engine actually spawned with — or an explicit ``unknown`` — is
        the commit-boundary reading of the same rule ``_resolve_spawn`` enforces at the spawn
        boundary: the engine states what it knows and marks what it does not, instead of
        writing a claim that ages into a falsehood."""
        return attribution.sign(
            message, spawn_model=self._spawn_model, enabled=self.attribution_trailer
        )

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

    # -- self-healing reconcile (REQ-059) --------------------------------------

    def _reconcile_stranded_running(self) -> None:
        """Self-heal every step the ledger holds in ``RUNNING`` (REQ-059 Decision 1).

        Run at the start of ``run``/``advance_once`` — after :func:`check_invariants`,
        before step selection. The engine is single-process and synchronous over one
        ledger (trunk-based, single-writer), so a ``RUNNING`` status observed at the start
        of a fresh top-level command provably has no live owner: a prior ``SIGINT``/crash/
        power-loss died between the ``step_started`` event and any terminal event, leaving
        the inline compensation (:meth:`run_step` lines 280/301) unrun. Requeue each such
        step the way that inline compensation would have — to ``RECOVER`` when its
        interrupted attempt was itself a recovery (so the ``--repeat`` resume signal
        survives, Decision 2), else ``PENDING`` — and append an ``interrupted`` event
        naming the step. This makes the wedge self-healing: re-running ``steward run``
        proceeds, so no recovery verb is needed (subtraction over the report's #3). It is
        the line-276 requeue applied at load, not new transaction machinery."""
        led = self.ledger
        stranded = [
            sid for sid, st in led.all_statuses().items() if st is StepStatus.RUNNING
        ]
        for sid in stranded:
            requeue = (
                StepStatus.RECOVER if self._was_recovering(sid) else StepStatus.PENDING
            )
            led.set_status(sid, requeue)
            led.save()
            led.append_event("interrupted", step=sid, requeued=requeue.value)

    def _was_recovering(self, step_id: str) -> bool:
        """Whether the interrupted attempt on ``step_id`` was a recovery — read from the
        ``recover`` flag of the *last* ``step_started`` event for the step (REQ-059
        Decision 2). The status itself was overwritten to ``RUNNING`` when the attempt
        started, so the event log is the only surviving record of the recovery signal."""
        recovering = False
        for ev in self.ledger.events():
            if ev.get("event") == "step_started" and ev.get("step") == step_id:
                recovering = bool(ev.get("recover", False))
        return recovering

    # -- budget-limit interruption (REQ-080) -----------------------------------

    def _budget_verdict(self) -> tuple[BudgetVerdict, str]:
        """Probe the account provider's budget oracle, or report that there is none.

        The oracle is optional on the :class:`AccountProvider` seam (REQ-080 Decision 6), so
        read it fail-open like the other optional seams (``dirty_paths``/``write_code_tree``):
        a provider without ``budget_verdict`` — :class:`SingleAccountProvider`, a consumer's
        own stand-in — yields ``NO_ORACLE`` and therefore never rides out a limit."""
        probe = getattr(self.accounts, "budget_verdict", None)
        if probe is None:
            return BudgetVerdict.NO_ORACLE, "account provider has no budget oracle"
        return probe()

    def _reset_limit_streak(self) -> None:
        """Clear the consecutive-limit guard — real progress happened (REQ-080 Decision 5):
        either the gate genuinely waited (the budget window moved) or a step completed."""
        self._limit_streak = 0
        self._limit_streak_step = None

    def _bump_limit_streak(self, step: Step) -> bool:
        """Count this limit death against ``step`` and report whether the guard trips.

        A limit death on a *different* step starts a fresh streak: the guard is about one
        step spinning, not about limits in general."""
        if self._limit_streak_step != step.id:
            self._limit_streak_step = step.id
            self._limit_streak = 0
        self._limit_streak += 1
        return self._limit_streak >= self.max_consecutive_limits

    def _requeue_limit(
        self, step: Step, verdict: BudgetVerdict, reason: str, *, corroborated: bool
    ) -> StepResult:
        """A budget limit killed the *session* — requeue the step and say whether the run may
        ride through it (REQ-080).

        The one path every limit **death** funnels through (a classified ``USAGE_LIMIT``, a
        clauder-corroborated ``ERROR``, and the repair loop's limit), so the requeue status,
        the event, and the resume decision cannot drift apart across three call sites.

        * **Always ``RECOVER``** (Decision 4), never ``PENDING``: the killed session left
          partial edits in the tree, so the relaunch must carry ``--repeat`` and assess them
          (:meth:`run_step` derives the flag from this status). ``steward repeat`` did this
          by hand in the manual workflow; the automatic resume must do it deliberately —
          REQ-079's whole-tree doctrine means those edits *will* be committed by whichever
          session lands next, so the resuming one had better have read them.
        * **Resumable** iff an oracle answered (``NO_ORACLE`` → stop, Decision 6: no honest
          signal for when the budget clears, and the engine does not blind-poll) **and** the
          guard has not tripped (Decision 5). An ``AVAILABLE`` verdict still resumes: the
          runtime signal is authoritative that a limit happened and clauder's usage view may
          simply lag — that disagreement is exactly what the guard bounds.

        Note the *gate*-side stops (``precheck`` returning not-ok: unsatisfiable, or a stop
        request) do **not** come here — no session ran, so there is nothing to recover, and
        the REQ's own stop list names them as terminal.
        """
        led = self.ledger
        led.set_status(step.id, StepStatus.RECOVER)
        led.save()
        tripped = self._bump_limit_streak(step)
        resumable = verdict is not BudgetVerdict.NO_ORACLE and not tripped
        led.append_event(
            "usage_limit",
            step=step.id,
            corroborated=corroborated,
            verdict=verdict.value,
            reason=reason,
            resumable=resumable,
            consecutive=self._limit_streak,
        )
        if tripped:
            led.append_event(
                "limit_guard", step=step.id, consecutive=self._limit_streak,
                detail=(
                    f"{self._limit_streak} limit deaths in a row on {step.id} with no gate "
                    f"wait and no progress — stopping instead of relaunching again."
                ),
            )
        if corroborated:
            detail = f"session error with no limit marker — corroborated as a limit by {reason}"
        else:
            detail = f"claude usage limit ({reason})"
        if tripped:
            detail += f" — {self._limit_streak} in a row on this step, stopping"
        elif not resumable:
            detail += " — no budget oracle, stopping"
        return StepResult(step, RunOutcome.LIMIT, detail, resumable=resumable)

    def only_ineligibility_reason(self, req_id: str) -> str:
        """Name *why* ``--only req_id`` selected nothing (REQ-026 D8) from the actual step
        statuses — never fabricating a dependency cause (REQ-059 Decision 3).

        Beyond not-active and already-done, the obstruction is diagnosed on the first
        not-yet-``DONE`` step: a ``RUNNING`` strand as interrupted, a ``BLOCKED`` step as
        parked, a ``FAILED`` step as failed — and *"blocked on an unfinished dependency"*
        **only** when a ``depends_on`` entry is genuinely not ``DONE``, naming it."""
        steps = [s for s in self.steps() if s.req == req_id]
        if not steps:
            return (
                f"{req_id} has no eligible step — it is not active "
                f"(activate it first with `steward activate {req_id}`, or it does not exist)."
            )
        statuses = {s.id: self.ledger.status_of(s.id) for s in steps}
        if all(st is StepStatus.DONE for st in statuses.values()):
            return f"{req_id} has no eligible step — it is already done."
        by_id = {s.id: s for s in self.steps()}
        for s in steps:
            st = statuses[s.id]
            if st is StepStatus.DONE:
                continue
            if st is StepStatus.RUNNING:
                return (
                    f"{req_id} has no eligible step — {s.id} is stranded RUNNING from an "
                    f"interrupted prior run. Re-run `steward run {req_id}`: the startup "
                    f"sweep requeues it and the run proceeds (no hand-edit of state.yaml)."
                )
            if st is StepStatus.BLOCKED:
                # REQ-074: a blocked step is either a genuine parked fork (an open
                # decision — resolve it in the guided `steward decide` session) or a
                # hold that names its own verb.
                parked = next(
                    (d for d in self.ledger.open_decisions() if d.step == s.id), None
                )
                if parked is not None:
                    return (
                        f"{req_id} has no eligible step — {s.id} is parked on an open "
                        f"fork ({parked.id}). Resolve it with `steward decide {parked.id}`."
                    )
                hold = self.ledger.hold_note(s.id)
                return (
                    f"{req_id} has no eligible step — {s.id} is held: "
                    f"{hold or 'blocked (see `steward status`)'}"
                )
            if st is StepStatus.FAILED:
                return (
                    f"{req_id} has no eligible step — {s.id} failed. Re-arm it with "
                    f"`steward repeat {req_id}` to retry."
                )
            # PENDING/RECOVER is runnable, so it was held out only by a dependency — name
            # the offending one. This is the *only* path that may state a dependency block,
            # and only after confirming a depends_on entry is genuinely not DONE.
            unmet = [
                d
                for d in s.depends_on
                if d not in by_id or self.ledger.status_of(d) is not StepStatus.DONE
            ]
            if unmet:
                return (
                    f"{req_id} has no eligible step — {s.id} is blocked on an unfinished "
                    f"dependency: {', '.join(unmet)}."
                )
        return f"{req_id} has no eligible step."

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
        # REQ-074: a fork the operator decided travels into the resuming session — the
        # same wire as the --repair failure brief. Without it the answer is write-only.
        command += self._answered_fork_brief(step)
        led.set_cursor(step.id)
        led.set_status(step.id, StepStatus.RUNNING)
        led.save()
        led.append_event("step_started", step=step.id, command=command, recover=recovering)

        # When the *gate* blocks a step (no session ran) it is re-queued. Keep a recovering
        # step as RECOVER so its recovery signal survives the interruption. A limit that kills
        # a running session is different — it goes through `_requeue_limit`, always RECOVER.
        requeue = StepStatus.RECOVER if recovering else StepStatus.PENDING

        # REQ-080 Decision 5: a gate that actually slept means the budget window moved, so
        # this is not the tight spin the consecutive-limit guard watches for — reset it.
        waits_before = getattr(self.accounts, "wait_count", 0)
        ok, reason = self.accounts.precheck()
        if getattr(self.accounts, "wait_count", 0) > waits_before:
            self._reset_limit_streak()
        if not ok:
            # An unsatisfiable budget or a stop request — the REQ-080 stop list. Never
            # resumable: waiting is precisely what the gate just declined to do.
            led.set_status(step.id, requeue)
            led.save()
            led.append_event("quota_block", step=step.id, reason=reason)
            return StepResult(step, RunOutcome.LIMIT, reason, resumable=False)

        model, effort, refusal = self._resolve_spawn(
            "develop", step=step, unattended=unattended
        )
        if refusal is not None:
            # REQ-091 Decision 2: never spawn an unattended session on a model nobody chose.
            # The step stays runnable — this is a config answer away, not a failure.
            led.set_status(step.id, requeue)
            led.save()
            led.append_event("spawn_refused", step=step.id, reason=refusal)
            return StepResult(step, RunOutcome.REFUSED, refusal, resumable=False)
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
            # The runtime said so outright (REQ-016's signal) — no corroboration needed.
            verdict, reason = self._budget_verdict()
            return self._requeue_limit(step, verdict, reason, corroborated=False)

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

        if result.outcome is claude_mod.Outcome.ERROR:
            # REQ-080 Decision 2: the ambiguous shape. The runtime signal (REQ-016) stays the
            # primary classifier and it said "error" — but the FlowSteward REQ-116 trace was a
            # budget death whose ending simply missed `_LIMIT_MARKERS`, and an ERROR sets the
            # step FAILED, a stopping state needing a manual `steward repeat`. Chasing every
            # future wording of the limit message into the marker table is a losing game; ask
            # the budget oracle the engine already trusts, at the moment it happened. Only an
            # EXHAUSTED verdict reclassifies — clauder saying "there is budget" leaves a
            # genuine error a genuine error.
            verdict, reason = self._budget_verdict()
            if verdict is BudgetVerdict.EXHAUSTED:
                return self._requeue_limit(step, verdict, reason, corroborated=True)

        if result.outcome in (claude_mod.Outcome.ERROR, claude_mod.Outcome.TIMEOUT):
            # A TIMEOUT is deliberately *not* corroborated: it is the watchdog killing a
            # session that went silent, which is not a budget-death shape (REQ-080 AC1 names
            # Outcome.ERROR alone).
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
        self, step: Step, detail: str = "", driver: str = "headless",
        *, run_gate: bool = True,
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
        Returns ``PARKED`` if the land gate refuses (nothing committed), ``VERIFY_FAILED`` on a
        capture gap (the work commit is **preserved** — REQ-063), else ``DONE``.

        ``run_gate`` (REQ-065): the validate phase pre-flights the same ``CompositeLandGate``
        in ``ReqValidateRoutine.start``/``__call__`` *before* spending the session, so its
        land callers pass ``run_gate=False`` — the gate is never run a second time for that
        validate step. Develop landing keeps the default (``True``).
        """
        led = self.ledger
        if run_gate and self.land_gate is not None:
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
        return self._land_checked(step, detail, driver, certify=True)

    def commit_deferred(
        self, step: Step, detail: str = "", driver: str = "headless"
    ) -> StepResult:
        """Close a green non-landing step (REQ-030 Decision 6) — commit, no land.

        The develop work is committed on ``dev`` and the ledger advances, but the REQ stays
        active: no ``done`` flip, no index touch, no land gate. Those fire from the trailing
        ``validate`` step's green (:meth:`mechanical_land`).
        """
        return self._land_checked(step, detail, driver, certify=False)

    def _land_checked(
        self, step: Step, detail: str, driver: str, *, certify: bool
    ) -> StepResult:
        """The shared post-green tail: commit the work, but only after proving the committed
        code reproduces its own green — and **never** destroying it on a gap (REQ-063).

        REQ-050 ran this check *after* committing and ``reset --hard``'d the work away on a gap,
        conflating a failed quality judgment with a failed mutation. Here the check runs against
        the **staged tree** *before* the commit (:meth:`_capture_gap`), so there is nothing to
        roll back:

        * **clean** → certify. ``certify`` lands the REQ (the ``on_verified`` ``done`` flip + the
          index ``DONE``-sync ride the one code commit — same-commit discipline), advances the
          cursor to ``DONE`` and records ``checkpoint``; ``certify=False`` (a develop step with a
          trailing validate) commits the pure code and records ``develop_committed``, deferring
          the flip to :meth:`mechanical_land` at validate time.
        * **gap** → withhold certification **without** discarding the work: commit the pure code
          (no ``done`` flip — no false claim) so the session's work is durable and **surfaced**,
          set the step ``FAILED`` (repeatable), record a ``capture_gap`` event naming the commit,
          commit the ledger close (clean tree at rest, REQ-032), and return a non-stopping
          ``VERIFY_FAILED`` — the REQ-056 shape (a mechanical failure, not a destructive
          exception). ``steward repeat`` resumes it once the missing source is tracked.
        """
        led = self.ledger
        gap = self._capture_gap(step)
        if gap is not None:
            # pure code — preserve the session's work, never reset
            sha = self._commit(step)
            led.set_status(step.id, StepStatus.FAILED)
            led.save()
            led.append_event("capture_gap", step=step.id, commit=sha, detail=gap)
            self._commit_ledger_close(step, "ledger close — capture gap")
            return StepResult(
                step, RunOutcome.VERIFY_FAILED, self._capture_gap_message(step, sha, gap),
                commit=sha,
            )
        # REQ-077: the flip (frontmatter + index) is written before the commit so it rides the
        # one code commit (same-commit discipline); the whole-tree stage (REQ-079) picks it up
        # like any other write of this step.
        # REQ-088 Cause B: keep the paths the flip just wrote and stage them content-blind —
        # a size-preserving rewrite inside the second git cached is invisible to ``git add -A``.
        written: set[Path] = set()
        if certify and self.on_verified is not None:
            written = self.on_verified(step) or set()
        sha = self._commit(step, force_paths=written)
        self._assert_committed_clean(step)
        led.set_cursor(step.id)
        led.set_status(step.id, StepStatus.DONE)
        led.save()
        event = "checkpoint" if certify else "develop_committed"
        led.append_event(event, step=step.id, commit=sha, driver=driver)
        # REQ-032: the trailing ledger write lands as a follow-up commit, so a terminal step
        # outcome leaves a clean tree.
        self._commit_ledger_close(step, "ledger checkpoint")
        return StepResult(step, RunOutcome.DONE, detail, commit=sha)

    def _park_attended(self, step: Step) -> StepResult:
        """Park an attended step in batch (REQ-029 Decision 9): leave the step BLOCKED with
        a hold naming the attended need, spawning no claude session.

        REQ-074: needing a human *present* is a scheduling hold, not a fork — recording it
        as a decision invited the circular answer→re-run→re-park trap. The hold's verb is
        running the step attended."""
        led = self.ledger
        note = (
            step.attended_reason
            or f"{step.req or step.id} needs an attended session"
        ) + f" — run `/advance {step.req or step.id}` in a live session."
        led.set_hold(step.id, note)
        led.save()
        led.append_event("attended_parked", step=step.id, reason=step.attended_reason)
        return StepResult(step, RunOutcome.PARKED, step.attended_reason)

    def _answered_fork_brief(self, step: Step) -> str:
        """The delivery wire for a decided fork (REQ-074): the most recent *answered*
        decision on this step, formatted for the resuming session's prompt. Empty when
        none exists. Idempotent — a decision, once made, stays valid context on re-runs."""
        answered = [
            d
            for d in self.ledger.decisions()
            if d.step == step.id and d.status is DecisionStatus.ANSWERED and d.answer
        ]
        if not answered:
            return ""
        d = answered[-1]
        rationale = f"\nRationale: {d.rationale}" if d.rationale else ""
        return (
            f"\n\nA fork parked on this step was decided by the operator ({d.id}):\n"
            f"Question: {d.question}\n"
            f"Choice: {d.answer}{rationale}\n"
            f"Honor this decision; do not re-open the fork."
        )

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
        model, effort, refusal = self._resolve_spawn(
            "repair", step=step, unattended=unattended
        )
        if refusal is not None:
            # A repair session is the *cheap* cold restart by design (REQ-029 D4), so an
            # unconfigured one is the costliest silent upgrade of the three kinds — refuse it
            # like any other unattended spawn rather than quietly running the top model.
            led.set_status(step.id, StepStatus.PENDING)
            led.save()
            led.append_event("spawn_refused", step=step.id, reason=refusal)
            return StepResult(step, RunOutcome.REFUSED, refusal, resumable=False)
        for attempt in range(1, self.repair_budget + 1):
            ok, reason = self.accounts.precheck()
            if not ok:
                led.set_status(step.id, StepStatus.PENDING)
                led.save()
                led.append_event("quota_block", step=step.id, reason=reason)
                return StepResult(step, RunOutcome.LIMIT, reason, resumable=False)
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
                # REQ-080: a repair session's limit death is a limit death — same requeue,
                # same resume decision. The run loop rides it out and the relaunched develop
                # session assesses the tree; no repair-side machinery of its own.
                verdict, limit_reason = self._budget_verdict()
                return self._requeue_limit(step, verdict, limit_reason, corroborated=False)
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
            dec = self._parse_park_brief(text, step)
            self.ledger.park_decision(dec)
            return dec
        return None

    def _parse_park_brief(self, text: str, step: Step) -> Decision:
        """Parse the fork brief following the park sentinel (REQ-074).

        Line 1 after the sentinel is the question; the following block (up to a blank
        line) carries the brief: ``- <option>`` lines, a ``recommendation: <text>`` line,
        and any other lines as context — so the operator is briefed, not just questioned."""
        block = text.split(PARK_SENTINEL, 1)[1].strip().split("\n\n", 1)[0]
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        question = lines[0] if lines else ""
        options: list[str] = []
        recommendation = ""
        context_lines: list[str] = []
        for ln in lines[1:]:
            if ln.startswith("- "):
                options.append(ln[2:].strip())
            elif ln.lower().startswith("recommendation:"):
                recommendation = ln.split(":", 1)[1].strip()
            else:
                context_lines.append(ln)
        return Decision(
            id=self.ledger.next_decision_id(),
            step=step.id,
            question=question or "unspecified fork raised by skill",
            req=step.req,
            options=options,
            recommendation=recommendation,
            context="\n".join(context_lines),
        )

    def _commit(
        self, step: Step, *, force_paths: Iterable[Path | str] = ()
    ) -> str | None:
        if self.committer is not None:
            return self.committer(step)
        if not self.autocommit:
            return None
        title = step.title or step.id
        message = self._sign(f"{step.id}: {title}")
        # REQ-048: the code commit (code + REQ flip + index) never carries the ledger — the
        # cursor advances in its own trailing .devsteward/ commit. REQ-049: a git failure
        # here is *not* swallowed — it propagates to the transaction boundary, which rolls
        # the half-commit back and surfaces a RecoverableError (no silent None half-state).
        # REQ-079: the commit stages the whole dirty tree — nothing is scoped away.
        # REQ-088: plus a content-blind re-stage of the paths the caller just wrote, which
        # git's stat cache can otherwise miss (see ``GitCli._stage_code``).
        return self.git.commit_code(message, force_paths=force_paths)

    def _assert_committed_clean(self, step: Step) -> None:
        """After the code commit, fail loudly if anything did not fully land (REQ-077,
        strengthening REQ-032 from a promise into a checked invariant; kept by REQ-079).

        The whole-tree stage leaves nothing behind by construction, so *any* leftover means
        the commit did not capture what it must — raise a plain error so the enclosing
        ``transaction`` rolls the half-land back and surfaces a ``RecoverableError``; the
        engine never returns DONE over a dirty tree.

        A no-op under the in-memory fake (its ``dirty_paths`` is empty). Real-git only, and the
        ``file_at_head``-style safety net does not apply here — a missing seam simply yields no
        leftover."""
        dirty = getattr(self.git, "dirty_paths", None)
        if dirty is None:
            return
        leftover = dirty()
        if leftover:
            raise RuntimeError(
                f"{step.id}: land left {len(leftover)} path(s) uncommitted after the code "
                f"commit — {', '.join(sorted(leftover))}. The commit did not capture the "
                f"REQ flip / index sync (same-commit discipline); rolling back."
            )

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
        return self.git.commit_ledger(self._sign(f"{ref}: {subject}"))

    # -- commit integrity (REQ-050, made non-destructive by REQ-063) -----------

    def _capture_gap(self, step: Step) -> str | None:
        """Whether the code about to be committed reproduces its own named green (REQ-063).

        Run *before* the commit, against the **staged tree** (:meth:`_stage_and_write_tree` —
        exactly what ``commit_code`` will commit: tracked/staged content, no ``.gitignore``d or
        never-staged working-tree state; built from the one staging routine the commit uses,
        so the checked tree and the landed tree never diverge): re-run the step's named
        acceptance tests against a clean ``git archive`` extract of that tree. Return a
        one-line gap description if a named test no longer passes, else ``None``.

        Pre-commit by design (REQ-063 Decision 1): REQ-050 ran this *after* committing and
        ``reset --hard``'d the work away on a gap — conflating a failed quality judgment with a
        failed mutation and destroying a paid-for session. Checking the staged tree first means
        a gap is a plain return value the caller handles non-destructively; there is nothing to
        roll back.

        Real-git only and a safety net: a no-op (``None``) when there is no repo (the in-memory
        fake), no named tests, an unusable env, or no extraction tooling — a self-check that
        cannot run must not block a legitimate land.

        **Not the validate land.** A *develop* regression AC's green is pure tracked source/test
        content, faithfully reproduced from a tree extract. A *validate* step's ``verify`` is the
        ``artifact`` AC tests, whose green is established against the **live lab** and recorded as
        captured evidence — it legitimately does *not* live in ``git archive`` content, so the
        validate phase is exempt (its integrity is the evidence contract owned by the validate
        profile, not this reproduction).
        """
        if not step.verify or step.phase == "validate":
            return None
        if not (self.root / ".git").is_dir():
            return None  # the in-memory fake / no repo — nothing to extract
        tree = self._stage_and_write_tree()
        if tree is None:
            return None
        return self._green_gap_at(step, tree)

    def _stage_and_write_tree(self) -> str | None:
        """Serialize the tree :meth:`GitCli.commit_code` will commit and return its sha — the
        capture-gate mirror. Delegates to :meth:`GitCli.write_code_tree` so the gate tree and
        the commit are built from the **one** staging routine: byte-identical tree out.
        Fail-open (``None``) when the git backend has no tree seam (the in-memory fake) or
        the write fails."""
        write_code_tree = getattr(self.git, "write_code_tree", None)
        if write_code_tree is None:
            return None
        try:
            return write_code_tree()
        except (OSError, subprocess.CalledProcessError):
            return None

    def _capture_gap_message(self, step: Step, sha: str | None, gap: str) -> str:
        """The surfaced detail for a withheld certification (REQ-063 Decision 4, made
        environment-honest by REQ-072 Decision 4): name the **preserved** work commit and frame
        the gap as *the named test did not reproduce* — the cause may be a source/test file the
        commit can't hold **or** a runtime environment the capture run lacked. Never a
        single-cause "track it / fix .gitignore" hunt when every file *is* captured, and
        explicitly *never* "commit the secret", the postmortem's actively-wrong advice. The
        env-file's *contents* never enter this message (Decision 5) — it names the file and
        the cause category only."""
        where = f"preserved as commit {sha} on {self.integration_branch}" if sha else "preserved"
        env_name = self.verify_env_file or ".env"
        return (
            f"the commit recorded for {step.req or step.id} does not reproduce its green — {gap}. "
            f"The work was {where} (nothing was discarded) and {step.id} was left repeatable. "
            f"The named test did not reproduce from the recorded commit; the cause may be an "
            f"uncaptured source/test file the commit can't hold (track the *source* file — "
            f"never a secret), or a runtime environment the capture run lacked (the declared "
            f"env-file `{env_name}` is carried into the check when present — see "
            f"`verify.env_file`). Fix the cause, then `steward repeat {step.req or step.id}`."
        )

    def _green_gap_at(self, step: Step, ref: str) -> str | None:
        """Run the step's named acceptance tests against a clean extract of ``ref`` (a commit or
        tree); return a one-line gap description if any no longer passes, else ``None``.

        The interpreter is resolved against the *real* repo: the environment (the venv) is
        never part of a commit's self-sufficiency — only its source/test files are — so the
        tests run under the same interpreter, in a throwaway dir holding only what the commit
        captured **plus the operator's declared env-file** (REQ-072: the check must reproduce
        the develop gate's green in the same *declared* environment, not a stripped one). An
        unusable env or an unavailable extraction is the verifier's / operator's concern, not
        a capture gap, so it fails open (returns ``None``)."""
        try:
            interpreter = resolve_test_interpreter(str(self.root), self._verify_python())
        except NoUsableEnvError:
            return None
        timeout = float(getattr(self.verifier, "timeout", 1800.0))
        with tempfile.TemporaryDirectory(prefix="devsteward-selfcheck-") as tmp:
            if not self._extract_commit(ref, tmp):
                return None
            self._carry_env_file(tmp)
            for cmd in step.verify:
                resolved = _rebind_interpreter(cmd, interpreter)
                gap = self._reproduces_green(cmd, resolved, tmp, timeout)
                if gap is not None:
                    return gap
        return None

    def _verify_python(self) -> str | None:
        """The configured test interpreter the verifier resolves under (``verify.python``),
        if the verifier exposes one (the REQ profile's :class:`ReqVerifier` does)."""
        return getattr(self.verifier, "python", None)

    def _carry_env_file(self, dest: str) -> None:
        """Carry the operator's declared env-file into the tree extract (REQ-072).

        ``git archive`` strips gitignored content by design, but the consumer's test
        bootstrap reads its environment from an env-file in the CWD (now the extract dir) —
        so without the carry the capture check runs in a *different* environment than the
        develop gate that just passed. Copying the file into the ephemeral extract reproduces
        the declared environment for both file-reading (``dotenv``) and ``os.environ``-reading
        bootstraps (the subprocess already inherits ``os.environ``).

        Honor-when-present, never require: an unset name or an absent file is a no-op — the
        clean-checkout hermetic path is unchanged. The copy lands only in the ``0700``
        ``TemporaryDirectory`` that is deleted after the run; the file's contents never reach
        a message, event, or persisted artifact (Decision 5). Fail-open on ``OSError`` like
        the rest of the self-check — a carry that cannot run must not block a legitimate land."""
        name = self.verify_env_file
        if not name:
            return
        src = self.root / name
        if not src.is_file():
            return
        try:
            target = Path(dest) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        except OSError:
            pass

    def _extract_commit(self, ref: str, dest: str) -> bool:
        """Extract only the tracked content of ``ref`` (a commit or tree) into ``dest`` — no
        gitignored or untracked working-tree state — via ``git archive`` piped to ``tar``.
        Returns ``False`` (fail-open) if the extraction tooling is unavailable."""
        try:
            archive = subprocess.run(
                ["git", "-C", str(self.root), "archive", ref],
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
        """Return a gap description if ``resolved`` does not reproduce from ``cwd`` (the tree
        extract), else ``None``. A pytest command is judged by its per-test outcome: a
        **failure**, **error**, or **zero-collection** is a capture gap (a source/test file the
        commit can't hold); a **skip is not** (REQ-063 Decision 2). ``verify`` already forbids
        skips (REQ-028), so a named test that passed verify but only skips from the bare extract
        is missing a *runtime environment* (a DB/secret/service), not a source file — the same
        category the validate phase is exempted for. A non-pytest command is judged by exit code."""
        if _is_pytest_command(resolved):
            o = _pytest_outcome(resolved, cwd, timeout)
            if o.collected == 0:
                return f"{cmd!r} collects nothing from the recorded commit ({o.tail})"
            if o.failed or o.errors:
                return (
                    f"{cmd!r} no longer passes from the recorded commit "
                    f"({o.failed} failed, {o.errors} errors of {o.collected})"
                )
            # A skip (without a fail/error) is environment-absence, not a capture gap (REQ-063).
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
        self._reconcile_stranded_running()  # REQ-059: self-heal a strand before selection
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

        **A budget limit does not end the run** (REQ-080 Decision 3). Unattended runs exist
        to ride out exactly these windows — possibly hours until a reset — so a resumable
        LIMIT simply loops: the interrupted step was requeued RECOVER, :meth:`next_eligible`
        re-selects it, and :meth:`run_step`'s ``precheck`` enters the **existing**
        ``clauder gate`` wait/re-gate/switch loop before relaunching it with ``--repeat``.
        No new waiting machinery lives here; the resume is the absence of the old ``break``.
        The run stops only on the REQ-080 stop list — no oracle (Decision 6), an
        unsatisfiable budget, the consecutive-limit guard (Decision 5), or the stop signal.
        """
        check_invariants(self)  # REQ-049: refuse up front on production / mid-merge (raises)
        self._reconcile_stranded_running()  # REQ-059: self-heal any strand before selection
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
            if res.outcome is RunOutcome.DONE:
                # REQ-080 D5: progress — a step completed, so no step is spinning. Reset the
                # consecutive-limit guard (the streak-step check alone would not: a *different*
                # step's completion must still clear an older step's streak).
                self._reset_limit_streak()
            if res.outcome is RunOutcome.REFUSED:
                # A step refused (e.g. a validate waiting on an undone lab): stop for a human.
                break
            if res.outcome is RunOutcome.LIMIT and not res.resumable:
                # No oracle / unsatisfiable / stop requested / guard tripped — the REQ-080
                # stop list. The step is requeued for a later run.
                break
            if res.outcome is RunOutcome.FAILED:
                # Hard failure: stop so a human can look (step stays FAILED).
                break
        return results
