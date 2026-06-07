"""REQ-015 — the REQ profile's verifier: give the guarantee teeth where it matters.

The generic :class:`~devsteward.core.verify.CommandVerifier` marker-trusts any step that
declares no tests. For the REQ workflow that is exactly the false-done hole: ``design`` and
``build`` carry no per-phase tests, so on the generic verifier *every* phase auto-passed —
and a REQ that declared no acceptance tests at all reached ``done`` without the engine ever
running anything (an empty no-op once landed this way).

:class:`ReqVerifier` keeps design/build permissive (they only advance the cursor — the REQ
is not delivered until it lands) but makes **land** airtight: a ``land`` step *must* run at
least one named acceptance test. A land step with no tests is refused, not trusted. That is
where "unattended automation can't be talked into a false done" actually has to hold,
because a no-op build is then caught at land when its acceptance tests fail.
"""

from __future__ import annotations

from ...core.model import Step
from ...core.verify import CommandVerifier


class ReqVerifier:
    """Wrap :class:`CommandVerifier` with one rule: a ``land`` step must verify for real."""

    def __init__(self, cwd: str | None = None, timeout: float = 1800.0):
        self._inner = CommandVerifier(cwd=cwd, timeout=timeout)

    def verify(self, step: Step) -> tuple[bool, str]:
        if step.phase == "land" and not step.verify:
            return (
                False,
                "land step has no acceptance tests — a REQ cannot land on marker-trust; "
                "declare at least one runnable acceptance criterion the engine re-runs",
            )
        # design/build (no per-phase tests) → marker-trust via the inner verifier; the
        # guarantee is enforced at land. land-with-tests → the tests are re-run for real.
        return self._inner.verify(step)
