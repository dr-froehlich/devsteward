"""Derive executor steps from REQ files — the REQ profile's :class:`StepSource`.

Each **active** requirement (``open``/``in-progress``/``blocked``) yields one
``REQ-NNN:develop`` step (REQ-029) — the single Claude session for the REQ, carrying the
requirement's ``regression`` acceptance ``test:`` commands as its verification.

**REQ-030 — the conditional System-Test phase:** a REQ that declares at least one
``artifact`` or ``manual`` acceptance criterion (the REQ-027 ``check:`` taxonomy) gets a
second step, ``REQ-NNN:validate``, between develop and the mechanical land:

* ``validate`` depends on ``REQ-NNN:develop`` **and** on the final step of every
  ``process.lab`` requirement (Decision 7 — lab availability is an eligibility
  dependency, surfaced via :attr:`Step.blocked_note`, never a red event);
* its ``verify`` carries the ``artifact`` test commands (the engine runs them itself —
  the System Tester session only preps the lab and captures artifacts);
* the develop step then gets ``lands=False`` — its green gate commits the work but the
  REQ-029 land routine fires only after validation is green (Decision 6).

Whole requirements are sequenced in dependency order: a dependent's step depends on the
dependency's **final** step (``:validate`` when it exists, else ``:develop``), so ``done``
keeps meaning *verified and validated*. Dependencies that are already ``done`` are
*satisfied* and dropped. A dependency that is **not** active and **not** done (draft,
dropped, superseded, or missing) yields a dangling dependency id that no step satisfies —
so the dependent stays correctly blocked until the situation is fixed (the linter flags it).

**Ledger reinterpretation (REQ-029 Decision 7):** the source emits only the new step ids.
Old ``:design``/``:build``/``:land`` rows left in a pre-existing ledger are orphaned
history — never rewritten, ignored for eligibility.
"""

from __future__ import annotations

from pathlib import Path

from ...core.model import Step
from .reqfile import PHASES, ReqFile, load_reqs

# Headless prompt per phase. The skill orients from the ledger cursor; the explicit
# args make a headless run unambiguous.
_COMMAND = "/advance"
# The System Tester session (REQ-030 D2) — fresh, never sees develop's diff.
_VALIDATE_COMMAND = "/system-test"

#: REQ-027 ``check:`` values routed to the validate step (REQ-030 Decision 1).
_VALIDATE_CHECKS = {"artifact", "manual"}


def has_validate_step(req: ReqFile) -> bool:
    """True iff the REQ declares at least one ``artifact`` or ``manual`` AC (D1)."""
    return any(c.check in _VALIDATE_CHECKS for c in req.acceptance)


def final_phase(req: ReqFile) -> str:
    """The phase of the REQ's last step — what dependents (and labs) wait on."""
    return "validate" if has_validate_step(req) else PHASES[0]


class ReqStepSource:
    """A :class:`devsteward.core.seams.StepSource` backed by ``docs/requirements/``."""

    def __init__(self, req_dir: Path):
        self.req_dir = Path(req_dir)

    def steps(self, ledger=None) -> list[Step]:  # ledger unused (no side effects)
        reqs = load_reqs(self.req_dir)
        by_id = {r.id: r for r in reqs}
        (phase,) = PHASES  # one fused develop phase per REQ (REQ-029)
        out: list[Step] = []

        def dep_step(dep: str) -> str | None:
            """The step id a dependency on ``dep`` resolves to, or None when satisfied."""
            dep_req = by_id.get(dep)
            if dep_req is not None and dep_req.status == "done":
                return None  # satisfied — drop it
            if dep_req is not None and dep_req.is_active:
                return f"{dep}:{final_phase(dep_req)}"
            return f"{dep}:{phase}"  # dangling (draft/terminal/missing) — blocks

        for r in reqs:
            if not r.is_active:
                continue  # draft = not ready; terminal = no work
            deps = [d for d in (dep_step(dep) for dep in r.depends_on) if d is not None]
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
            validating = has_validate_step(r)
            # The develop gate carries the regression tests; artifact tests belong to the
            # validate gate (they need the lab) and manual ACs have no runnable command.
            develop_verify = tuple(
                c.test
                for c in r.acceptance
                if c.test and c.check not in _VALIDATE_CHECKS
            )
            out.append(
                Step(
                    id=f"{r.id}:{phase}",
                    command=f"{_COMMAND} {r.id} {phase}",
                    depends_on=tuple(deps),
                    verify=develop_verify,
                    title=f"{r.title} — {phase}",
                    req=r.id,
                    phase=phase,
                    attended=bool(attended_reason),
                    attended_reason=attended_reason,
                    lands=not validating,
                )
            )
            if validating:
                # Lab availability (D7): an eligibility dependency exactly like
                # depends_on, surfaced in status — no red event, no parked decision.
                lab_deps: list[str] = []
                labs_pending: list[str] = []
                for lab in proc.get("lab", []):
                    resolved = dep_step(lab)
                    if resolved is not None:
                        lab_deps.append(resolved)
                        labs_pending.append(lab)
                out.append(
                    Step(
                        id=f"{r.id}:validate",
                        command=f"{_VALIDATE_COMMAND} {r.id}",
                        depends_on=(f"{r.id}:{phase}", *lab_deps),
                        verify=tuple(
                            c.test
                            for c in r.acceptance
                            if c.test and c.check == "artifact"
                        ),
                        title=f"{r.title} — validate",
                        req=r.id,
                        phase="validate",
                        blocked_note=(
                            "validation waiting on " + ", ".join(labs_pending)
                            if labs_pending
                            else ""
                        ),
                    )
                )
        return out
