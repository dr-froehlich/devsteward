"""REQ-015 + REQ-029 — verify teeth: the engine refuses to land a REQ on marker-trust.

After REQ-029 the REQ profile has one delivering step, ``develop``: it carries the
acceptance tests and the engine lands the REQ mechanically only when they run green. A
develop step that declares no acceptance tests is refused, not trusted — closing the
false-done path where an empty no-op once reached DONE because every phase auto-passed.
Any non-``develop`` (generic/phase-less) step still passes on marker-trust.
"""

from __future__ import annotations

from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Step, StepStatus
from devsteward.profiles.req.verify import ReqVerifier

from conftest import FakeRunner, ListStepSource, RecordingCommitter, ok_result


def test_develop_without_tests_fails():
    """AC1: a develop step with no acceptance tests is refused (no marker-trust at land)."""
    v = ReqVerifier()
    ok, reason = v.verify(Step(id="REQ-X:develop", command="/advance", verify=(), phase="develop"))
    assert ok is False
    assert "marker-trust" in reason and "acceptance" in reason


def test_develop_runs_tests_other_phases_pass():
    """AC2: develop re-runs its named tests (green passes, red fails); a non-develop step
    with no per-phase tests still marker-trusts through, since the guarantee lives at the
    develop gate."""
    v = ReqVerifier()

    green = Step(id="REQ-X:develop", command="/advance", verify=("true",), phase="develop")
    assert v.verify(green)[0] is True
    red = Step(id="REQ-X:develop", command="/advance", verify=("false",), phase="develop")
    assert v.verify(red)[0] is False

    for phase in ("note", None):
        step = Step(id="REQ-X:other", command="/advance", verify=(), phase=phase)
        assert v.verify(step)[0] is True, f"{phase} should advance on marker-trust"


def test_executor_refuses_develop_without_tests(project):
    """AC3: end to end, the engine (executor + ReqVerifier) refuses to mark a develop step
    DONE when it declares no acceptance tests — it is FAILED and never committed."""
    step = Step(id="REQ-X:develop", command="/advance", verify=(), phase="develop")
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
    assert Ledger(project).status_of("REQ-X:develop") is StepStatus.FAILED


# --- REQ-028: a skip is not green; zero collected is not green; the full suite gates ----


def test_develop_skip_is_not_green(tmp_path):
    """AC1: a named acceptance test that *skips* fails the develop gate (skip ≠ green); a
    passing test still passes, and a non-develop step still passes on marker-trust."""
    test_file = tmp_path / "test_behaviour.py"
    test_file.write_text(
        "import pytest\n"
        "def test_proves_x():\n"
        "    pytest.skip('no live socket on a clean checkout')\n",
        encoding="utf-8",
    )
    v = ReqVerifier(cwd=str(tmp_path), full_suite=None)
    step = Step(
        id="REQ-X:develop",
        command="/advance",
        phase="develop",
        verify=(f"python -m pytest {test_file.name}::test_proves_x",),
    )
    ok, reason = v.verify(step)
    assert ok is False, reason
    assert "skip" in reason.lower()

    # the very same named test, now actually proving X, passes
    test_file.write_text("def test_proves_x():\n    assert True\n", encoding="utf-8")
    assert v.verify(step)[0] is True

    # REQ-015 Decision 2 preserved: a non-develop step carries no tests and marker-trusts
    s = Step(id="REQ-X:note", command="/advance", verify=(), phase="note")
    assert v.verify(s)[0] is True, "a non-develop step should advance on marker-trust"


def test_develop_zero_collected_is_not_green(tmp_path):
    """AC2: a named test command that collects zero tests (a non-existent, renamed, or
    unowned id) fails the gate rather than reading an empty selection as green."""
    test_file = tmp_path / "test_behaviour.py"
    test_file.write_text("def test_real():\n    assert True\n", encoding="utf-8")
    v = ReqVerifier(cwd=str(tmp_path), full_suite=None)
    step = Step(
        id="REQ-X:develop",
        command="/advance",
        phase="develop",
        verify=(f"python -m pytest {test_file.name}::test_does_not_exist",),
    )
    ok, reason = v.verify(step)
    assert ok is False, reason
    assert "0 tests" in reason

    # the real, owned test id collects and passes
    good = Step(
        id="REQ-X:develop",
        command="/advance",
        phase="develop",
        verify=(f"python -m pytest {test_file.name}::test_real",),
    )
    assert v.verify(good)[0] is True


def test_develop_full_suite_red_fails_step(tmp_path):
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
        id="REQ-X:develop",
        command="/advance",
        phase="develop",
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


# --- REQ-068: deterministic lane routing, fail-hard on a declared skip --------------------


def test_develop_gate_routes_by_check_excludes_validation(tmp_path):
    """REQ-068 AC2: the develop gate runs a REQ's ``regression`` + ``live`` lane tests and the
    hermetic full suite, but a one-time ``artifact``/``manual`` test of another (done) REQ is
    *not* run in this REQ's develop gate — the engine deselects every artifact/manual node-id
    project-wide from the full-suite run. The exclusion set is derived from frontmatter by
    :func:`devsteward.build.build_verifier`, not from a hand-edited marker expression."""
    from devsteward.build import build_verifier
    from devsteward.config import Config

    from conftest import write_index, write_req

    # A one-time artifact validation that would FAIL if it ran inside this develop gate
    # (the FlowSteward REQ-054 shape: another REQ's live System-Test flaking in the suite).
    (tmp_path / "test_validation.py").write_text(
        "def test_one_time_validation():\n    assert False, 'one-time validation — must not gate later REQs'\n",
        encoding="utf-8",
    )
    # This REQ's standing lane tests: one hermetic regression, one live — both green.
    (tmp_path / "test_lanes.py").write_text(
        "def test_regression_lane():\n    assert True\n"
        "def test_live_lane():\n    assert True\n",
        encoding="utf-8",
    )
    reqs = tmp_path / "reqs"
    # REQ-001 (done) owns the one-time artifact validation; REQ-002 (open) owns the lanes.
    write_req(reqs, "REQ-001", status="done", check="artifact",
              test="python -m pytest test_validation.py::test_one_time_validation")
    write_req(reqs, "REQ-002", status="open", check="live",
              test="python -m pytest test_lanes.py::test_live_lane")
    write_index(reqs, [("REQ-001", "validation", "DONE", "–"),
                       ("REQ-002", "lanes", "OPEN", "–")])
    cfg = Config(root=tmp_path, requirements_dir="reqs",
                 index_file="reqs/REQUIREMENTS_INDEX.md")
    v = build_verifier(cfg)

    # the engine derived the artifact node-id project-wide for deselection.
    assert "test_validation.py::test_one_time_validation" in v.exclude_nodeids

    # the develop gate: regression + live named tests + the hermetic full suite, but the
    # one-time validation is excluded — so the gate is GREEN despite that failing test.
    step = Step(
        id="REQ-002:develop", command="/advance", phase="develop",
        verify=(
            "python -m pytest test_lanes.py::test_regression_lane",
            "python -m pytest test_lanes.py::test_live_lane",
        ),
    )
    ok, detail = v.verify(step)
    assert ok is True, detail

    # control: with the validation NOT excluded, the same suite goes red — proving the
    # exclusion (not luck) is what kept the one-time test out of the standing gate.
    v.exclude_nodeids = ()
    assert v.verify(step)[0] is False


def test_live_skip_is_hard_red_unknown_skip_tolerated(tmp_path):
    """REQ-068 AC3: a ``check: live`` named test that *skips* (its declared resource absent)
    is a hard red, while an *unknown* test that skips in the full suite is still tolerated
    (REQ-063) — fail-hard applies only to a declared lane the engine knows must run."""
    # The live lane test skips (its declared resource — a live socket — is absent).
    (tmp_path / "test_live.py").write_text(
        "import pytest\n"
        "def test_live_proof():\n    pytest.skip('declared resource absent')\n",
        encoding="utf-8",
    )
    # An unknown suite member that also skips — this one must stay tolerated.
    (tmp_path / "test_unknown.py").write_text(
        "import pytest\n"
        "def test_unowned():\n    pytest.skip('optional / unowned')\n",
        encoding="utf-8",
    )
    v = ReqVerifier(cwd=str(tmp_path), full_suite="python -m pytest")
    step = Step(
        id="REQ-X:develop", command="/advance", phase="develop",
        verify=("python -m pytest test_live.py::test_live_proof",),  # the live lane, named
    )
    ok, reason = v.verify(step)
    assert ok is False, reason
    assert "skip" in reason.lower()  # the named live test's skip is the hard red

    # the live test now actually proves X → green, even though the unknown member still skips
    # in the full suite (tolerated, REQ-063).
    (tmp_path / "test_live.py").write_text(
        "def test_live_proof():\n    assert True\n", encoding="utf-8"
    )
    assert v.verify(step)[0] is True
