"""REQ-015 — verify teeth: the engine refuses to *land* a REQ on marker-trust.

design/build advance the cursor (no per-phase tests); the verification guarantee is
enforced at land, where the REQ is delivered. A land step that declares no acceptance tests
is refused, not trusted — closing the false-done path where an empty no-op once reached
DONE because every phase auto-passed.
"""

from __future__ import annotations

from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Step, StepStatus
from devsteward.profiles.req.verify import ReqVerifier

from conftest import FakeRunner, ListStepSource, RecordingCommitter, ok_result


def test_land_without_tests_fails():
    """AC1: a land step with no acceptance tests is refused (no marker-trust at land)."""
    v = ReqVerifier()
    ok, reason = v.verify(Step(id="REQ-X:land", command="/advance", verify=(), phase="land"))
    assert ok is False
    assert "marker-trust" in reason and "acceptance" in reason


def test_land_runs_tests_designbuild_pass():
    """AC2: land re-runs its named tests (green passes, red fails); design/build with no
    per-phase tests still marker-trust through, since the guarantee lives at land."""
    v = ReqVerifier()

    green = Step(id="REQ-X:land", command="/advance", verify=("true",), phase="land")
    assert v.verify(green)[0] is True
    red = Step(id="REQ-X:land", command="/advance", verify=("false",), phase="land")
    assert v.verify(red)[0] is False

    for phase in ("design", "build"):
        step = Step(id=f"REQ-X:{phase}", command="/advance", verify=(), phase=phase)
        assert v.verify(step)[0] is True, f"{phase} should advance on marker-trust"


def test_executor_refuses_land_without_tests(project):
    """AC3: end to end, the engine (executor + ReqVerifier) refuses to mark a land step
    DONE when it declares no acceptance tests — it is FAILED and never committed."""
    step = Step(id="REQ-X:land", command="/advance", verify=(), phase="land")
    committer = RecordingCommitter()
    ex = Executor(
        root=project,
        source=ListStepSource([step]),
        verifier=ReqVerifier(cwd=str(project)),
        accounts=SingleAccountProvider(),
        runner=FakeRunner(default=ok_result()),
        committer=committer,
    )

    res = ex.run_step(step)
    assert res.outcome is RunOutcome.VERIFY_FAILED
    assert committer.committed == []
    assert Ledger(project).status_of("REQ-X:land") is StepStatus.FAILED
