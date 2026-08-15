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
        # REQ-091: a spawn names its model; an unconfigured headless spawn refuses.
        model="test-spawn-model",
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
    """A green develop gate lands mechanically: REQ flips done, ledger advances, the commits
    land on dev — all with a single claude invocation (the develop session); the land spends
    none (REQ-048: trunk-based — no branch merge)."""
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
    # REQ-048: trunk-based — the land never leaves dev; code + ledger both commit there.
    assert git.current == "dev"
    assert git.commits and all(branch == "dev" for branch, _ in git.commits)
    from devsteward.profiles.req.reqfile import parse_req
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "done"


# -- AC3 ----------------------------------------------------------------------


def test_land_refused_fails_not_parks(tmp_path):
    """REQ-056 AC2 — a land-gate refusal (no plan names the REQ) *fails* to a repeatable step
    instead of parking a decision: the develop step is set FAILED (not BLOCKED), no decision is
    parked, the land_refused event is still recorded, the ledger close is still committed (clean
    tree at rest), and the run continues to other REQs. With a plan present it lands."""
    # (a) no plan → FAILED, no decision parked, REQ stays active, step not DONE
    _project_with_req(tmp_path, plan=False)
    Ledger.init(tmp_path)
    ex = _executor(tmp_path)
    res = ex.advance_once()
    assert res.outcome is RunOutcome.VERIFY_FAILED  # non-stopping; not PARKED
    assert "no file in plans/ names REQ-001" in res.detail
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.FAILED  # not BLOCKED
    assert led.open_decisions() == []  # no decision parked
    events = _events(tmp_path)
    assert any(e["event"] == "land_refused" for e in events)
    assert not any(e["event"] == "decision_parked" for e in events)
    assert not any(e["event"] == "checkpoint" for e in events)  # nothing landed
    from devsteward.profiles.req.reqfile import parse_req
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "open"

    # the ledger close is committed → the tree is clean at rest (REQ-032)
    git = ex.git
    assert git.commits and git.commits[-1][0] == "dev"

    # a run does not hard-stop on a land refusal: a second independent REQ still lands
    multi = tmp_path / "multi"
    multi.mkdir()
    req_dir = multi / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="open")        # no plan → will fail H
    write_req(req_dir, "REQ-002", status="open")        # planned → lands
    write_index(req_dir, [("REQ-001", "one", "OPEN", "–"), ("REQ-002", "two", "OPEN", "–")])
    _write_plan(multi, "REQ-002")
    Ledger.init(multi)
    results = {r.step.id: r.outcome for r in _executor(multi).run()}
    assert results["REQ-001:develop"] is RunOutcome.VERIFY_FAILED
    assert results["REQ-002:develop"] is RunOutcome.DONE  # run continued past the refusal

    # (b) a fresh project with the plan present → lands
    other = tmp_path / "with_plan"
    other.mkdir()
    _project_with_req(other)
    Ledger.init(other)
    res2 = _executor(other).advance_once()
    assert res2.outcome is RunOutcome.DONE
    assert Ledger(other).status_of("REQ-001:develop") is StepStatus.DONE


# -- AC4 ----------------------------------------------------------------------


def test_repair_exhausted_fails_not_parks(tmp_path):
    """REQ-056 AC1 — a red develop gate spawns at most two fresh repair sessions (each carrying
    the failure brief, on the repair model) then *fails to a repeatable step* instead of parking
    a decision: the develop step is set FAILED (not BLOCKED), no decision is parked, the
    repair_exhausted event is still recorded, and the unattended run continues to other
    independent steps (no hard stop) — converging on the no-budget red-gate path (state A). A
    repair that turns the gate green lands instead."""
    _project_with_req(tmp_path)
    Ledger.init(tmp_path)
    runner = FakeRunner(default=ok_result())
    verifier = _ScriptedVerifier([(False, "FAILED tests/test_x.py::test_y")])  # always red
    ex = _executor(tmp_path, runner=runner, verifier=verifier, repair_budget=2)

    res = ex.advance_once()
    assert res.outcome is RunOutcome.VERIFY_FAILED  # converges on state A; not PARKED
    assert "FAILED tests/test_x.py::test_y" in res.detail  # the latest red brief
    # develop + exactly two repairs
    assert len(runner.calls) == 3
    repair_calls = [c for c in runner.calls if "--repair" in c["command"]]
    assert len(repair_calls) == 2
    for c in repair_calls:
        assert "FAILED tests/test_x.py::test_y" in c["command"]  # the failure brief
        assert c["model"] == "claude-sonnet-4-6"  # repair model
    assert runner.calls[0]["model"] == "claude-opus-4-8"  # develop model
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.FAILED  # not BLOCKED
    assert led.open_decisions() == []  # no decision parked
    events = _events(tmp_path)
    assert any(e["event"] == "repair_exhausted" for e in events)  # event still recorded
    assert not any(e["event"] == "decision_parked" for e in events)
    assert not any(e["event"] == "checkpoint" for e in events)

    # the run does not hard-stop on an exhausted repair: a second independent REQ still lands.
    # The scripted verifier is keyed by call count — REQ-001's develop+2 repairs are 3 reds,
    # then REQ-002's develop verify is green.
    multi = tmp_path / "multi"
    multi.mkdir()
    req_dir = multi / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="open")
    write_req(req_dir, "REQ-002", status="open")
    write_index(req_dir, [("REQ-001", "one", "OPEN", "–"), ("REQ-002", "two", "OPEN", "–")])
    _write_plan(multi, "REQ-001", "REQ-002")
    Ledger.init(multi)
    v_multi = _ScriptedVerifier([(False, "red"), (False, "red"), (False, "red"), (True, "ok")])
    results = {r.step.id: r.outcome
               for r in _executor(multi, verifier=v_multi, repair_budget=2).run()}
    assert results["REQ-001:develop"] is RunOutcome.VERIFY_FAILED
    assert results["REQ-002:develop"] is RunOutcome.DONE  # run continued past the failure

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


def test_repeat_recovers_dirty_fail_with_signal(tmp_path):
    """REQ-056 AC3 — `steward repeat` recovers a D-/H-failed step carrying the resume signal:
    it flips the FAILED develop step to RECOVER, and the next driven run issues the develop
    command with --repeat (step_started recover: true), so the resuming session assesses the
    dirty tree rather than restarting clean."""
    from devsteward.lifecycle import repeat

    # Drive state H: a land-gate refusal leaves REQ-001:develop FAILED with no plan.
    _project_with_req(tmp_path, plan=False)
    Ledger.init(tmp_path)
    ex = _executor(tmp_path)
    assert ex.advance_once().outcome is RunOutcome.VERIFY_FAILED
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.FAILED

    # `steward repeat REQ-001` re-arms the failed step to RECOVER.
    res = repeat(led, "REQ-001")
    assert res.steps == ["REQ-001:develop"]
    reloaded = Ledger(tmp_path)
    assert reloaded.status_of("REQ-001:develop") is StepStatus.RECOVER

    # The next driven run issues the develop command with the --repeat resume signal.
    _write_plan(tmp_path, "REQ-001")  # the human supplies the missing plan
    runner = FakeRunner(default=ok_result())
    ex2 = _executor(tmp_path, runner=runner)
    res2 = ex2.advance_once(only="REQ-001")
    assert res2.outcome is RunOutcome.DONE
    assert "--repeat" in runner.calls[-1]["command"]
    events = _events(tmp_path)
    started = [e for e in events if e["event"] == "step_started"
               and e["step"] == "REQ-001:develop"]
    assert started[-1]["recover"] is True  # the resume signal rode the step_started event


# -- AC5 ----------------------------------------------------------------------


def test_per_step_model_config(tmp_path):
    """Model/effort resolve per step kind with documented defaults; a project override
    changes only the named kind; the executor passes the resolved values to each session."""
    # (a) unconfigured — REQ-090: no built-in model tier, so the model is simply absent and
    # the engine omits --model. (This used to resolve to a model hardcoded in config.py.)
    cfg = Config(root=tmp_path, claude={})
    assert cfg.step_claude("develop") == (None, "high")
    assert cfg.step_claude("repair")[0] is None

    # (b) the flat config model reaches every kind; a per-step override changes only its kind
    cfg2 = Config(
        root=tmp_path,
        claude={"model": "test-model-flat", "steps": {"repair": {"model": "test-model-repair"}}},
    )
    assert cfg2.step_claude("develop") == ("test-model-flat", "high")
    assert cfg2.step_claude("validate")[0] == "test-model-flat"
    assert cfg2.step_claude("repair")[0] == "test-model-repair"

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
    # REQ-074: the attended wait is a ledger hold (no decision) naming the attended need.
    led = Ledger(tmp_path)
    assert led.open_decisions() == []
    assert "split" in led.hold_note("REQ-001:develop")
    assert "concept" in led.hold_note("REQ-002:develop")


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


# -- REQ-054 AC3 --------------------------------------------------------------


def test_repeat_resume_flag(tmp_path):
    """REQ-054 AC3 — the resume-signal contract under the renamed verb. A step re-armed for
    a repeat (RECOVER status) is launched with `--repeat` appended to its command (not the
    old `--recover`), and the shipped `advance` skill's functional flag reference — the side
    that branches on the signal — reads `--repeat`."""
    _project_with_req(tmp_path)
    Ledger.init(tmp_path)
    led = Ledger(tmp_path)
    led.set_status("REQ-001:develop", StepStatus.RECOVER)  # re-armed by `steward repeat`
    led.save()
    runner = FakeRunner(default=ok_result())
    ex = _executor(tmp_path, runner=runner)

    ex.advance_once(only="REQ-001")

    cmd = runner.calls[-1]["command"]
    assert "--repeat" in cmd and "--recover" not in cmd

    # The other side of the contract: the shipped skill branches on `--repeat`.
    from importlib.resources import files
    skill = (
        files("devsteward") / "templates" / ".claude" / "skills" / "advance" / "SKILL.md"
    ).read_text(encoding="utf-8")
    flag_line = next(line for line in skill.splitlines() if "in your command" in line)
    assert "--repeat" in flag_line and "--recover" not in flag_line
