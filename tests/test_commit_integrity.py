"""REQ-063 — non-destructive commit integrity: a capture gap never discards the work.

The REQ-050 gate proved a develop commit reproduces its own green, but did it *after*
committing and ``reset --hard``'d the work away on a gap — discarding a green, paid-for
session (FlowSteward REQ-043 postmortem). REQ-063 re-architects the land path: the check runs
against the **staged tree before the commit**, so a gap is handled non-destructively — the
pure code is committed and its SHA surfaced, the step is left repeatable, nothing is reset.
And an **environment skip** (a test that passed verify but only skips from the bare extract,
its DB/secret absent) is no longer a capture gap.

Real-git teeth (the plan-0021 lesson): a throwaway ``git init`` repo on ``dev``, only
``claude`` faked (``FakeRunner``). The develop "work" is written **uncommitted** into the tree
(the fake runner makes no edits), so the engine commits it for real — exactly the live shape.

* **AC1** (``test_capture_gap_preserves_work_and_surfaces_sha``) — a real source-capture gap
  withholds certification but **preserves** the work commit and surfaces its SHA.
* **AC2** (``test_environment_skip_is_not_a_capture_gap``) — the all-skip shape certifies.
* **AC3** (``test_self_sufficient_green_certifies``) — a self-sufficient green lands ``DONE``,
  the flip riding the one code commit (same-commit discipline); no false positive.
* **AC4** (``test_withhold_recovery_is_honest_and_names_sha``) — the withhold message names the
  preserved SHA and frames the cause as a source file, never "commit the secret".
* Two controls: the validate land stays exempt; the develop land of the *self-sufficient* case.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.git import GitCli
from devsteward.core.ledger import Ledger
from devsteward.core.model import Step, StepStatus
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


def _log_shas(root: Path) -> list[str]:
    return _git(root, "log", "--format=%H").split()


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


# A named test that reads a sibling file — green only if that file is present in the cwd.
_DEP_TEST = (
    "from pathlib import Path\n"
    "def test_needs_secret():\n"
    "    assert Path('secret.txt').read_text().strip() == 'load-bearing'\n"
)

# A named test that reads a *tracked* (committed) sibling file — captured by the commit.
_CAPTURED_TEST = (
    "from pathlib import Path\n"
    "def test_reads_committed_data():\n"
    "    assert Path('data.txt').read_text().strip() == 'captured'\n"
)

# An environment-bound test as the real ones are shaped: it skips when a runtime artifact is
# absent. With the artifact present (the session's env) it passes; from a bare extract the
# (gitignored) artifact is never there, so it skips — an environment absence, not a source gap.
_LIVE_LAB_TEST = (
    "from pathlib import Path\n"
    "import pytest\n"
    "def test_over_live_lab_corpus():\n"
    "    if not Path('lab_present.flag').exists():\n"
    "        pytest.skip('live lab absent')\n"
    "    assert True\n"
)


# -- AC1: a capture gap preserves the work and surfaces the SHA ----------------


def test_capture_gap_preserves_work_and_surfaces_sha(tmp_path):
    """AC1: the develop gate passes (the gitignored ``secret.txt`` is in the tree), but the
    recorded commit can't carry it, so the staged-tree check sees the named test go red. The
    land **withholds certification without destroying the work**: the pure code is committed
    (its SHA surfaced and reachable on ``dev``), the REQ stays ``open``, the step is left
    ``FAILED`` (repeatable), and nothing is ``reset --hard``'d."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    (tmp_path / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    _init_git(tmp_path)  # commits the scaffold + .gitignore; the work is added below

    # The develop session's work, left uncommitted in the tree (the engine commits it). The
    # load-bearing file exists so the gate is green, yet is gitignored so the commit drops it.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_dep.py").write_text(_DEP_TEST, encoding="utf-8")
    (tmp_path / "secret.txt").write_text("load-bearing\n", encoding="utf-8")

    before_head = _head(tmp_path)
    ex = _executor(tmp_path)
    res = ex.advance_once()

    # Withheld, not destroyed: a non-stopping VERIFY_FAILED naming a real, reachable work commit.
    assert res.outcome is RunOutcome.VERIFY_FAILED
    assert res.commit and res.commit != before_head
    assert res.commit in _log_shas(tmp_path)  # on the dev history — preserved, not dangling
    assert "test_dep.py" in _git(tmp_path, "show", "--stat", res.commit)
    assert before_head in _log_shas(tmp_path)  # history extended, not rewritten

    # Nothing certified: the REQ is still open, no checkpoint event, a capture_gap event, and
    # the tree is clean at rest (the ledger close was committed).
    assert "status: open" in (tmp_path / "docs" / "requirements" / "REQ-001.md").read_text()
    assert _porcelain(tmp_path) == ""
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.FAILED
    assert not any(e["event"] == "checkpoint" for e in led.events())
    assert any(e["event"] == "capture_gap" for e in led.events())


# -- AC2: an environment skip is not a capture gap ----------------------------


def test_environment_skip_is_not_a_capture_gap(tmp_path):
    """AC2: the named test passes in verify (the gitignored ``lab_present.flag`` is in the
    tree) and only **skips** from the bare extract (the flag, like a DB/secret, is never in the
    commit). That is environment absence, not a source-capture gap, so the develop land
    certifies ``DONE`` — the FlowSteward REQ-043 all-skip shape, no longer discarded."""
    _scaffold(tmp_path, test="python -m pytest tests/test_lab.py")
    (tmp_path / ".gitignore").write_text("lab_present.flag\n", encoding="utf-8")
    _init_git(tmp_path)

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_lab.py").write_text(_LIVE_LAB_TEST, encoding="utf-8")
    (tmp_path / "lab_present.flag").write_text("up\n", encoding="utf-8")  # gitignored env

    ex = _executor(tmp_path)
    res = ex.advance_once()

    assert res.outcome is RunOutcome.DONE
    assert _porcelain(tmp_path) == ""
    assert "status: done" in (tmp_path / "docs" / "requirements" / "REQ-001.md").read_text()
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.DONE
    assert any(e["event"] == "checkpoint" for e in led.events())


# -- AC3: a self-sufficient green certifies (no false positive) ----------------


def test_self_sufficient_green_certifies(tmp_path):
    """AC3: a green depending only on *committed* source (``data.txt`` is tracked) reproduces
    from the extract and lands ``DONE`` — the re-architecture raises no false positive — with
    the ``done`` flip + index sync riding the one code commit (same-commit discipline)."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    _init_git(tmp_path)

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_dep.py").write_text(_CAPTURED_TEST, encoding="utf-8")
    (tmp_path / "data.txt").write_text("captured\n", encoding="utf-8")  # tracked, not ignored

    ex = _executor(tmp_path)
    res = ex.advance_once()

    assert res.outcome is RunOutcome.DONE
    assert _porcelain(tmp_path) == ""
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.DONE
    assert any(e["event"] == "checkpoint" for e in led.events())

    # Same-commit discipline: the one code commit carries the work AND the REQ flip + index.
    shown = _git(tmp_path, "show", "--stat", res.commit)
    assert "data.txt" in shown
    assert "REQ-001.md" in shown
    assert "REQUIREMENTS_INDEX.md" in shown
    assert "status: done" in (tmp_path / "docs" / "requirements" / "REQ-001.md").read_text()


# -- AC4: the withhold message is honest and names the SHA ---------------------


def test_withhold_recovery_is_honest_and_names_sha(tmp_path):
    """AC4: on a real source-capture gap the surfaced detail names the **preserved** work
    commit and frames the cause as an uncaptured *source/test* file — explicitly *never* the
    postmortem's wrong "commit them / fix .gitignore" advice applied to a secret."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    (tmp_path / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    _init_git(tmp_path)

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_dep.py").write_text(_DEP_TEST, encoding="utf-8")
    (tmp_path / "secret.txt").write_text("load-bearing\n", encoding="utf-8")

    ex = _executor(tmp_path)
    res = ex.advance_once()

    assert res.outcome is RunOutcome.VERIFY_FAILED
    msg = res.detail
    assert "does not reproduce its green" in msg
    assert res.commit and res.commit in msg          # names the preserved SHA
    assert "source/test file" in msg                 # frames it as a source file...
    assert "never a secret" in msg                    # ...not "commit the secret"


# -- control: the validate land stays exempt ----------------------------------


def _validate_step(verify: str) -> Step:
    return Step(
        id="REQ-001:validate",
        command="/system-test REQ-001",
        verify=(verify,),
        title="REQ-001 — validate",
        req="REQ-001",
        phase="validate",
    )


def test_validate_land_certifies_despite_live_lab_skip(tmp_path):
    """Control: the commit-integrity check is a develop-land invariant and must not fire on the
    validate land. A validate step's ``verify`` is the ``artifact`` AC test, whose green was
    established against the live lab and skips from a bare extract by design — so the validate
    phase is exempt and certifies ``DONE`` (REQ-050 × REQ-030, preserved by REQ-063)."""
    _scaffold(tmp_path, test="python -m pytest tests/test_lab.py")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_lab.py").write_text(_LIVE_LAB_TEST, encoding="utf-8")
    (tmp_path / ".gitignore").write_text("lab_present.flag\n", encoding="utf-8")
    _init_git(tmp_path)  # commits the test — but never the lab flag (ignored)
    (tmp_path / "lab_present.flag").write_text("up\n", encoding="utf-8")

    ex = _executor(tmp_path)
    res = ex.mechanical_land(_validate_step("python -m pytest tests/test_lab.py"))

    assert res.outcome is RunOutcome.DONE
    assert _porcelain(tmp_path) == ""
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:validate") is StepStatus.DONE
    assert any(e["event"] == "checkpoint" for e in led.events())
