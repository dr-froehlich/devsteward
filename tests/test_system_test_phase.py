"""REQ-030 — the System-Test phase: the conditional validate step, the decoupled System
Tester session, engine-run artifact gates, dated evidence events, manual decision stops,
red-parks-no-repair, lab eligibility, and `steward validate` as the single entry point.

Wired like ``test_phase_model.py``: the REQ profile's real source/verifier/flipper/
land-gate/validate-routine around a fake ``claude`` runner and an in-memory git topology.
Real pytest subprocesses run only where the skip-is-red teeth are the point.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from click.testing import CliRunner

from devsteward.cli import main as cli_main
from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Decision, DecisionStatus, StepStatus
from devsteward.profiles.req import ReqStepSource
from devsteward.profiles.req.checkpoint import PlanArtifactGate, ReqDoneFlipper
from devsteward.profiles.req.reqfile import parse_req
from devsteward.profiles.req.validate import ReqValidateRoutine, Signoff
from devsteward.profiles.req.verify import ReqVerifier

from conftest import FakeGitTopology, FakeRunner, ok_result, write_index


def _write_req(req_dir: Path, rid: str, acs, *, status="open", depends_on=(), process=None):
    """A REQ with an explicit list of ACs (id, test, check) — the conftest helper carries
    only one criterion, and this phase is all about mixing checks."""
    req_dir.mkdir(parents=True, exist_ok=True)
    deps = "[" + ", ".join(depends_on) + "]"
    acc_items = []
    for ac in acs:
        acc_items.append(
            f"- id: {ac['id']}\n"
            f"  text: {ac.get('text', ac['id'] + ' holds.')}\n"
            f"  test: \"{ac['test']}\"\n"
            f"  check: {ac['check']}\n"
            f"  status: pending\n"
        )
    proc = ""
    if process is not None:
        lines = ["process:"]
        for key, value in process.items():
            if isinstance(value, list):
                lines.append(f"  {key}: [{', '.join(value)}]")
            else:
                lines.append(f"  {key}: {value}")
        proc = "\n".join(lines) + "\n"
    text = (
        f"---\n"
        f"id: {rid}\n"
        f'title: "{rid} title"\n'
        f"status: {status}\n"
        f"kind: feature\n"
        f"added: 2026-06-10\n"
        f"completed: null\n"
        f"verified_by: null\n"
        f"depends_on: {deps}\n"
        f"concept_refs: []\n"
        f"scenario_refs: []\n"
        f"supersedes: null\n"
        f"tags: []\n"
        f"{proc}"
        f"---\n\n"
        f"## Context\n\n{rid} context.\n\n"
        f"## Requirement\n\nDo the thing.\n\n"
        "```yaml acceptance\n" + "".join(acc_items) + "```\n\n"
        f"## Notes\n\nNone.\n"
    )
    (req_dir / f"{rid}.md").write_text(text, encoding="utf-8")


def _write_plan(root: Path, *reqs):
    plans = root / "docs" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "0001-plan.md").write_text(
        "# Plan\n\n" + "\n".join(f"Covers {r}." for r in reqs) + "\n", encoding="utf-8"
    )


class SystemTesterRunner(FakeRunner):
    """A fake ``claude`` that, on a ``/system-test`` command, drops a captured artifact
    into the evidence dir the engine passed — and (deliberately) *claims* success in its
    report text, which must carry zero gate weight (AC2)."""

    def __init__(self, root: Path, artifact: str | None = "capture.txt",
                 content: str = "observed behaviour\n"):
        super().__init__(default=ok_result("session report: all checks look great!"))
        self.root = Path(root)
        self.artifact = artifact
        self.content = content

    def __call__(self, command, **kw):
        result = super().__call__(command, **kw)
        if "/system-test" in command and "--evidence" in command and self.artifact:
            rel = command.split("--evidence", 1)[1].split()[0]
            p = self.root / rel / self.artifact
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(self.content, encoding="utf-8")
        return result


def _executor(root, *, runner=None, git=None, repair_budget=0):
    req_dir = root / "docs" / "requirements"
    return Executor(
        root=root,
        source=ReqStepSource(req_dir),
        verifier=ReqVerifier(cwd=str(root), full_suite=None),
        accounts=SingleAccountProvider(),
        runner=runner or SystemTesterRunner(root),
        git=git or FakeGitTopology(current="dev"),
        on_verified=ReqDoneFlipper(req_dir, req_dir / "REQUIREMENTS_INDEX.md"),
        land_gate=PlanArtifactGate(root / "docs" / "plans"),
        repair_budget=repair_budget,
        step_claude={"develop": ("claude-opus-4-8", "high"),
                     "repair": ("claude-sonnet-4-6", "high"),
                     "validate": ("claude-opus-4-8", "high")},
        validate_runner=ReqValidateRoutine(req_dir),
    )


def _events(root):
    path = root / ".devsteward" / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _validation_events(root):
    return [e for e in _events(root) if e["event"] == "validation"]


def _project(root, acs, *, rid="REQ-001", process=None):
    req_dir = root / "docs" / "requirements"
    _write_req(req_dir, rid, acs, process=process)
    write_index(req_dir, [(rid, f"{rid} title", "OPEN", "–")])
    _write_plan(root, rid)
    Ledger.init(root)


_REGRESSION = {"id": "AC1", "test": "true", "check": "regression"}
_ARTIFACT_OK = {"id": "AC2", "test": "true", "check": "artifact"}
_ARTIFACT_RED = {"id": "AC2", "test": "false", "check": "artifact"}
_MANUAL = {"id": "AC3", "test": "manual: reviewer inspects the run", "check": "manual"}


# -- AC1 ------------------------------------------------------------------------


def test_phase_conditional_on_check(tmp_path):
    """Only regression ACs → no validate step; any artifact/manual AC → exactly one
    validate step between develop and the land, and the land waits for validate green."""
    req_dir = tmp_path / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", [_REGRESSION])
    _write_req(req_dir, "REQ-002", [_REGRESSION, _ARTIFACT_OK])
    _write_req(req_dir, "REQ-003", [_REGRESSION], depends_on=["REQ-002"])
    steps = {s.id: s for s in ReqStepSource(req_dir).steps()}

    assert set(steps) == {
        "REQ-001:develop", "REQ-002:develop", "REQ-002:validate", "REQ-003:develop"
    }
    assert steps["REQ-001:develop"].lands  # no system tests ⇒ no system-test phase
    assert not steps["REQ-002:develop"].lands  # defers to validate (D6)
    assert steps["REQ-002:develop"].verify == ("true",)  # regression only
    assert steps["REQ-002:validate"].verify == ("true",)  # the artifact AC's command
    assert steps["REQ-002:validate"].depends_on == ("REQ-002:develop",)
    # a dependent waits for the dep's *final* step — done means validated
    assert steps["REQ-003:develop"].depends_on == ("REQ-002:validate",)

    # the land does not fire before validate is green
    write_index(req_dir, [("REQ-002", "t", "OPEN", "–")])
    _write_plan(tmp_path, "REQ-002")
    Ledger.init(tmp_path)
    git = FakeGitTopology(current="dev")
    ex = _executor(tmp_path, git=git)
    res = ex.advance_once(only="REQ-002")
    assert res.outcome is RunOutcome.DONE  # develop closed…
    assert parse_req(req_dir / "REQ-002.md").status == "open"  # …but no land yet
    assert git.current == "dev"  # REQ-048: never leaves dev
    assert not any(e["event"] == "checkpoint" for e in _events(tmp_path))
    assert any(e["event"] == "develop_committed" for e in _events(tmp_path))

    res2 = ex.advance_once(only="REQ-002")  # the validate step
    assert res2.step.id == "REQ-002:validate" and res2.outcome is RunOutcome.DONE
    assert parse_req(req_dir / "REQ-002.md").status == "done"
    assert git.current == "dev"  # REQ-048: lands on dev, no merge
    assert any(e["event"] == "checkpoint" for e in _events(tmp_path))


# -- AC2 ------------------------------------------------------------------------


def test_context_independence(tmp_path):
    """The validate session is fresh (its prompt carries only the /system-test command and
    the evidence dir — no develop diff), and the engine itself runs the artifact AC's test
    command: a session report claiming success cannot turn a red gate green."""
    _project(tmp_path, [_REGRESSION, _ARTIFACT_OK])
    runner = SystemTesterRunner(tmp_path)
    ex = _executor(tmp_path, runner=runner)
    ex.advance_once(only="REQ-001")
    res = ex.advance_once(only="REQ-001")
    assert res.outcome is RunOutcome.DONE

    session = [c for c in runner.calls if "/system-test" in c["command"]]
    assert len(session) == 1
    cmd = session[0]["command"]
    assert cmd.startswith("/system-test REQ-001 --evidence ")
    assert "--repeat" not in cmd and "diff" not in cmd  # nothing of develop leaks in
    assert session[0]["model"] == "claude-opus-4-8"  # per-step-kind config (D2)

    # red artifact test + a glowing session report → still red, REQ does not land
    other = tmp_path / "talked_green"
    other.mkdir()
    _project(other, [_REGRESSION, _ARTIFACT_RED])
    ex2 = _executor(other, runner=SystemTesterRunner(other))
    ex2.advance_once(only="REQ-001")
    res2 = ex2.advance_once(only="REQ-001")
    assert res2.outcome is RunOutcome.PARKED
    assert parse_req(other / "docs/requirements/REQ-001.md").status == "open"


# -- AC3 ------------------------------------------------------------------------


def test_evidence_event_and_skip_is_red(tmp_path):
    """A green validation appends a dated evidence event (per-AC results, artifact path +
    sha256 under .devsteward/evidence/REQ-NNN/) and updates verified_by; a lab skip or a
    missing artifact is a hard red, never a pass."""
    _project(tmp_path, [_REGRESSION, _ARTIFACT_OK])
    content = "observed behaviour\n"
    ex = _executor(tmp_path, runner=SystemTesterRunner(tmp_path, content=content))
    ex.advance_once(only="REQ-001")
    assert ex.advance_once(only="REQ-001").outcome is RunOutcome.DONE

    (ev,) = _validation_events(tmp_path)
    assert ev["ok"] is True and ev["req"] == "REQ-001"
    assert any(r["ac"] == "AC2" and r["ok"] for r in ev["results"])
    (artifact,) = ev["artifacts"]
    assert artifact["path"].startswith(".devsteward/evidence/REQ-001/")
    assert artifact["sha256"] == hashlib.sha256(content.encode()).hexdigest()
    assert (tmp_path / artifact["path"]).is_file()
    fm = parse_req(tmp_path / "docs/requirements/REQ-001.md").frontmatter
    assert "validation green" in fm["verified_by"]

    # a skipping artifact test is a hard red (skip ≠ green at the validation gate)
    skipping = tmp_path / "skips"
    (skipping / "tst").mkdir(parents=True)
    (skipping / "tst" / "test_val.py").write_text(
        "import pytest\n\ndef test_lab():\n    pytest.skip('lab not up')\n",
        encoding="utf-8",
    )
    _project(skipping, [
        _REGRESSION,
        {"id": "AC2", "test": "python -m pytest tst/test_val.py::test_lab",
         "check": "artifact"},
    ])
    ex2 = _executor(skipping, runner=SystemTesterRunner(skipping))
    ex2.advance_once(only="REQ-001")
    res = ex2.advance_once(only="REQ-001")
    assert res.outcome is RunOutcome.PARKED
    (ev2,) = _validation_events(skipping)
    assert ev2["ok"] is False
    assert "skip" in res.detail.lower()

    # an artifact AC whose session captured nothing is the missing-artifact hard red
    empty = tmp_path / "no_artifact"
    empty.mkdir()
    _project(empty, [_REGRESSION, _ARTIFACT_OK])
    ex3 = _executor(empty, runner=SystemTesterRunner(empty, artifact=None))
    ex3.advance_once(only="REQ-001")
    res3 = ex3.advance_once(only="REQ-001")
    assert res3.outcome is RunOutcome.PARKED
    assert "missing artifact" in res3.detail


# -- AC4 ------------------------------------------------------------------------


def test_validate_single_entry_point(tmp_path):
    """The one routine executes the pending validate step in-flight (green → the land
    proceeds) and, on a done REQ, appends a fresh evidence event without touching status."""
    _project(tmp_path, [_REGRESSION, _ARTIFACT_OK])
    git = FakeGitTopology(current="dev")
    ex = _executor(tmp_path, git=git)
    ex.advance_once(only="REQ-001")  # develop (deferred land)

    routine = ex.validate_runner
    step = ex.step_by_id("REQ-001:validate")
    res = routine(ex, step, unattended=False, driver="interactive")
    assert res.outcome is RunOutcome.DONE
    req_path = tmp_path / "docs/requirements/REQ-001.md"
    assert parse_req(req_path).status == "done"  # the land proceeded
    assert git.current == "dev"  # REQ-048: lands on dev, no merge
    checkpoints = [e for e in _events(tmp_path) if e["event"] == "checkpoint"]
    assert checkpoints and checkpoints[-1]["driver"] == "interactive"

    # done REQ → fresh evidence appended, status (and topology) untouched
    res2 = routine.revalidate(ex, "REQ-001")
    assert res2.outcome is RunOutcome.DONE
    events = _validation_events(tmp_path)
    assert len(events) == 2
    assert events[0]["rerun"] is False and events[1]["rerun"] is True
    assert parse_req(req_path).status == "done"
    # REQ-048: a done re-validation lands nothing — the checkpoint count is unchanged.
    assert len([e for e in _events(tmp_path) if e["event"] == "checkpoint"]) == 1
    assert ex.ledger.status_of("REQ-001:validate") is StepStatus.DONE  # undisturbed


# -- AC5 ------------------------------------------------------------------------


def test_manual_decision_stop(tmp_path):
    """A manual AC parks as a decision stop when unattended; attended, the human verdict is
    recorded as the evidence event with date, reviewer, and scope."""
    _project(tmp_path, [_REGRESSION, _MANUAL])
    ex = _executor(tmp_path)
    ex.advance_once(only="REQ-001")
    res = ex.advance_once(only="REQ-001")  # unattended validate → decision stop
    assert res.outcome is RunOutcome.PARKED
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:validate") is StepStatus.BLOCKED
    # REQ-074: the pending oracle is a hold naming its verb, not a decision.
    assert led.open_decisions() == []
    hold = led.hold_note("REQ-001:validate")
    assert "AC3" in hold and "human" in hold
    assert not _validation_events(tmp_path)  # a pending oracle records no verdict

    # attended: the sign-off lands the REQ and the event carries the provenance
    other = tmp_path / "attended"
    other.mkdir()
    _project(other, [_REGRESSION, _MANUAL])
    ex2 = _executor(other)
    ex2.advance_once(only="REQ-001")
    ex2.advance_once(only="REQ-001")  # unattended pass parks the manual stop first
    assert ex2.ledger.hold_note("REQ-001:validate")  # held, not a decision (REQ-074)
    step = ex2.step_by_id("REQ-001:validate")
    res2 = ex2.validate_runner(
        ex2, step, unattended=False, driver="interactive",
        signoff=lambda ac: Signoff(approved=True, reviewer="Petra",
                                   scope="reviewed the proof run"),
    )
    assert res2.outcome is RunOutcome.DONE
    (ev,) = _validation_events(other)
    (so,) = ev["signoffs"]
    assert so == {"ac": "AC3", "approved": True, "reviewer": "Petra",
                  "scope": "reviewed the proof run", "date": so["date"]}
    assert so["date"]  # engine-composed, dated
    req = parse_req(other / "docs/requirements/REQ-001.md")
    assert req.status == "done"
    assert "signed off by Petra" in req.frontmatter["verified_by"]
    assert ex2.ledger.hold_note("REQ-001:validate") == ""  # the hold cleared with the land

    # a declined verdict is a red validation, not a pass
    declined = tmp_path / "declined"
    declined.mkdir()
    _project(declined, [_REGRESSION, _MANUAL])
    ex3 = _executor(declined)
    ex3.advance_once(only="REQ-001")
    res3 = ex3.validate_runner(
        ex3, ex3.step_by_id("REQ-001:validate"), unattended=False,
        signoff=lambda ac: Signoff(approved=False, reviewer="Petra"),
    )
    assert res3.outcome is RunOutcome.PARKED
    assert parse_req(declined / "docs/requirements/REQ-001.md").status == "open"


# -- AC6 ------------------------------------------------------------------------


def test_red_validation_parks_no_repair(tmp_path):
    """A red validation records the red evidence event and parks with the failure brief;
    no repair session is spawned even when the executor carries a repair budget."""
    _project(tmp_path, [_REGRESSION, _ARTIFACT_RED])
    runner = SystemTesterRunner(tmp_path)
    ex = _executor(tmp_path, runner=runner, repair_budget=2)
    ex.advance_once(only="REQ-001")
    res = ex.advance_once(only="REQ-001")

    assert res.outcome is RunOutcome.PARKED
    (ev,) = _validation_events(tmp_path)
    assert ev["ok"] is False
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:validate") is StepStatus.BLOCKED
    # REQ-074: the red park is a hold, not a decision.
    assert led.open_decisions() == []
    assert "validation red" in led.hold_note("REQ-001:validate")
    # exactly one develop session + one system-test session — zero repairs (D8)
    assert len(runner.calls) == 2
    assert not any("--repair" in c["command"] for c in runner.calls)
    assert not any(e["event"] == "repair_started" for e in _events(tmp_path))


# -- AC7 ------------------------------------------------------------------------


def test_lab_dependency_blocks_validation(tmp_path, monkeypatch):
    """The validate step is ineligible while a process.lab REQ is not done — surfaced by
    name in steward status, no red event, no parked decision — and becomes eligible once
    the lab REQ is done."""
    req_dir = tmp_path / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", [_REGRESSION, _ARTIFACT_OK],
               process={"lab": ["REQ-031"]})
    _write_req(req_dir, "REQ-031", [_REGRESSION])
    write_index(req_dir, [("REQ-001", "t", "OPEN", "–"), ("REQ-031", "lab", "OPEN", "–")])
    _write_plan(tmp_path, "REQ-001", "REQ-031")
    Ledger.init(tmp_path)
    ex = _executor(tmp_path)

    step = ex.step_by_id("REQ-001:validate")
    assert step.depends_on == ("REQ-001:develop", "REQ-031:develop")
    assert step.blocked_note == "validation waiting on REQ-031"

    res = ex.advance_once(only="REQ-001")  # develop runs; validate stays ineligible
    assert res.outcome is RunOutcome.DONE
    assert "REQ-001:validate" not in [s.id for s in ex.eligible_steps()]
    assert Ledger(tmp_path).open_decisions() == []  # honest deferral, no park
    assert not _validation_events(tmp_path)  # and no red event

    monkeypatch.chdir(tmp_path)
    out = CliRunner().invoke(cli_main, ["status"]).output
    assert "validation waiting on REQ-031" in out

    # the direct entry point defers too, naming the lab
    res_direct = ex.validate_runner(ex, step, unattended=False)
    assert res_direct.outcome is RunOutcome.REFUSED
    assert "REQ-031" in res_direct.detail

    # lab done → the validate step becomes eligible
    _write_req(req_dir, "REQ-031", [_REGRESSION], status="done")
    fresh = ex.step_by_id("REQ-001:validate")
    assert fresh.depends_on == ("REQ-001:develop",)
    assert fresh.blocked_note == ""
    assert "REQ-001:validate" in [s.id for s in ex.eligible_steps()]


# -- REQ-057 AC1: state F's circular-answer trap is closed -----------------------


def test_pending_validation_decision_answer_redirects(tmp_path, monkeypatch):
    """REQ-057 AC1: `steward decision answer` on a pending-validation (manual-AC) hold refuses
    and redirects to `steward validate REQ`, leaving the validate step BLOCKED — it does NOT
    flip to PENDING / re-park (the circular trap REQ-056 removed for D/H). A genuine develop
    fork is unaffected: it still answers and unblocks."""
    # A real git+config scaffold so the CLI's build_executor / transaction path works.
    from test_transaction_boundary import _init_git, _scaffold

    _scaffold(tmp_path, acs=(("AC1", "true", "manual"),))
    _init_git(tmp_path)
    monkeypatch.chdir(tmp_path)

    # A state-F hold: a manual-AC validation parked on the validate step (as _park_manual does).
    led = Ledger(tmp_path)
    led.park_decision(Decision(
        id=led.next_decision_id(), step="REQ-001:validate", req="REQ-001",
        question="REQ-001 validation: manual AC AC1 awaits its human oracle.",
    ))
    assert Ledger(tmp_path).status_of("REQ-001:validate") is StepStatus.BLOCKED

    refused = CliRunner().invoke(cli_main, ["decision", "answer", "DEC-001", "looks good"])
    assert refused.exit_code != 0
    assert "steward validate REQ-001" in refused.output
    # Refused before any mutation: still BLOCKED, decision still OPEN (not re-armed / re-parked).
    reloaded = Ledger(tmp_path)
    assert reloaded.status_of("REQ-001:validate") is StepStatus.BLOCKED
    (still_open,) = reloaded.open_decisions()
    assert still_open.id == "DEC-001" and still_open.status is DecisionStatus.OPEN

    # A genuine develop-phase fork is unaffected — answered, its step unblocked to PENDING.
    led2 = Ledger(tmp_path)
    led2.park_decision(Decision(
        id=led2.next_decision_id(), step="REQ-001:develop", req="REQ-001",
        question="Which CSV quoting?",
    ))
    answered = CliRunner().invoke(cli_main, ["decision", "answer", "DEC-002", "RFC 4180"])
    assert answered.exit_code == 0, answered.output
    final = Ledger(tmp_path)
    assert final.status_of("REQ-001:develop") is StepStatus.PENDING
    assert final.find_decision("DEC-002").status is DecisionStatus.ANSWERED
