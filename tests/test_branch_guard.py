"""Branch guard.

REQ-011 — the engine refuses to autocommit on the production branch (``main``). That is the
*only* branch guard left: REQ-048 made the engine trunk-based, so there is no feature-branch
regime to enforce — everything else runs on ``dev``.

The branch state is supplied by an injectable :class:`FakeGitTopology` seam, so the guard
drives without a real git checkout — consistent with conftest's goal of exercising the full
loop without committing to git.
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
        Path("handbook") / "_00-method.qmd",
        Path("handbook") / "_03-workflow.qmd",
    ):
        text = (_PKG / rel).read_text(encoding="utf-8")
        assert "main" in text and "dev" in text and "integration" in text.lower(), rel


# -- REQ-048: trunk-based — every non-production branch just proceeds ----------


def test_develop_proceeds_on_dev(project):
    """A develop implementation step runs, commits, and advances on ``dev`` — REQ-048: no
    feature branch, the work lands where it runs."""
    step = Step(
        id="REQ-019:develop",
        command="/advance REQ-019 develop",
        verify=("true",),
        phase="develop",
    )
    runner = FakeRunner(default=ok_result())
    committer = RecordingCommitter()
    ex = _executor(project, [step], branch="dev", runner=runner, committer=committer)
    res = ex.advance_once()
    assert res.outcome is RunOutcome.DONE
    assert len(runner.calls) == 1
    assert committer.committed == ["REQ-019:develop"]
    assert Ledger(project).status_of("REQ-019:develop") is StepStatus.DONE
