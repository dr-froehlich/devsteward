"""Operator verbs that shape the queue: ``activate`` and ``recover`` (REQ-026).

Two pure status mutations, kept out of the content-agnostic core:

* :func:`activate` flips a REQ from ``draft``/``dropped`` to ``open``, editing the REQ
  frontmatter **and** its ``REQUIREMENTS_INDEX.md`` row in lockstep so the index↔REQ
  same-commit invariant stays green (REQ-002, D1). It leaves both files *uncommitted*
  (D3) — declaration is committed deliberately by the operator/skill.
* :func:`recover` flips a REQ's ``FAILED`` ledger step(s) to the new ``RECOVER`` status
  (a :class:`StepStatus`, not a REQ-frontmatter status — D4) so the executor re-attempts
  them. It does not touch the working tree (D6): the failed attempt's partial edits are
  left for the resuming skill to assess.

Neither verb introduces a new ``claude`` invocation or skill — recovery is picked up by
the existing ``/advance`` skill via the status flip.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .core.ledger import Ledger
from .core.model import StepStatus
from .profiles.req import index as index_mod
from .profiles.req.reqfile import load_reqs, set_frontmatter_status


class LifecycleError(Exception):
    """A refusal the CLI maps to a non-zero ``ClickException``."""


# REQ-001: never weaken a finished requirement — change direction by superseding.
_REFUSE_REOPEN = {"done", "superseded"}
# A status that already produces work — activating it is a no-op, not an error.
_ALREADY_ACTIVE = {"open", "in-progress", "blocked"}


@dataclass
class ActivateResult:
    req_id: str
    old_status: str
    new_status: str
    changed: bool
    message: str


@dataclass
class RecoverResult:
    req_id: str
    steps: list[str]  # the step ids flipped FAILED -> RECOVER


def activate(cfg: Config, req_id: str) -> ActivateResult:
    """Flip ``req_id`` to ``open`` in both the REQ frontmatter and the index row (D1).

    - unknown id → :class:`LifecycleError`;
    - ``done``/``superseded`` → :class:`LifecycleError` pointing at supersede (D2);
    - already-active (``open``/``in-progress``/``blocked``) → no-op (``changed=False``);
    - ``draft``/``dropped`` → set both to ``open`` (D2: ``dropped`` is the one terminal
      that legitimately reverses). The files are left uncommitted (D3).
    """
    reqs = {r.id: r for r in load_reqs(cfg.req_dir)}
    req = reqs.get(req_id)
    if req is None:
        raise LifecycleError(f"{req_id} is not a known requirement (no REQ file found).")
    old = req.status.lower()
    if old in _REFUSE_REOPEN:
        raise LifecycleError(
            f"{req_id} is {old} — a finished requirement is never reopened. Change "
            f"direction by superseding it with a new REQ (`supersedes: {req_id}`)."
        )
    if old in _ALREADY_ACTIVE:
        return ActivateResult(
            req_id, old, old, changed=False,
            message=f"{req_id} already active ({old}) — no-op.",
        )
    # draft / dropped -> open, both files in lockstep.
    set_frontmatter_status(req.path, "open")
    index_mod.set_status(cfg.index_path, req_id, "open")
    return ActivateResult(
        req_id, old, "open", changed=True,
        message=f"activated {req_id} ({old} -> open).",
    )


def recover(ledger: Ledger, req_id: str) -> RecoverResult:
    """Flip ``req_id``'s ``FAILED`` ledger step(s) to ``RECOVER`` and record an event (D4).

    Refuses (``LifecycleError``) when the REQ has no failed step. Leaves the working tree
    as the failed attempt left it (D6) — no git is touched.
    """
    failed = sorted(
        sid for sid, st in ledger.all_statuses().items()
        if sid.startswith(f"{req_id}:") and st is StepStatus.FAILED
    )
    if not failed:
        raise LifecycleError(
            f"{req_id} has no failed step to recover "
            f"(recover only re-arms a step the executor marked failed)."
        )
    for sid in failed:
        ledger.set_status(sid, StepStatus.RECOVER)
    ledger.save()
    ledger.append_event("step_recover", req=req_id, steps=failed)
    return RecoverResult(req_id, failed)
