"""Derive executor steps from REQ files — the REQ profile's :class:`StepSource`.

Each **active** requirement (``open``/``in-progress``/``blocked``) yields three steps in
order: ``REQ-NNN:design`` → ``REQ-NNN:build`` → ``REQ-NNN:land``. The land step carries
the requirement's acceptance ``test:`` commands as its verification.

Whole requirements are sequenced in dependency order: ``REQ-B:design`` depends on
``REQ-A:land`` for each dependency ``REQ-A``. Dependencies that are already ``done`` are
*satisfied* and dropped. A dependency that is **not** active and **not** done (draft,
dropped, superseded, or missing) yields a dangling dependency id that no step satisfies —
so the dependent stays correctly blocked until the situation is fixed (the linter flags it).
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
        out: list[Step] = []
        for r in reqs:
            if not r.is_active:
                continue  # draft = not ready; terminal = no work
            design_deps: list[str] = []
            for dep in r.depends_on:
                dep_req = by_id.get(dep)
                if dep_req is not None and dep_req.status == "done":
                    continue  # satisfied — drop it
                design_deps.append(f"{dep}:land")  # active resolves; otherwise blocks
            prev: str | None = None
            for phase in PHASES:
                sid = f"{r.id}:{phase}"
                deps = tuple(design_deps) if phase == "design" else (prev,)
                verify = (
                    tuple(c.test for c in r.acceptance if c.test)
                    if phase == "land"
                    else ()
                )
                out.append(
                    Step(
                        id=sid,
                        command=f"{_COMMAND} {r.id} {phase}",
                        depends_on=tuple(d for d in deps if d),
                        verify=verify,
                        title=f"{r.title} — {phase}",
                        req=r.id,
                        phase=phase,
                        slug=_slugify(r.title),
                    )
                )
                prev = sid
        return out
