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

from collections.abc import Callable

from ...core.model import Step
from . import index as index_mod
from .reqfile import load_reqs, set_frontmatter_status


class ReqDoneFlipper:
    """Flip a REQ to ``done`` (frontmatter + index) when its ``develop`` step verifies.

    Only the *landing* phase flips the REQ status: ``develop`` (REQ-029), or ``validate``
    when the REQ declared a System-Test phase (REQ-030 Decision 6 — develop then defers
    and the validate land is the terminal one); any other phase leaves it active.
    Idempotent: re-flipping an already-``done`` REQ is a no-op, so an interactive
    ``steward checkpoint`` re-run is safe.
    """

    def __init__(self, req_dir: Path, index_path: Path):
        self.req_dir = Path(req_dir)
        self.index_path = Path(index_path)

    def __call__(self, step: Step) -> set[Path]:
        """Flip the REQ + index to ``done`` and return the absolute paths written.

        The flip lands in the worktree before the caller's whole-tree code commit (REQ-079),
        so it rides the one commit like any other write of this step (same-commit
        discipline). Returns an empty set when there is nothing to flip (a non-landing phase
        or a missing REQ file)."""
        if step.phase not in ("develop", "validate"):
            return set()
        reqs = {r.id: r for r in load_reqs(self.req_dir)}
        req = reqs.get(step.req)
        if req is None:  # nothing to flip — a generic step or a missing REQ file
            return set()
        if req.status.lower() != "done":
            set_frontmatter_status(req.path, "done")
        index_mod.set_status(self.index_path, step.req, "done")
        return {Path(req.path), self.index_path}


class PlanArtifactGate:
    """REQ-029 Decision 6 — the mechanical land refuses to land a REQ when no file in
    ``docs/plans/`` names its REQ id.

    A grep-shaped *existence* check at the one moment it is both cheap and load-bearing
    (the land), never plan *quality*. Deliberately not a lint rule: lint would fire during
    the whole develop window, before the plan can exist. The executor calls this as its
    ``land_gate`` seam; a returned message refuses the land (the step parks), ``None``
    lets it proceed. A generic/phase-less step (no ``req``) is not gated.
    """

    def __init__(self, plans_dir: Path):
        self.plans_dir = Path(plans_dir)

    def __call__(self, step: Step) -> str | None:
        req = step.req
        if not req:
            return None
        if self.plans_dir.is_dir():
            for p in sorted(self.plans_dir.glob("*.md")):
                if req in p.read_text(encoding="utf-8"):
                    return None
        return (
            f"refusing to land {req} — no file in {self.plans_dir.name}/ names {req} "
            f"(plan-first discipline; write the plan before landing)"
        )


class ConceptArtifactGate:
    """REQ-039 — when a REQ declared ``process.concept``, the develop land additionally
    refuses unless a concept deliverable exists — a flat ``docs/concepts/REQ-NNN.md`` *or* a
    non-empty bundle directory ``docs/concepts/REQ-NNN/`` (REQ-067) — *and* the REQ's
    ``concept_refs`` reference it (the flat file or a path inside the directory).

    The left-arm counterpart of the validate phase done the *lightweight* way: there is no
    dedicated concept step, CLI verb, or skill. ``process.concept`` already makes the develop
    step attended (so batch parks it); the concept session is that ordinary attended develop
    session, and this gate is the engine-owned firewall that the architecture deliverable was
    actually produced before any code lands. Mirrors :class:`PlanArtifactGate`'s grep-shaped
    *existence* check (never concept *quality*); conditioned on the flag, so a REQ that did not
    declare a concept phase is untouched. A generic/phase-less step (no ``req``) is not gated.
    """

    def __init__(self, concepts_dir: Path, req_dir: Path):
        self.concepts_dir = Path(concepts_dir)
        self.req_dir = Path(req_dir)

    def __call__(self, step: Step) -> str | None:
        req_id = step.req
        if not req_id:
            return None
        req = {r.id: r for r in load_reqs(self.req_dir)}.get(req_id)
        if req is None or not req.process.get("concept"):
            return None  # no concept phase declared — not gated
        # Existence: the deliverable may be a flat ``REQ-NNN.md`` *or* a non-empty bundle
        # directory ``REQ-NNN/`` (REQ-067 — a durable prototype produces several files, the
        # directory is their natural home). An empty directory does not count.
        doc = self.concepts_dir / f"{req_id}.md"
        bundle = self.concepts_dir / req_id
        has_flat = doc.is_file()
        has_bundle = bundle.is_dir() and any(p.is_file() for p in bundle.rglob("*"))
        if not (has_flat or has_bundle):
            return (
                f"refusing to land {req_id} — it declared a concept phase but no "
                f"{self.concepts_dir.name}/{req_id}.md file or non-empty "
                f"{self.concepts_dir.name}/{req_id}/ bundle directory exists "
                f"(run the attended concept session and capture the architecture first)"
            )
        # Link: a ``concept_refs`` entry must name the flat file (``REQ-NNN.md``) or point
        # inside the bundle directory (``REQ-NNN/…``).
        if not any(
            f"{req_id}.md" in str(ref) or f"{req_id}/" in str(ref)
            for ref in req.concept_refs
        ):
            return (
                f"refusing to land {req_id} — its concept deliverable exists but the REQ's "
                f"concept_refs references neither {self.concepts_dir.name}/{req_id}.md nor a "
                f"path under {self.concepts_dir.name}/{req_id}/ "
                f"(link the deliverable in concept_refs)"
            )
        return None


class CompositeLandGate:
    """Run several land gates in order, first refusal wins (REQ-039 composes the plan-artifact
    gate with the concept-artifact gate). ``None`` entries are skipped; an all-clear returns
    ``None`` so the land proceeds."""

    def __init__(self, *gates: Callable[[Step], str | None] | None):
        self.gates = [g for g in gates if g is not None]

    def __call__(self, step: Step) -> str | None:
        for gate in self.gates:
            refusal = gate(step)
            if refusal is not None:
                return refusal
        return None
