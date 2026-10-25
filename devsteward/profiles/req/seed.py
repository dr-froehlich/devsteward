"""Seed a ledger for an already-built corpus — ``steward seed-ledger`` (REQ-022).

Onboarding an existing project (the memzy sequence, plan 0005) arrives with REQs whose
verdict is already settled. ``steward init`` makes an *empty* ledger; for finished history
the cursor must start at the *end*. This module marks every **terminal** REQ's phase-step(s)
``done`` with an honest provenance event, so ``steward status`` reports an all-done corpus
and ``advance``/``run`` is a correct no-op until the next ``/intake`` produces new work.

This is **not** a re-adjudication of history (the same archivist boundary REQ-010 drew): the
verdict travels verbatim from the converted ``status``; no historic suite is re-run and the
verification gate never fires. The seeder is **dialect-independent** — it reads only the
converted, schema-valid frontmatter (``id``, ``status``), so the identical command seeds
memzy, ExamEngineer, or any future onboarding (Decision 1).

It derives step ids through the profile's own helpers (:data:`PHASES`,
:func:`has_validate_step`) so it can never drift from the step source, and builds ids by
string so lettered ids (``REQ-099z``, REQ-021) seed via the identical opaque path (D6).
"""

from __future__ import annotations

from pathlib import Path

from ...core.ledger import Ledger
from ...core.model import StepStatus
from .reqfile import PHASES, load_reqs
from .source import has_validate_step


def seed_ledger(ledger: Ledger, req_dir: Path) -> list[str]:
    """Seed already-finished history into ``ledger``; return the newly-seeded REQ ids.

    For each terminal REQ (``done``/``dropped``/``superseded``) set its ``develop`` step
    (and ``validate`` when it declared an artifact/manual AC) to ``done`` and append one
    ``ledger_seed`` provenance event. Active/draft REQs are left untouched. Idempotent: a
    terminal REQ whose ``develop`` step is already ``done`` — seeded before, or genuinely
    engine-driven — is skipped (no duplicate event, no re-seed).
    """
    (phase,) = PHASES  # the one fused develop phase per REQ (REQ-029)
    seeded: list[tuple[str, list[str]]] = []

    for req in load_reqs(req_dir):
        if not req.is_terminal:
            continue  # active = genuine pending work; draft = not ready — leave for the engine
        develop_step = f"{req.id}:{phase}"
        if ledger.status_of(develop_step) is StepStatus.DONE:
            continue  # already done (seeded or driven) — idempotent skip
        step_ids = [develop_step]
        if has_validate_step(req):
            step_ids.append(f"{req.id}:validate")
        for step_id in step_ids:
            ledger.set_status(step_id, StepStatus.DONE)
        seeded.append((req.id, step_ids))

    if seeded:
        # Mirror park_decision's ordering: persist the status overlay, then the events.
        ledger.save()
        for req_id, step_ids in seeded:
            ledger.append_event("ledger_seed", req=req_id, steps=step_ids)

    return [req_id for req_id, _ in seeded]
