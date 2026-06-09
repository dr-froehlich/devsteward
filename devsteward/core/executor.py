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
is the separate **interactive** mode — the only context where `AskUserQuestion` applies
and where the skill (not the engine) verifies and commits, with no engine guarantees.
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
        implementation_phases: tuple[str, ...] = ("build", "land"),
        feature_branch_template: str = "req-{num}-{slug}",
        git: GitTopology | None = None,
        branch_resolver: Callable[[Path], str] | None = None,
        on_verified: Callable[[Step], None] | None = None,
    ):
        self.root = Path(root)
        self.source = source
        self.verifier = verifier
        self.accounts = accounts
        # Profile hook run *after* a passing verify and *before* the checkpoint commit, so
        # any status flip it makes (the REQ profile marks the REQ `done`) is gated on green
        # tests and rides in the same commit. None for the generic profile.
        self.on_verified = on_verified
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

    # -- planning --------------------------------------------------------------

    def steps(self) -> list[Step]:
        return self.source.steps(self.ledger)

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

        result = self.runner(
            command,
            argv_prefix=self.accounts.claude_argv(),
            cwd=str(self.root),
            unattended=unattended,
            permission_mode=self.permission_mode,
            model=self.model,
            effort=self.effort,
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

        # Verify: named acceptance tests must be green.
        verified, detail = self.verifier.verify(step)
        led.append_event("verify", step=step.id, ok=verified, detail=detail[:2000])
        if not verified:
            led.set_status(step.id, StepStatus.FAILED)
            led.save()
            return StepResult(step, RunOutcome.VERIFY_FAILED, detail)

        # Terminal flip (verify-gated, in-commit): let the profile mark the work done
        # *before* the commit so the status change is captured by the one checkpoint commit,
        # never authored speculatively by the skill ahead of verification.
        if self.on_verified is not None:
            self.on_verified(step)

        # Commit + advance.
        sha = self._commit(step)
        led.set_status(step.id, StepStatus.DONE)
        led.save()
        led.append_event("checkpoint", step=step.id, commit=sha)
        return StepResult(step, RunOutcome.DONE, detail, commit=sha)

    def checkpoint(self, step: Step) -> StepResult:
        """The verify → flip → commit → advance *tail*, for an interactive land the human
        already did (no ``claude`` invocation).

        Interactive ``/advance`` does the thinking and leaves the tree dirty; this command
        (``steward checkpoint``) re-runs the named acceptance tests, lets the profile flip
        the REQ ``done``, makes the one authoritative commit, and advances the ledger —
        the *same* atomic tail :meth:`run_step` uses in batch. It replaces the old manual
        hand-edit of ``state.yaml`` that let the ledger drift out of sync with a committed
        ``done`` (the REQ-025 failure shape).
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
        if self.on_verified is not None:
            self.on_verified(step)
        sha = self._commit(step)
        led.set_cursor(step.id)
        led.set_status(step.id, StepStatus.DONE)
        led.save()
        led.append_event("checkpoint", step=step.id, commit=sha)
        return StepResult(step, RunOutcome.DONE, detail, commit=sha)

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
        if res.outcome is RunOutcome.DONE and step.phase == "land":
            self._merge_after_land(step)
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
