"""Branch guards.

REQ-011 — the engine refuses to autocommit on the production branch.
REQ-019 — it also refuses *implementation* steps (``build``/``land``) on the integration
branch, while allowing declaration (a ``design`` plan) there; implementation belongs on a
feature branch.

The branch state is supplied by an injectable :class:`FakeGitTopology` seam (REQ-020), so
the guards drive without a real git checkout — consistent with conftest's goal of exercising
the full loop without committing to git.
"""

from __future__ import annotations

from pathlib import Path

from devsteward.config import load_config
from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Step, StepStatus
from devsteward.core.verify import CommandVerifier

from conftest import (
    FakeGitTopology,
    FakeRunner,
    ListStepSource,
    RecordingCommitter,
    ok_result,
)

_PKG = Path(__file__).resolve().parents[1] / "devsteward"


def _executor(root, steps, *, branch, runner=None, committer=None, git=None):
    return Executor(
        root=root,
        source=ListStepSource(steps),
        verifier=CommandVerifier(cwd=str(root)),
        accounts=SingleAccountProvider(),
        runner=runner or FakeRunner(default=ok_result()),
        committer=committer or RecordingCommitter(),
        production_branch="main",
        integration_branch="dev",
        git=git or FakeGitTopology(current=branch),
    )


def test_config_branch_names(tmp_path: Path):
    """AC1 — defaults are main/dev; a written git section is read back."""
    Ledger.init(tmp_path, profile="req")

    cfg = load_config(tmp_path)
    assert cfg.production_branch == "main"
    assert cfg.integration_branch == "dev"

    (tmp_path / ".devsteward" / "config.yaml").write_text(
        "git:\n  production_branch: master\n  integration_branch: release\n",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.production_branch == "master"
    assert cfg.integration_branch == "release"


def test_refuses_on_production_branch(project):
    """AC2 — on the production branch: no claude, no commit, step stays PENDING."""
    step = Step(id="REQ-011:land", command="/advance REQ-011 land", verify=("true",))
    runner = FakeRunner(default=ok_result())
    committer = RecordingCommitter()
    ex = _executor(project, [step], branch="main", runner=runner, committer=committer)

    res = ex.advance_once()
    assert res.outcome is RunOutcome.REFUSED
    assert runner.calls == []
    assert committer.committed == []
    assert Ledger(project).status_of("REQ-011:land") is StepStatus.PENDING
    assert "main" in res.detail


def test_proceeds_off_production_branch(project):
    """AC3 — on the integration branch the executor runs, commits, advances to DONE."""
    step = Step(id="REQ-011:land", command="/advance REQ-011 land", verify=("true",))
    runner = FakeRunner(default=ok_result())
    committer = RecordingCommitter()
    ex = _executor(project, [step], branch="dev", runner=runner, committer=committer)

    res = ex.advance_once()
    assert res.outcome is RunOutcome.DONE
    assert len(runner.calls) == 1
    assert committer.committed == ["REQ-011:land"]
    assert Ledger(project).status_of("REQ-011:land") is StepStatus.DONE


def test_scaffolding_documents_model():
    """AC4 — the stamped config and consumer-facing docs carry the main/dev model."""
    config_tmpl = (
        _PKG / "templates" / ".devsteward" / "config.yaml.tmpl"
    ).read_text(encoding="utf-8")
    assert "git:" in config_tmpl
    assert "production_branch: main" in config_tmpl
    assert "integration_branch: dev" in config_tmpl

    for rel in (
        Path("templates") / "CLAUDE.md.tmpl",
        Path("handbook") / "00-method.md",
        Path("handbook") / "03-workflow.md",
    ):
        text = (_PKG / rel).read_text(encoding="utf-8")
        assert "main" in text and "dev" in text and "integration" in text.lower(), rel


# -- REQ-019: implementation off the integration branch -----------------------
#
# REQ-019's *refusal* of build/land on the integration branch is deliberately superseded by
# REQ-020 (the executor now manages the feature branch instead of refusing); that
# create+switch behavior is covered by tests/test_branch_lifecycle.py AC1. The remaining
# REQ-019 tests below — design stays on the integration branch, implementation proceeds off
# it — are still true under REQ-020 and stay here.


def test_design_allowed_on_integration_branch(project):
    """AC2 — a design step proceeds on the integration branch (plans may live on dev),
    while the REQ-011 production guard still refuses everything (design included)."""
    step = Step(
        id="REQ-019:design",
        command="/advance REQ-019 design",
        verify=("true",),
        phase="design",
    )
    runner = FakeRunner(default=ok_result())
    ex = _executor(project, [step], branch="dev", runner=runner)
    res = ex.advance_once()
    assert res.outcome is RunOutcome.DONE
    assert len(runner.calls) == 1
    assert Ledger(project).status_of("REQ-019:design") is StepStatus.DONE

    # Production guard is unchanged: on `main` even a design step is refused, before
    # any claude runs.
    runner_main = FakeRunner(default=ok_result())
    ex_main = _executor(project, [step], branch="main", runner=runner_main)
    res_main = ex_main.advance_once()
    assert res_main.outcome is RunOutcome.REFUSED
    assert runner_main.calls == []
    assert "main" in res_main.detail


def test_implementation_proceeds_on_feature_branch(project):
    """AC3 — on a feature branch (neither production nor integration) build and land run,
    commit, and advance normally."""
    for phase in ("build", "land"):
        step = Step(
            id=f"REQ-019:{phase}",
            command=f"/advance REQ-019 {phase}",
            verify=("true",),
            phase=phase,
        )
        runner = FakeRunner(default=ok_result())
        committer = RecordingCommitter()
        ex = _executor(
            project, [step], branch="feature/req-019", runner=runner, committer=committer
        )
        res = ex.advance_once()
        assert res.outcome is RunOutcome.DONE, phase
        assert len(runner.calls) == 1
        assert committer.committed == [f"REQ-019:{phase}"]
        assert Ledger(project).status_of(f"REQ-019:{phase}") is StepStatus.DONE


def test_docs_state_declaration_implementation_regime():
    """AC4 — the canonical docs state the declaration-on-dev / implement-on-branch regime,
    and the intake skill no longer instructs "branch first"."""
    root = _PKG.parent  # repo root
    for path in (
        root / "CLAUDE.md",
        _PKG / "templates" / "CLAUDE.md.tmpl",
        _PKG / "handbook" / "03-workflow.md",
    ):
        text = path.read_text(encoding="utf-8").lower()
        assert "only implementation branches" in text, path

    intake = (
        _PKG / "templates" / ".claude" / "skills" / "intake" / "SKILL.md"
    ).read_text(encoding="utf-8").lower()
    assert "branch first" not in intake
    assert "not a feature branch" in intake
