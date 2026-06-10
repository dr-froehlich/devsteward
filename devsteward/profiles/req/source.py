"""Derive executor steps from REQ files — the REQ profile's :class:`StepSource`.

Each **active** requirement (``open``/``in-progress``/``blocked``) yields **one** step:
``REQ-NNN:develop`` (REQ-029). It is the single Claude session for the REQ and carries the
requirement's acceptance ``test:`` commands as its verification — the gate the engine
re-runs before it lands the REQ mechanically.

Whole requirements are sequenced in dependency order: ``REQ-B:develop`` depends on
``REQ-A:develop`` for each dependency ``REQ-A``. Dependencies that are already ``done`` are
*satisfied* and dropped. A dependency that is **not** active and **not** done (draft,
dropped, superseded, or missing) yields a dangling dependency id that no step satisfies —
so the dependent stays correctly blocked until the situation is fixed (the linter flags it).

**Ledger reinterpretation (REQ-029 Decision 7):** the source emits only the new ``:develop``
ids. Old ``:design``/``:build``/``:land`` rows left in a pre-existing ledger are orphaned
history — never rewritten, ignored for eligibility. A REQ whose old-shape ``land`` is done
has frontmatter ``done`` (not active) so it yields no step; a REQ caught mid-flight is still
active and gets a fresh ``:develop`` step (PENDING by default), restarting the cursor cleanly.
"""

from __future__ import annotations

import re
from pathlib import Path

from ...core.model import Step
from .reqfile import PHASES, load_reqs

# Headless prompt per phase. The skill orients from the ledger cursor; the explicit
# args make a headless run unambiguous.
_COMMAND = "/advance"

_SLUG_MAX_WORDS = 5


def _slugify(title: str) -> str:
    """A short branch-name segment from a REQ title (REQ-020 feeds ``req-<num>-<slug>``).

    Take the headline before the first ` — ` (em dash) separator, lowercase, map runs of
    non-alphanumerics to a single hyphen, and cap at a few words. E.g.
    "Branch lifecycle automation — the executor…" → ``branch-lifecycle-automation``.
    """
    headline = title.split(" — ", 1)[0]
    words = [w for w in re.sub(r"[^a-z0-9]+", "-", headline.lower()).split("-") if w]
    return "-".join(words[:_SLUG_MAX_WORDS])


class ReqStepSource:
    """A :class:`devsteward.core.seams.StepSource` backed by ``docs/requirements/``."""

    def __init__(self, req_dir: Path):
        self.req_dir = Path(req_dir)

    def steps(self, ledger=None) -> list[Step]:  # ledger unused (no side effects)
        reqs = load_reqs(self.req_dir)
        by_id = {r.id: r for r in reqs}
        (phase,) = PHASES  # one fused phase per REQ (REQ-029)
        out: list[Step] = []
        for r in reqs:
            if not r.is_active:
                continue  # draft = not ready; terminal = no work
            deps: list[str] = []
            for dep in r.depends_on:
                dep_req = by_id.get(dep)
                if dep_req is not None and dep_req.status == "done":
                    continue  # satisfied — drop it
                deps.append(f"{dep}:{phase}")  # active resolves; otherwise blocks
            proc = r.process
            attended_reason = ""
            if proc.get("develop") == "split":
                attended_reason = (
                    f"{r.id} declared a split develop — needs an attended design review"
                )
            elif proc.get("concept"):
                attended_reason = (
                    f"{r.id} declared a concept phase — needs an attended session"
                )
            out.append(
                Step(
                    id=f"{r.id}:{phase}",
                    command=f"{_COMMAND} {r.id} {phase}",
                    depends_on=tuple(deps),
                    verify=tuple(c.test for c in r.acceptance if c.test),
                    title=f"{r.title} — {phase}",
                    req=r.id,
                    phase=phase,
                    slug=_slugify(r.title),
                    attended=bool(attended_reason),
                    attended_reason=attended_reason,
                )
            )
        return out
