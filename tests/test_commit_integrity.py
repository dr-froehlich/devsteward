"""REQ-050 — commit integrity: a land refuses a green the recorded commit doesn't capture.

Stage C of REQ-047 (plan ``docs/plans/0026-single-source-of-truth-trunk-based.md``), built on
the REQ-049 transaction boundary. Real-git teeth (the plan-0021 lesson, reinforced by the
task brief: a fake can't certify a ``.gitignore``d-file gap). A throwaway ``git init`` repo on
``dev``, only ``claude`` faked (``FakeRunner``); the executor commits for real and the
assertions read real git state.

* **AC4** (``test_land_refuses_uncaptured_green``) — a develop whose pass depends on a
  ``.gitignore``d / never-staged file is refused at land with the gap named; the REQ does
  **not** flip ``done`` and ``dev`` is left clean (no stranded work commit).
* A control (``test_land_certifies_a_self_sufficient_green``) — a green that depends only on
  *committed* source still lands ``DONE`` (the self-check raises no false positive).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.errors import PreconditionError
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.git import GitCli
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.profiles.req import ReqStepSource
from devsteward.profiles.req.checkpoint import PlanArtifactGate, ReqDoneFlipper
from devsteward.profiles.req.verify import ReqVerifier

from conftest import FakeRunner, ok_result


# -- scaffold ------------------------------------------------------------------


def _write_req(req_dir: Path, rid: str, test: str, *, status="open"):
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / f"{rid}.md").write_text(
        f"---\n"
        f"id: {rid}\n"
        f'title: "{rid} title"\n'
        f"status: {status}\n"
        f"kind: feature\n"
        f"added: 2026-06-19\n"
        f"completed: null\n"
        f"verified_by: null\n"
        f"depends_on: []\n"
        f"concept_refs: []\n"
        f"scenario_refs: []\n"
        f"supersedes: null\n"
        f"tags: []\n"
        f"---\n\n"
        f"## Context\n\n{rid} context.\n\n"
        f"## Requirement\n\nDo the thing.\n\n"
        "```yaml acceptance\n"
        f"- id: AC1\n"
        f"  text: AC1 holds.\n"
        f'  test: "{test}"\n'
        f"  check: regression\n"
        f"  status: pending\n"
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


def _scaffold(root: Path, *, test: str):
    req_dir = root / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", test)
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
    _git(root, "config", "user.email", "integrity@devsteward.test")
    _git(root, "config", "user.name", "DevSteward Integrity Test")
    _git(root, "checkout", "-q", "-b", "dev")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "scaffold")


def _head(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").strip()


def _porcelain(root: Path) -> str:
    return _git(root, "status", "--porcelain").strip()


def _executor(root: Path) -> Executor:
    req_dir = root / "docs" / "requirements"
    return Executor(
        root=root,
        source=ReqStepSource(req_dir),
        verifier=ReqVerifier(cwd=str(root), full_suite=None),
        accounts=SingleAccountProvider(),
        runner=FakeRunner(default=ok_result()),
        on_verified=ReqDoneFlipper(req_dir, req_dir / "REQUIREMENTS_INDEX.md"),
        land_gate=PlanArtifactGate(root / "docs" / "plans"),
        production_branch="main",
        integration_branch="dev",
        git=GitCli(root),
    )


# -- AC4 -----------------------------------------------------------------------

# A named test that reads a sibling file — green only if that file is present.
_DEP_TEST = (
    "from pathlib import Path\n"
    "def test_needs_secret():\n"
    "    assert Path('secret.txt').read_text().strip() == 'load-bearing'\n"
)


def test_land_refuses_uncaptured_green(tmp_path):
    """AC4: the develop gate passes because a ``.gitignore``d ``secret.txt`` sits in the
    working tree — but ``commit_code`` (``git add -A`` minus ``.devsteward/``) cannot stage an
    ignored file, so the recorded commit can't reproduce the green. The land re-runs the named
    test against a clean extract of the commit, sees it go red, rolls the work commit back, and
    refuses with the gap named — REQ-001 never flips ``done`` and ``dev`` is left clean."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_dep.py").write_text(_DEP_TEST, encoding="utf-8")
    (tmp_path / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    _init_git(tmp_path)  # commits the test + .gitignore — but never secret.txt (ignored)

    # The load-bearing file exists in the tree (so the develop gate is green) yet is ignored.
    (tmp_path / "secret.txt").write_text("load-bearing\n", encoding="utf-8")

    before_head = _head(tmp_path)
    ex = _executor(tmp_path)

    with pytest.raises(PreconditionError) as exc:
        ex.advance_once()

    # The refusal names the gap and tells the operator how to close it.
    assert "does not reproduce its green" in str(exc.value)
    assert "gitignore" in exc.value.recovery.lower()

    # Nothing certified, nothing advanced: the work commit was rolled back, the REQ is still
    # open, no checkpoint event, and the tree is clean (no stranded half-state).
    assert _head(tmp_path) == before_head
    assert _porcelain(tmp_path) == ""
    assert "status: open" in (tmp_path / "docs" / "requirements" / "REQ-001.md").read_text()
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is not StepStatus.DONE
    assert not any(e["event"] == "checkpoint" for e in led.events())


# -- control: a self-sufficient green still lands ------------------------------

# A named test that reads a *tracked* (committed) sibling file — captured by the commit.
_CAPTURED_TEST = (
    "from pathlib import Path\n"
    "def test_reads_committed_data():\n"
    "    assert Path('data.txt').read_text().strip() == 'captured'\n"
)


def test_land_certifies_a_self_sufficient_green(tmp_path):
    """The self-check raises no false positive: a green that depends only on *committed*
    source (``data.txt`` is tracked, so the commit captures it) re-runs green from the extract
    and the REQ lands ``DONE``."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_dep.py").write_text(_CAPTURED_TEST, encoding="utf-8")
    (tmp_path / "data.txt").write_text("captured\n", encoding="utf-8")  # tracked, not ignored
    _init_git(tmp_path)

    ex = _executor(tmp_path)
    res = ex.advance_once()

    assert res.outcome is RunOutcome.DONE
    assert _porcelain(tmp_path) == ""
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.DONE
    assert any(e["event"] == "checkpoint" for e in led.events())
