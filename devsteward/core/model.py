"""Core data model — content-agnostic.

A :class:`Step` is the atomic unit the executor walks. A :class:`Decision` is a fork
parked while running unattended (park-and-surface). Neither knows anything about REQs;
the REQ profile fills the optional ``req``/``phase`` fields for its own bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class StepStatus(str, Enum):
    """Authoritative status of a step, owned by the ledger."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    BLOCKED = "blocked-on-decision"
    FAILED = "failed"


class DecisionStatus(str, Enum):
    OPEN = "open"
    ANSWERED = "answered"


@dataclass(frozen=True)
class AcceptanceCheck:
    """One acceptance criterion: a human ``text`` and a runnable ``test`` id."""

    id: str
    text: str
    test: str
    status: str = "pending"  # pending | pass | fail (engine-owned)


@dataclass(frozen=True)
class Step:
    """A unit of work the executor can run.

    ``command`` is the headless Claude prompt (e.g. ``"/advance"``). ``depends_on``
    lists the ids of steps that must be ``DONE`` before this one is eligible. ``verify``
    lists the test commands the verifier must see green before the step is marked done.
    ``req``/``phase``/``slug`` are profile bookkeeping (unused by the generic profile);
    ``slug`` feeds the feature-branch name when the executor manages topology (REQ-020).
    """

    id: str
    command: str
    depends_on: tuple[str, ...] = ()
    verify: tuple[str, ...] = ()
    title: str = ""
    req: str | None = None
    phase: str | None = None
    slug: str = ""  # short branch-name segment; the profile (not the core) derives it


@dataclass
class Decision:
    """A parked fork: recorded, surfaced, and resumed once answered."""

    id: str
    step: str
    question: str
    status: DecisionStatus = DecisionStatus.OPEN
    options: list[str] = field(default_factory=list)
    answer: str | None = None
    req: str | None = None
    raised_at: str | None = None
    answered_at: str | None = None
