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

Attended (`advance_once`) does exactly one step interactively-friendly; unattended
(`run`) marches every eligible step, parking on forks.
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


@dataclass
class StepResult:
    step: Step
    outcome: RunOutcome
    detail: str = ""
    commit: str | None = None


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
    ):
        self.root = Path(root)
        self.source = source
        self.verifier = verifier
        self.accounts = accounts
        self.runner = runner
        self.committer = committer
        self.autocommit = autocommit
        self.ledger = Ledger(self.root)

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

    def run_step(self, step: Step, *, unattended: bool = True) -> StepResult:
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
        )

        if result.outcome is claude_mod.Outcome.USAGE_LIMIT:
            led.set_status(step.id, StepStatus.PENDING)
            led.save()
            led.append_event("usage_limit", step=step.id)
            return StepResult(step, RunOutcome.LIMIT, "claude usage limit")

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

    def advance_once(self, *, unattended: bool = False) -> StepResult | None:
        """Attended: run exactly one eligible step (or None if nothing is eligible)."""
        step = self.next_eligible()
        if step is None:
            return None
        return self.run_step(step, unattended=unattended)

    def run(self, *, max_steps: int | None = None) -> list[StepResult]:
        """Unattended: march eligible steps headless, parking on forks.

        A parked step is BLOCKED (not eligible), so the loop naturally advances to the
        next independent step and stops when nothing is eligible.
        """
        results: list[StepResult] = []
        count = 0
        while True:
            if max_steps is not None and count >= max_steps:
                break
            step = self.next_eligible()
            if step is None:
                break
            res = self.run_step(step, unattended=True)
            results.append(res)
            count += 1
            if res.outcome is RunOutcome.LIMIT:
                # Out of quota: stop the whole run (step is back to PENDING).
                break
            if res.outcome is RunOutcome.FAILED:
                # Hard failure: stop so a human can look (step stays FAILED).
                break
        return results
