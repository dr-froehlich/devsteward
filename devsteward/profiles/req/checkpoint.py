"""Engine-owned terminal flip: a verified land marks the REQ ``done``.

The skill no longer authors ``status: done``. Doing so *before* the engine verified was
the root of premature/false dones: a failed land left a ``done`` in the working tree, and
because the step source reads the *working tree*, that stray ``done`` made the not-yet-
landed REQ look terminal (so ``steward run`` found nothing and ``recover`` could not make
it eligible again).

This hook is the REQ profile's ``on_verified`` seam. The executor calls it *after* a
passing verify and *before* the checkpoint commit, so the REQ frontmatter ``done`` and its
``REQUIREMENTS_INDEX.md`` row ``DONE`` ride in the *same* commit as the code — gated on
green acceptance tests, in lockstep (the same invariant :func:`devsteward.lifecycle.activate`
keeps for ``open``). The ledger ``DONE`` is set by the executor right after, so frontmatter,
index, and ledger can no longer diverge.
"""

from __future__ import annotations

from pathlib import Path

from ...core.model import Step
from . import index as index_mod
from .reqfile import load_reqs, set_frontmatter_status


class ReqDoneFlipper:
    """Flip a REQ to ``done`` (frontmatter + index) when its ``land`` step verifies.

    Only the terminal ``land`` phase flips the REQ status; ``design``/``build`` leave it
    active. Idempotent: re-flipping an already-``done`` REQ is a no-op, so an interactive
    ``steward checkpoint`` re-run is safe.
    """

    def __init__(self, req_dir: Path, index_path: Path):
        self.req_dir = Path(req_dir)
        self.index_path = Path(index_path)

    def __call__(self, step: Step) -> None:
        if step.phase != "land":
            return
        reqs = {r.id: r for r in load_reqs(self.req_dir)}
        req = reqs.get(step.req)
        if req is None:  # nothing to flip — a generic step or a missing REQ file
            return
        if req.status.lower() != "done":
            set_frontmatter_status(req.path, "done")
        index_mod.set_status(self.index_path, step.req, "done")
