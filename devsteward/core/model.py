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
    RECOVER = "recover"  # an operator re-armed a FAILED step (REQ-026) — eligible again


class DecisionStatus(str, Enum):
    OPEN = "open"
    ANSWERED = "answered"


@dataclass(frozen=True)
class AcceptanceCheck:
    """One acceptance criterion: a human ``text`` and a runnable ``test`` id.

    ``check`` is the REQ-027/REQ-068 routing key (``regression | live | artifact | manual``)
    mapping the criterion onto the V-model and selecting its execution lane. The core only
    carries the value — ``""`` means *undeclared*; the REQ profile's linter enforces
    presence/enum on active REQs.
    """

    id: str
    text: str
    test: str
    status: str = "pending"  # pending | pass | fail (engine-owned)
    check: str = ""  # regression | live | artifact | manual ("" = undeclared)


@dataclass(frozen=True)
class Step:
    """A unit of work the executor can run.

    ``command`` is the headless Claude prompt (e.g. ``"/advance"``). ``depends_on``
    lists the ids of steps that must be ``DONE`` before this one is eligible. ``verify``
    lists the test commands the verifier must see green before the step is marked done.
    ``req``/``phase`` are profile bookkeeping (unused by the generic profile).
    """

    id: str
    command: str
    depends_on: tuple[str, ...] = ()
    verify: tuple[str, ...] = ()
    title: str = ""
    req: str | None = None
    phase: str | None = None
    #: This step needs a human present (the profile sets it; the core only honors it by
    #: parking in batch). REQ-029: a REQ that declared a split develop or a concept phase.
    attended: bool = False
    #: Opaque human-readable reason the step is attended (the profile fills it; the core
    #: surfaces it verbatim in the batch park decision). Empty when ``attended`` is False.
    attended_reason: str = ""
    #: Whether a green gate on this step *lands* its deliverable (terminal flip, land
    #: gate). The REQ profile sets ``False`` on a develop step that defers to a trailing
    #: ``validate`` step (REQ-030 Decision 6): the work is committed on ``dev``, but the
    #: land fires only after validation is green.
    lands: bool = True
    #: Opaque human-readable note on why the step is currently held (the profile fills
    #: it; ``steward status`` surfaces it verbatim). E.g. REQ-030 Decision 7: a validate
    #: step waiting on a not-yet-done ``process.lab`` requirement.
    blocked_note: str = ""


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
