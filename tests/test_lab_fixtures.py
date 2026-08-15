"""REQ-051 — lab fixtures upstream; the System Tester never improvises.

Stage D of REQ-047 (plan ``docs/plans/0026-single-source-of-truth-trunk-based.md``), built on
the trunk-based foundation (REQ-048). The oracle is *git cleanliness* — a fake can't certify a
fixture's tracked/untracked status — so these are real-git teeth (a throwaway ``git init`` repo
on ``dev``, only ``claude`` faked), in the family of ``tests/test_commit_integrity.py`` /
``tests/test_transaction_boundary.py``.

* **AC5** (``test_missing_fixture_hard_red_no_uncommitted``) — a validation whose declared lab
  fixture is missing (and which a System Tester improvises as an *untracked* file, the exact
  REQ-047 dirty-tree trigger) stops as a hard red with the gap captured in the evidence event;
  the improvised file is discarded, the REQ does not flip ``done``, and the tree carries **no
  uncommitted fixture**.
* A control (``test_committed_fixture_clears_the_gate``) — a fixture committed upstream raises
  no false positive: the validation goes green and the REQ lands ``done``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.git import GitCli
from devsteward.core.ledger import Ledger
from devsteward.profiles.req import ReqStepSource
from devsteward.profiles.req.checkpoint import PlanArtifactGate, ReqDoneFlipper
from devsteward.profiles.req.reqfile import parse_req
from devsteward.profiles.req.validate import ReqValidateRoutine
from devsteward.profiles.req.verify import ReqVerifier

from conftest import FakeRunner, ok_result

_FIXTURE_REL = "labs/widget/golden.txt"


# -- scaffold ------------------------------------------------------------------


def _write_req(req_dir: Path, rid: str, fixtures: list[str]):
    """A REQ with a regression AC (develop's gate) + an artifact AC (the validate step) and a
    ``process.fixtures`` declaration — the committed inputs the validation rests on."""
    req_dir.mkdir(parents=True, exist_ok=True)
    fx = ", ".join(fixtures)
    (req_dir / f"{rid}.md").write_text(
        f"---\n"
        f"id: {rid}\n"
        f'title: "{rid} title"\n'
        f"status: open\n"
        f"kind: feature\n"
        f"added: 2026-06-19\n"
        f"completed: null\n"
        f"verified_by: null\n"
        f"depends_on: []\n"
        f"concept_refs: []\n"
        f"scenario_refs: []\n"
        f"supersedes: null\n"
        f"tags: []\n"
        f"process:\n"
        f"  fixtures: [{fx}]\n"
        f"---\n\n"
        f"## Context\n\n{rid} context.\n\n"
        f"## Requirement\n\nDo the thing.\n\n"
        "```yaml acceptance\n"
        "- id: AC1\n"
        "  text: develop gate holds.\n"
        '  test: "true"\n'
        "  check: regression\n"
        "  status: pending\n"
        "- id: AC2\n"
        "  text: the behaviour is observed against the lab.\n"
        '  test: "true"\n'
        "  check: artifact\n"
        "  status: pending\n"
        "```\n\n"
        f"## Notes\n\nNone.\n",
        encoding="utf-8",
    )


def _index(req_dir: Path):
    (req_dir / "REQUIREMENTS_INDEX.md").write_text(
        "# Requirements Index\n\n"
        "| ID | Title | Status | File | Depends on |\n"
        "|----|-------|--------|------|------------|\n"
        "| REQ-001 | REQ-001 title | OPEN | [REQ-001](REQ-001.md) | – |\n",
        encoding="utf-8",
    )


def _scaffold(root: Path, *, fixtures: list[str]):
    req_dir = root / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", fixtures)
    _index(req_dir)
    plans = root / "docs" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "0001-plan.md").write_text("# Plan 0001\n\nCovers REQ-001.\n", encoding="utf-8")
    (root / ".devsteward").mkdir(parents=True, exist_ok=True)
    (root / ".devsteward" / "config.yaml").write_text(
        "accounts:\n  provider: single\n", encoding="utf-8"
    )
    Ledger.init(root, profile="req")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _init_git(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "fixtures@devsteward.test")
    _git(root, "config", "user.name", "DevSteward Fixtures Test")
    _git(root, "checkout", "-q", "-b", "dev")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "scaffold")


def _porcelain(root: Path) -> str:
    return _git(root, "status", "--porcelain").strip()


class FakeSystemTester(FakeRunner):
    """A fake System Tester. On ``/system-test`` it captures an evidence artifact into the
    engine-passed ``--evidence`` dir; with ``improvise`` set it *also* writes the declared lab
    fixture as an **untracked** file — the dirty-tree move REQ-051 exists to refuse."""

    def __init__(self, root: Path, *, improvise: str | None = None):
        super().__init__(default=ok_result("session report: all checks look great!"))
        self.root = Path(root)
        self.improvise = improvise

    def __call__(self, command, **kw):
        result = super().__call__(command, **kw)
        if "/system-test" in command and "--evidence" in command:
            rel = command.split("--evidence", 1)[1].split()[0]
            art = self.root / rel / "capture.txt"
            art.parent.mkdir(parents=True, exist_ok=True)
            art.write_text("observed behaviour\n", encoding="utf-8")
            if self.improvise:
                fx = self.root / self.improvise
                fx.parent.mkdir(parents=True, exist_ok=True)
                fx.write_text("improvised — never committed\n", encoding="utf-8")
        return result


def _executor(root: Path, runner: FakeRunner) -> Executor:
    req_dir = root / "docs" / "requirements"
    return Executor(
        # REQ-091: a spawn names its model; an unconfigured headless spawn refuses.
        model="test-spawn-model",
        root=root,
        source=ReqStepSource(req_dir),
        verifier=ReqVerifier(cwd=str(root), full_suite=None),
        accounts=SingleAccountProvider(),
        runner=runner,
        on_verified=ReqDoneFlipper(req_dir, req_dir / "REQUIREMENTS_INDEX.md"),
        land_gate=PlanArtifactGate(root / "docs" / "plans"),
        production_branch="main",
        integration_branch="dev",
        git=GitCli(root),
        validate_runner=ReqValidateRoutine(req_dir),
    )


def _validation_events(root: Path) -> list[dict]:
    path = root / ".devsteward" / "events.jsonl"
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip() and json.loads(line)["event"] == "validation"
    ]


# -- AC5 -----------------------------------------------------------------------


def test_missing_fixture_hard_red_no_uncommitted(tmp_path):
    """AC5: the declared lab fixture ``labs/widget/golden.txt`` is never committed. The System
    Tester improvises one as an untracked file; the engine's fixture gate sees the untracked
    file under the declared path, refuses with a hard red, captures the gap in the dated
    evidence event, discards the improvised file, and parks — REQ-001 never flips ``done`` and
    the tree carries no uncommitted fixture."""
    _scaffold(tmp_path, fixtures=[_FIXTURE_REL])
    _init_git(tmp_path)  # commits the scaffold — but never the fixture (it doesn't exist yet)

    ex = _executor(tmp_path, FakeSystemTester(tmp_path, improvise=_FIXTURE_REL))

    assert ex.advance_once(only="REQ-001").outcome is RunOutcome.DONE  # develop closes
    res = ex.advance_once(only="REQ-001")  # the validate step
    assert res.outcome is RunOutcome.PARKED  # a hard red parks, no repair loop

    # The REQ is not certified: it stays open (no done flip).
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "open"

    # The gap is captured in the dated evidence event, naming the fixture and the cause.
    (ev,) = _validation_events(tmp_path)
    assert ev["ok"] is False
    gaps = [r for r in ev["results"] if not r["ok"]]
    assert any(
        _FIXTURE_REL in r["detail"] and "improvised" in r["detail"] for r in gaps
    ), ev["results"]

    # No uncommitted fixture is left in the tree: the improvised file was discarded and the
    # tree is clean (only the ledger close was committed).
    assert not (tmp_path / _FIXTURE_REL).exists()
    assert _porcelain(tmp_path) == ""


def test_missing_fixture_obedient_tester_is_red(tmp_path):
    """The other half of the contract: even when the Tester obeys the skill and creates
    nothing, a *missing* declared fixture (no committed file under the path) is still a hard
    red naming the gap — the validation cannot certify a green that rests on an absent
    fixture."""
    _scaffold(tmp_path, fixtures=[_FIXTURE_REL])
    _init_git(tmp_path)  # the fixture is never committed and the Tester does not improvise

    ex = _executor(tmp_path, FakeSystemTester(tmp_path))  # improvise=None

    assert ex.advance_once(only="REQ-001").outcome is RunOutcome.DONE
    res = ex.advance_once(only="REQ-001")
    assert res.outcome is RunOutcome.PARKED
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "open"

    (ev,) = _validation_events(tmp_path)
    assert ev["ok"] is False
    gaps = [r for r in ev["results"] if not r["ok"]]
    assert any(_FIXTURE_REL in r["detail"] and "missing" in r["detail"] for r in gaps)
    assert _porcelain(tmp_path) == ""


# -- control: a committed fixture raises no false positive ---------------------


def test_committed_fixture_clears_the_gate(tmp_path):
    """No false positive: a fixture committed upstream is tracked, the fixture gate passes, the
    artifact AC is green, and REQ-001 lands ``done`` — the check only bites missing/improvised
    fixtures, never a fixture the commit captures."""
    _scaffold(tmp_path, fixtures=[_FIXTURE_REL])
    fx = tmp_path / _FIXTURE_REL
    fx.parent.mkdir(parents=True, exist_ok=True)
    fx.write_text("the committed golden fixture\n", encoding="utf-8")
    _init_git(tmp_path)  # commits the fixture along with the scaffold

    ex = _executor(tmp_path, FakeSystemTester(tmp_path))

    assert ex.advance_once(only="REQ-001").outcome is RunOutcome.DONE  # develop
    res = ex.advance_once(only="REQ-001")  # validate
    assert res.outcome is RunOutcome.DONE
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "done"

    (ev,) = _validation_events(tmp_path)
    assert ev["ok"] is True
    assert _porcelain(tmp_path) == ""
