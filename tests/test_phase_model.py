"""REQ-029 — the phase-model rework: one fused ``develop`` step, mechanical land on green,
bounded repair on red, per-step-kind model config, the split/concept batch-park, and ledger
reinterpretation.

These tests wire the REQ profile's real source/verifier/flipper/land-gate around a fake
``claude`` runner and an in-memory git topology, so the full develop→land (or →repair→park)
chain is exercised without a real session or checkout.
"""

from __future__ import annotations

import json

from devsteward.config import Config
from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.profiles.req import ReqStepSource
from devsteward.profiles.req.checkpoint import PlanArtifactGate, ReqDoneFlipper
from devsteward.profiles.req.verify import ReqVerifier

from conftest import (
    FakeGitTopology,
    FakeRunner,
    ok_result,
    write_index,
    write_req,
)


def _write_plan(root, *reqs):
    """Drop a plan file under ``docs/plans/`` naming the given REQ ids (REQ-029 D6)."""
    plans = root / "docs" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "0001-plan.md").write_text(
        "# Plan 0001\n\n" + "\n".join(f"Covers {r}." for r in reqs) + "\n",
        encoding="utf-8",
    )


class _ScriptedVerifier:
    """A verifier returning a fixed sequence of ``(ok, detail)`` results (then the last,
    repeated), so a test can stage a red gate that a repair turns green."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def verify(self, step):
        self.calls += 1
        idx = min(self.calls - 1, len(self._results) - 1)
        return self._results[idx]


def _events(root):
    path = root / ".devsteward" / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _executor(root, *, runner=None, verifier=None, git=None, repair_budget=0, step_claude=None):
    req_dir = root / "docs" / "requirements"
    return Executor(
        root=root,
        source=ReqStepSource(req_dir),
        verifier=verifier or ReqVerifier(cwd=str(root), full_suite=None),
        accounts=SingleAccountProvider(),
        runner=runner or FakeRunner(default=ok_result()),
        git=git or FakeGitTopology(current="dev"),
        on_verified=ReqDoneFlipper(req_dir, req_dir / "REQUIREMENTS_INDEX.md"),
        land_gate=PlanArtifactGate(root / "docs" / "plans"),
        repair_budget=repair_budget,
        step_claude=step_claude or {"develop": ("claude-opus-4-8", "high"),
                                    "repair": ("claude-sonnet-4-6", "high")},
    )


def _project_with_req(root, rid="REQ-001", *, status="open", process=None, plan=True):
    req_dir = root / "docs" / "requirements"
    write_req(req_dir, rid, status=status, process=process)
    write_index(req_dir, [(rid, f"{rid} title", status.upper(), "–")])
    if plan:
        _write_plan(root, rid)


# -- AC1 ----------------------------------------------------------------------


def test_single_develop_step(tmp_path):
    """The step source yields exactly one ``develop`` step per active REQ — no design,
    build, or land step — carrying the acceptance tests, with deps resolving to develop."""
    req_dir = tmp_path / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="open")
    write_req(req_dir, "REQ-002", status="open", depends_on=["REQ-001"])
    steps = ReqStepSource(req_dir).steps()

    ids = [s.id for s in steps]
    assert ids == ["REQ-001:develop", "REQ-002:develop"]
    assert not any(p in i for s in steps for i in [s.id] for p in (":design", ":build", ":land"))
    by_id = {s.id: s for s in steps}
    assert by_id["REQ-001:develop"].verify == ("true",)  # acceptance test carried
    assert by_id["REQ-002:develop"].depends_on == ("REQ-001:develop",)


# -- AC2 ----------------------------------------------------------------------


def test_mechanical_land_zero_claude(tmp_path):
    """A green develop gate lands mechanically: REQ flips done, ledger advances, the branch
    merges — all with a single claude invocation (the develop session); the land spends none."""
    _project_with_req(tmp_path)
    Ledger.init(tmp_path)
    runner = FakeRunner(default=ok_result())
    git = FakeGitTopology(current="dev")
    ex = _executor(tmp_path, runner=runner, git=git)

    res = ex.advance_once()
    assert res.outcome is RunOutcome.DONE
    assert len(runner.calls) == 1  # only the develop session — zero claude at land

    events = _events(tmp_path)
    assert sum(1 for e in events if e["event"] == "step_started") == 1
    assert any(e["event"] == "checkpoint" for e in events)
    assert not any(e["event"] == "repair_started" for e in events)
    assert Ledger(tmp_path).status_of("REQ-001:develop") is StepStatus.DONE
    assert len(git.merged) == 1  # --no-ff merge happened mechanically
    from devsteward.profiles.req.reqfile import parse_req
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "done"


# -- AC3 ----------------------------------------------------------------------


def test_land_requires_plan_artifact(tmp_path):
    """The mechanical land refuses (parks, surfaces) when no plan names the REQ; with a plan
    present it proceeds."""
    # (a) no plan → refused, REQ stays active, step not DONE
    _project_with_req(tmp_path, plan=False)
    Ledger.init(tmp_path)
    ex = _executor(tmp_path)
    res = ex.advance_once()
    assert res.outcome is RunOutcome.PARKED
    assert "no file in plans/ names REQ-001" in res.detail
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.BLOCKED
    from devsteward.profiles.req.reqfile import parse_req
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "open"

    # (b) a fresh project with the plan present → lands
    other = tmp_path / "with_plan"
    other.mkdir()
    _project_with_req(other)
    Ledger.init(other)
    res2 = _executor(other).advance_once()
    assert res2.outcome is RunOutcome.DONE
    assert Ledger(other).status_of("REQ-001:develop") is StepStatus.DONE


# -- AC4 ----------------------------------------------------------------------


def test_repair_budget_then_park(tmp_path):
    """A red develop gate spawns at most two fresh repair sessions (each carrying the failure
    brief, on the repair model) then parks; a repair that turns it green lands instead."""
    _project_with_req(tmp_path)
    Ledger.init(tmp_path)
    runner = FakeRunner(default=ok_result())
    verifier = _ScriptedVerifier([(False, "FAILED tests/test_x.py::test_y")])  # always red
    ex = _executor(tmp_path, runner=runner, verifier=verifier, repair_budget=2)

    res = ex.advance_once()
    assert res.outcome is RunOutcome.PARKED
    # develop + exactly two repairs
    assert len(runner.calls) == 3
    repair_calls = [c for c in runner.calls if "--repair" in c["command"]]
    assert len(repair_calls) == 2
    for c in repair_calls:
        assert "FAILED tests/test_x.py::test_y" in c["command"]  # the failure brief
        assert c["model"] == "claude-sonnet-4-6"  # repair model
    assert runner.calls[0]["model"] == "claude-opus-4-8"  # develop model
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.BLOCKED
    assert led.open_decisions() and led.open_decisions()[0].step == "REQ-001:develop"
    events = _events(tmp_path)
    assert not any(e["event"] == "checkpoint" for e in events)

    # repair #1 turns the gate green → lands, only one repair spawned
    other = tmp_path / "repairs_ok"
    other.mkdir()
    _project_with_req(other)
    Ledger.init(other)
    runner2 = FakeRunner(default=ok_result())
    v2 = _ScriptedVerifier([(False, "red"), (True, "1 passed")])  # red, then green
    ex2 = _executor(other, runner=runner2, verifier=v2, repair_budget=2)
    res2 = ex2.advance_once()
    assert res2.outcome is RunOutcome.DONE
    assert len([c for c in runner2.calls if "--repair" in c["command"]]) == 1
    assert Ledger(other).status_of("REQ-001:develop") is StepStatus.DONE


# -- AC5 ----------------------------------------------------------------------


def test_per_step_model_config(tmp_path):
    """Model/effort resolve per step kind with documented defaults; a project override
    changes only the named kind; the executor passes the resolved values to each session."""
    # (a) defaults
    cfg = Config(root=tmp_path, claude={})
    assert cfg.step_claude("develop") == ("claude-opus-4-8", "high")
    assert cfg.step_claude("repair")[0] == "claude-sonnet-4-6"

    # (b) override only repair
    cfg2 = Config(root=tmp_path, claude={"steps": {"repair": {"model": "claude-haiku-4-5"}}})
    assert cfg2.step_claude("develop") == ("claude-opus-4-8", "high")
    assert cfg2.step_claude("repair")[0] == "claude-haiku-4-5"

    # (c) end-to-end: the configured repair model reaches the spawned repair session
    _project_with_req(tmp_path)
    Ledger.init(tmp_path)
    runner = FakeRunner(default=ok_result())
    v = _ScriptedVerifier([(False, "red")])
    ex = _executor(
        tmp_path, runner=runner, verifier=v, repair_budget=1,
        step_claude={"develop": ("claude-opus-4-8", "high"),
                     "repair": ("claude-haiku-4-5", "high")},
    )
    ex.advance_once()
    assert runner.calls[0]["model"] == "claude-opus-4-8"
    assert runner.calls[1]["model"] == "claude-haiku-4-5"


# -- AC6 ----------------------------------------------------------------------


def test_split_and_concept_park_in_batch(tmp_path):
    """`steward run` parks a REQ declaring develop: split or concept: true with a decision
    naming the attended need, and spawns no develop session for it; a default REQ still lands."""
    req_dir = tmp_path / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="open", process={"develop": "split"})
    write_req(req_dir, "REQ-002", status="open", process={"concept": True})
    write_req(req_dir, "REQ-003", status="open")
    write_index(req_dir, [(r, f"{r} t", "OPEN", "–") for r in ("REQ-001", "REQ-002", "REQ-003")])
    _write_plan(tmp_path, "REQ-003")
    Ledger.init(tmp_path)
    runner = FakeRunner(default=ok_result())
    ex = _executor(tmp_path, runner=runner)

    results = ex.run()
    outcomes = {r.step.id: r.outcome for r in results}
    assert outcomes["REQ-001:develop"] is RunOutcome.PARKED
    assert outcomes["REQ-002:develop"] is RunOutcome.PARKED
    assert outcomes["REQ-003:develop"] is RunOutcome.DONE

    # no develop session was spawned for the attended REQs
    assert all("REQ-001" not in c["command"] and "REQ-002" not in c["command"]
               for c in runner.calls)
    questions = {d.step: d.question for d in Ledger(tmp_path).open_decisions()}
    assert "split" in questions["REQ-001:develop"]
    assert "concept" in questions["REQ-002:develop"]


# -- AC7 ----------------------------------------------------------------------


def test_old_ledger_reinterpreted_not_rewritten(tmp_path):
    """A done REQ with an old-shape land yields no step; a mid-flight REQ with only old
    design/build rows gets a fresh develop step; events.jsonl is only appended to."""
    req_dir = tmp_path / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="done")          # old-shape land was done
    write_req(req_dir, "REQ-002", status="in-progress")   # caught mid-flight
    write_index(req_dir, [("REQ-001", "one", "DONE", "–"), ("REQ-002", "two", "IN-PROGRESS", "–")])
    _write_plan(tmp_path, "REQ-002")
    led = Ledger.init(tmp_path)
    # seed the pre-REQ-029 ledger shape
    for sid in ("REQ-001:design", "REQ-001:build", "REQ-001:land",
                "REQ-002:design", "REQ-002:build"):
        led.set_status(sid, StepStatus.DONE)
    led.save()
    led.append_event("legacy_marker", note="pre-REQ-029")

    events_before = (tmp_path / ".devsteward" / "events.jsonl").read_text()

    ex = _executor(tmp_path)
    # (a) the done REQ produces no step; (b) the mid-flight REQ gets a fresh develop step
    ids = [s.id for s in ex.steps()]
    assert ids == ["REQ-002:develop"]
    assert ex.ledger.status_of("REQ-002:develop") is StepStatus.PENDING  # fresh, eligible
    assert [s.id for s in ex.eligible_steps()] == ["REQ-002:develop"]

    ex.advance_once()  # drive it, which appends events

    # (c) the log only grew; the old shape survives verbatim (append-only audit contract)
    events_after = (tmp_path / ".devsteward" / "events.jsonl").read_text()
    assert events_after.startswith(events_before)  # never rewritten, only appended
    assert "legacy_marker" in events_after
