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
from .ledger import Ledger
from .model import Decision, Step, StepStatus
from .seams import AccountProvider, StepSource, Verifier

PARK_SENTINEL = "[[DEVSTEWARD_PARK]]"


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


def _git_current_branch(root: Path) -> str:
    """The checked-out branch name, or ``"HEAD"`` when detached (never a real branch)."""
    res = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip()


def _git_commit(root: Path, message: str) -> str | None:
    """Stage everything and commit. Returns the new sha, or None if nothing to commit."""
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True
    )
    if not status.stdout.strip():
        return None
    subprocess.run(
        ["git", "commit", "-m", message], cwd=root, check=True, capture_output=True
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
    )
    return sha.stdout.strip()


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
        production_branch: str = "main",
        branch_resolver: Callable[[Path], str] | None = None,
    ):
        self.root = Path(root)
        self.source = source
        self.verifier = verifier
        self.accounts = accounts
        self.runner = runner
        self.committer = committer
        self.autocommit = autocommit
        self.permission_mode = permission_mode
        self.production_branch = production_branch
        self._branch_resolver = branch_resolver or _git_current_branch
        self.ledger = Ledger(self.root)

    # -- branch guard ----------------------------------------------------------

    def current_branch(self) -> str:
        return self._branch_resolver(self.root)

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

    # -- planning --------------------------------------------------------------

    def steps(self) -> list[Step]:
        return self.source.steps(self.ledger)

    def eligible_steps(self) -> list[Step]:
        """Steps whose status is PENDING and whose every dependency is DONE.

        Returned in deterministic id order so runs are reproducible.
        """
        steps = self.steps()
        by_id = {s.id: s for s in steps}
        eligible = []
        for s in steps:
            if self.ledger.status_of(s.id) is not StepStatus.PENDING:
                continue
            if all(
                d in by_id and self.ledger.status_of(d) is StepStatus.DONE
                for d in s.depends_on
            ):
                eligible.append(s)
        return sorted(eligible, key=lambda s: s.id)

    def next_eligible(self) -> Step | None:
        elig = self.eligible_steps()
        return elig[0] if elig else None

    # -- execution -------------------------------------------------------------

    def run_step(
        self,
        step: Step,
        *,
        unattended: bool = True,
        on_event: Callable[[dict], None] | None = None,
    ) -> StepResult:
        led = self.ledger
        led.set_cursor(step.id)
        led.set_status(step.id, StepStatus.RUNNING)
        led.save()
        led.append_event("step_started", step=step.id, command=step.command)

        ok, reason = self.accounts.precheck()
        if not ok:
            led.set_status(step.id, StepStatus.PENDING)
            led.save()
            led.append_event("quota_block", step=step.id, reason=reason)
            return StepResult(step, RunOutcome.LIMIT, reason)

        result = self.runner(
            step.command,
            argv_prefix=self.accounts.claude_argv(),
            cwd=str(self.root),
            unattended=unattended,
            permission_mode=self.permission_mode,
            on_event=on_event,
        )

        if result.outcome is claude_mod.Outcome.USAGE_LIMIT:
            led.set_status(step.id, StepStatus.PENDING)
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

        # Commit + advance.
        sha = self._commit(step)
        led.set_status(step.id, StepStatus.DONE)
        led.save()
        led.append_event("checkpoint", step=step.id, commit=sha)
        return StepResult(step, RunOutcome.DONE, detail, commit=sha)

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
        message = (
            f"{step.id}: {title}\n\n"
            "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
        )
        try:
            return _git_commit(self.root, message)
        except subprocess.CalledProcessError:
            return None

    # -- drivers ---------------------------------------------------------------

    def advance_once(
        self,
        *,
        unattended: bool = True,
        on_event: Callable[[dict], None] | None = None,
    ) -> StepResult | None:
        """Run exactly one eligible step headless (or None if nothing is eligible)."""
        refusal = self.branch_guard()
        if refusal is not None:
            self.ledger.append_event("branch_refused", branch=self.current_branch())
            return StepResult(self.next_eligible(), RunOutcome.REFUSED, refusal)
        step = self.next_eligible()
        if step is None:
            return None
        return self.run_step(step, unattended=unattended, on_event=on_event)

    def run(
        self,
        *,
        max_steps: int | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> list[StepResult]:
        """Unattended: march eligible steps headless, parking on forks.

        A parked step is BLOCKED (not eligible), so the loop naturally advances to the
        next independent step and stops when nothing is eligible.
        """
        refusal = self.branch_guard()
        if refusal is not None:
            self.ledger.append_event("branch_refused", branch=self.current_branch())
            return [StepResult(self.next_eligible(), RunOutcome.REFUSED, refusal)]
        results: list[StepResult] = []
        count = 0
        while True:
            if max_steps is not None and count >= max_steps:
                break
            step = self.next_eligible()
            if step is None:
                break
            res = self.run_step(step, unattended=True, on_event=on_event)
            results.append(res)
            count += 1
            if res.outcome is RunOutcome.LIMIT:
                # Out of quota: stop the whole run (step is back to PENDING).
                break
            if res.outcome is RunOutcome.FAILED:
                # Hard failure: stop so a human can look (step stays FAILED).
                break
        return results
