"""REQ-018 — `steward checkpoint`: the engine is the verifying bookkeeper for interactive
work. The same REQ-028 gate and mechanical land as batch, the full topology close-out,
driver provenance on the checkpoint event, and the interactive-first handbook.

Like ``test_phase_model.py`` these wire the REQ profile's real source/verifier/flipper/
land-gate around an in-memory git topology, so the interactive close is exercised without
a real session or checkout.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from devsteward import cli
from devsteward.cli import main
from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.profiles.req import ReqStepSource
from devsteward.profiles.req.checkpoint import PlanArtifactGate, ReqDoneFlipper
from devsteward.profiles.req.reqfile import parse_req
from devsteward.profiles.req.verify import ReqVerifier

from conftest import FakeGitTopology, FakeRunner, ok_result, write_index, write_req

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_plan(root, *reqs):
    plans = root / "docs" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "0001-plan.md").write_text(
        "# Plan 0001\n\n" + "\n".join(f"Covers {r}." for r in reqs) + "\n",
        encoding="utf-8",
    )


class _ScriptedVerifier:
    """A verifier returning a fixed sequence of ``(ok, detail)`` results (then the last,
    repeated), so a test can stage a red gate that a later re-run finds green."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def verify(self, step):
        self.calls += 1
        idx = min(self.calls - 1, len(self._results) - 1)
        return self._results[idx]


def _events(root):
    path = root / ".devsteward" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _executor(root, *, runner=None, verifier=None, git=None):
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
    )


def _project_with_req(root, rid="REQ-001", *, status="open", plan=True, depends_on=()):
    req_dir = root / "docs" / "requirements"
    write_req(req_dir, rid, status=status, depends_on=depends_on)
    if plan:
        _write_plan(root, rid)


def _index(root, *rows):
    write_index(root / "docs" / "requirements", list(rows))


# -- AC1 ----------------------------------------------------------------------


def test_green_checkpoint_verifies_and_advances(tmp_path, monkeypatch):
    """`steward checkpoint` (no args — the cursor step) runs the REQ-028 gate; on green it
    flips the REQ done, syncs the index, appends a checkpoint event with the commit sha and
    driver: interactive, and advances the cursor — without invoking claude."""
    _project_with_req(tmp_path)
    _index(tmp_path, ("REQ-001", "REQ-001 title", "OPEN", "–"))
    Ledger.init(tmp_path)
    runner = FakeRunner(default=ok_result())
    ex = _executor(tmp_path, runner=runner)
    ex.ledger.set_cursor("REQ-001:develop")
    ex.ledger.save()

    monkeypatch.setattr(cli, "_load_or_die", lambda: SimpleNamespace())
    monkeypatch.setattr(cli, "build_executor", lambda cfg, **kw: ex)
    result = CliRunner().invoke(main, ["checkpoint"])
    assert result.exit_code == 0, result.output

    assert runner.calls == []  # the land spends no claude
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "done"
    index_text = (tmp_path / "docs/requirements/REQUIREMENTS_INDEX.md").read_text()
    assert "DONE" in index_text and "OPEN" not in index_text
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.DONE
    assert led.cursor_step == "REQ-001:develop"
    cps = [e for e in _events(tmp_path) if e["event"] == "checkpoint"]
    assert len(cps) == 1
    assert cps[0]["commit"] and cps[0]["driver"] == "interactive"


# -- AC2 ----------------------------------------------------------------------


def test_red_gate_no_land_writes(tmp_path):
    """A red gate records the red verify event and marks the step FAILED, but performs zero
    land-side writes — no flip, no index touch, no commit, no cursor move, no checkpoint
    event — and a later re-run after a fix lands without `repeat`."""
    _project_with_req(tmp_path)
    _index(tmp_path, ("REQ-001", "REQ-001 title", "OPEN", "–"))
    Ledger.init(tmp_path)
    git = FakeGitTopology(current="dev")
    verifier = _ScriptedVerifier(
        [(False, "FAILED tests/test_x.py::test_y"), (True, "1 passed")]
    )
    ex = _executor(tmp_path, verifier=verifier, git=git)
    step = ex.step_by_id("REQ-001:develop")

    res = ex.checkpoint(step)
    assert res.outcome is RunOutcome.VERIFY_FAILED
    assert "FAILED tests/test_x.py::test_y" in res.detail

    # the honest trail: the red verify event and the FAILED step status
    reds = [e for e in _events(tmp_path) if e["event"] == "verify"]
    assert reds and reds[0]["ok"] is False
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.FAILED
    # zero land-side writes
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "open"
    assert "OPEN" in (tmp_path / "docs/requirements/REQUIREMENTS_INDEX.md").read_text()
    assert git.commits == []  # REQ-048: a red gate commits nothing
    assert led.cursor_step is None
    assert not any(e["event"] == "checkpoint" for e in _events(tmp_path))

    # the re-run after the fix lands — no `repeat` needed
    res2 = ex.checkpoint(step)
    assert res2.outcome is RunOutcome.DONE
    assert Ledger(tmp_path).status_of("REQ-001:develop") is StepStatus.DONE
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "done"


# -- AC3 ----------------------------------------------------------------------


def test_no_step_redo_after_checkpoint(tmp_path):
    """After a green `steward checkpoint`, the next `steward advance` selects the next
    step, not a redo of the checkpointed one."""
    _project_with_req(tmp_path, "REQ-001")
    _project_with_req(tmp_path, "REQ-002", depends_on=["REQ-001"])
    _write_plan(tmp_path, "REQ-001", "REQ-002")
    _index(
        tmp_path,
        ("REQ-001", "one", "OPEN", "–"),
        ("REQ-002", "two", "OPEN", "REQ-001"),
    )
    Ledger.init(tmp_path)
    ex = _executor(tmp_path)

    res = ex.checkpoint(ex.step_by_id("REQ-001:develop"))
    assert res.outcome is RunOutcome.DONE
    nxt = ex.next_eligible()
    assert nxt is not None and nxt.id == "REQ-002:develop"
    assert "REQ-001:develop" not in [s.id for s in ex.eligible_steps()]


# -- AC4 ----------------------------------------------------------------------


def test_full_close_out_lands_on_dev(tmp_path):
    """A green checkpoint lands the work on dev (REQ-048: trunk-based) — the authoritative
    code commit, then the trailing ledger commit, both on dev; no feature branch, no merge,
    no branch_merged event."""
    _project_with_req(tmp_path)
    _index(tmp_path, ("REQ-001", "REQ-001 title", "OPEN", "–"))
    Ledger.init(tmp_path)
    git = FakeGitTopology(current="dev")
    ex = _executor(tmp_path, git=git)

    res = ex.checkpoint(ex.step_by_id("REQ-001:develop"))
    assert res.outcome is RunOutcome.DONE
    # the code commit, then the trailing-ledger follow-up — both on dev (REQ-032: clean at
    # rest, the cursor advance committed not left dirty).
    assert [b for b, _ in git.commits] == ["dev", "dev"]
    assert "ledger checkpoint" in git.commits[1][1]
    assert git.current == "dev"
    assert not any(e["event"] == "branch_merged" for e in _events(tmp_path))
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "done"


# -- REQ-060: an honest terminal state, no misleading checkpoint refusal ------


def test_checkpoint_done_req_names_done(tmp_path, monkeypatch):
    """REQ-060 AC2 — `steward checkpoint REQ-NNN` on a *done* REQ fails with a message that
    names it as done and points at supersede, not the generic 'is REQ active (not draft/
    done) and is the phase develop?' question."""
    _project_with_req(tmp_path, "REQ-001", status="done")
    _index(tmp_path, ("REQ-001", "REQ-001 title", "DONE", "–"))
    Ledger.init(tmp_path)
    ex = _executor(tmp_path)
    cfg = SimpleNamespace(req_dir=tmp_path / "docs" / "requirements")

    monkeypatch.setattr(cli, "_load_or_die", lambda: cfg)
    monkeypatch.setattr(cli, "build_executor", lambda c, **kw: ex)
    result = CliRunner().invoke(main, ["checkpoint", "REQ-001"])

    assert result.exit_code != 0, result.output
    assert "REQ-001 is done" in result.output
    assert "supersede" in result.output
    # not the interrogating question the user already knows the answer to
    assert "active (not draft/done)" not in result.output


def test_checkpoint_no_arg_stale_cursor_nothing_in_flight(tmp_path, monkeypatch):
    """REQ-060 AC3 — no-arg `steward checkpoint` whose cursor names a done/non-derivable
    step reports 'nothing in flight to checkpoint', not the 'not a derivable step' error."""
    _project_with_req(tmp_path, "REQ-001", status="done")
    _index(tmp_path, ("REQ-001", "REQ-001 title", "DONE", "–"))
    Ledger.init(tmp_path)
    ex = _executor(tmp_path)
    ex.ledger.set_cursor("REQ-001:develop")  # stale: pinned to the now-done final step
    ex.ledger.save()
    cfg = SimpleNamespace(req_dir=tmp_path / "docs" / "requirements")

    monkeypatch.setattr(cli, "_load_or_die", lambda: cfg)
    monkeypatch.setattr(cli, "build_executor", lambda c, **kw: ex)
    result = CliRunner().invoke(main, ["checkpoint"])

    assert result.exit_code != 0, result.output
    assert "nothing in flight to checkpoint" in result.output
    assert "not a derivable step" not in result.output


# -- AC5 ----------------------------------------------------------------------


def test_driver_provenance_both_modes(tmp_path):
    """A batch land writes driver: headless; an interactive checkpoint writes driver:
    interactive — same event shape, same certifying engine."""
    # batch: the executor drives the develop session headless, then lands
    _project_with_req(tmp_path)
    _index(tmp_path, ("REQ-001", "REQ-001 title", "OPEN", "–"))
    Ledger.init(tmp_path)
    ex = _executor(tmp_path)
    assert ex.advance_once().outcome is RunOutcome.DONE
    (batch_cp,) = [e for e in _events(tmp_path) if e["event"] == "checkpoint"]
    assert batch_cp["driver"] == "headless"

    # interactive: the human drove; `steward checkpoint` closes
    other = tmp_path / "interactive"
    other.mkdir()
    _project_with_req(other)
    _index(other, ("REQ-001", "REQ-001 title", "OPEN", "–"))
    Ledger.init(other)
    ex2 = _executor(other)
    assert ex2.checkpoint(ex2.step_by_id("REQ-001:develop")).outcome is RunOutcome.DONE
    (inter_cp,) = [e for e in _events(other) if e["event"] == "checkpoint"]
    assert inter_cp["driver"] == "interactive"

    # same event shape: identical keys, both carrying a commit sha
    assert set(batch_cp) == set(inter_cp)
    assert batch_cp["commit"] and inter_cp["commit"]


# -- AC6 ----------------------------------------------------------------------


def test_handbook_and_skill_interactive_first():
    """The handbook presents interactive driving as the default with `steward run` as the
    batch lane, no 'no engine guarantees' framing remains, and both /advance copies
    (repo + stamped template, identical) close via steward checkpoint."""
    handbook = _REPO_ROOT / "devsteward" / "handbook"
    chapters = sorted(handbook.glob("_*.qmd"))
    assert chapters, f"no handbook chapters under {handbook}"
    for chapter in chapters:
        text = chapter.read_text(encoding="utf-8").lower()
        # covers the plural too, and the inverted "the human is the guarantee" framing
        assert "no engine guarantee" not in text, chapter.name
        assert "human is the guarantee" not in text, chapter.name

    workflow = (handbook / "_03-workflow.qmd").read_text(encoding="utf-8")
    assert "default driving mode" in workflow
    assert "batch lane" in workflow

    repo_skill = _REPO_ROOT / ".claude" / "skills" / "advance" / "SKILL.md"
    template_skill = (
        _REPO_ROOT
        / "devsteward" / "templates" / ".claude" / "skills" / "advance" / "SKILL.md"
    )
    repo_text = repo_skill.read_text(encoding="utf-8")
    assert repo_text == template_skill.read_text(encoding="utf-8")
    assert "steward checkpoint" in repo_text
    assert "no engine guarantee" not in repo_text.lower()

    claude_tmpl = _REPO_ROOT / "devsteward" / "templates" / "CLAUDE.md.tmpl"
    assert "no engine guarantee" not in claude_tmpl.read_text(encoding="utf-8").lower()
