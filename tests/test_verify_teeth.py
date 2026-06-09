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


# --- REQ-028: a skip is not green; zero collected is not green; the full suite gates ----


def test_land_skip_is_not_green(tmp_path):
    """AC1: a named acceptance test that *skips* fails the land gate (skip ≠ green); a
    passing test still passes, and design/build still pass on marker-trust."""
    test_file = tmp_path / "test_behaviour.py"
    test_file.write_text(
        "import pytest\n"
        "def test_proves_x():\n"
        "    pytest.skip('no live socket on a clean checkout')\n",
        encoding="utf-8",
    )
    v = ReqVerifier(cwd=str(tmp_path), full_suite=None)
    step = Step(
        id="REQ-X:land",
        command="/advance",
        phase="land",
        verify=(f"python -m pytest {test_file.name}::test_proves_x",),
    )
    ok, reason = v.verify(step)
    assert ok is False, reason
    assert "skip" in reason.lower()

    # the very same named test, now actually proving X, passes
    test_file.write_text("def test_proves_x():\n    assert True\n", encoding="utf-8")
    assert v.verify(step)[0] is True

    # REQ-015 Decision 2 preserved: design/build carry no tests and marker-trust through
    for phase in ("design", "build"):
        s = Step(id=f"REQ-X:{phase}", command="/advance", verify=(), phase=phase)
        assert v.verify(s)[0] is True, f"{phase} should advance on marker-trust"


def test_land_zero_collected_is_not_green(tmp_path):
    """AC2: a named test command that collects zero tests (a non-existent, renamed, or
    unowned id) fails the gate rather than reading an empty selection as green."""
    test_file = tmp_path / "test_behaviour.py"
    test_file.write_text("def test_real():\n    assert True\n", encoding="utf-8")
    v = ReqVerifier(cwd=str(tmp_path), full_suite=None)
    step = Step(
        id="REQ-X:land",
        command="/advance",
        phase="land",
        verify=(f"python -m pytest {test_file.name}::test_does_not_exist",),
    )
    ok, reason = v.verify(step)
    assert ok is False, reason
    assert "0 tests" in reason

    # the real, owned test id collects and passes
    good = Step(
        id="REQ-X:land",
        command="/advance",
        phase="land",
        verify=(f"python -m pytest {test_file.name}::test_real",),
    )
    assert v.verify(good)[0] is True


def test_land_full_suite_red_fails_step(tmp_path):
    """AC3: at land the engine runs the full project suite in addition to the named AC
    tests; a failure elsewhere fails the step even though every named AC test passes."""
    (tmp_path / "test_named.py").write_text(
        "def test_named_ac():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "test_other.py").write_text(
        "def test_other_behaviour():\n    assert False\n", encoding="utf-8"
    )
    v = ReqVerifier(cwd=str(tmp_path), full_suite="python -m pytest")
    step = Step(
        id="REQ-X:land",
        command="/advance",
        phase="land",
        verify=("python -m pytest test_named.py::test_named_ac",),
    )
    ok, reason = v.verify(step)
    assert ok is False, reason
    assert "suite" in reason.lower()

    # with the rest of the suite green, the same land — same passing named test — passes
    (tmp_path / "test_other.py").write_text(
        "def test_other_behaviour():\n    assert True\n", encoding="utf-8"
    )
    assert v.verify(step)[0] is True
