"""REQ-020 — the executor manages the implementation feature branch end-to-end.

REQ-011 and REQ-019 *guarded* topology (refuse on production; refuse implementation on the
integration branch). REQ-020 replaces the integration-branch refusal with *management*: on
the integration branch the implementation step lazily creates+switches to the REQ's feature
branch, and its green land merges it back ``--no-ff``. The production guard (REQ-011) is
untouched. After REQ-029 the single implementation phase is ``develop`` (it carries the
acceptance gate and triggers the merge on green).

Driven through ``FakeGitTopology`` (no real checkout), consistent with ``test_branch_guard``:
the fake records ``created``/``switched``/``commits``/``merged`` so the create→run→merge
dance is assertable in memory.
"""

from __future__ import annotations

from pathlib import Path

from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Step, StepStatus
from devsteward.core.verify import CommandVerifier
from devsteward.profiles.req.source import _slugify

from conftest import (
    FakeGitTopology,
    FakeRunner,
    RecordingCommitter,
    ListStepSource,
    ok_result,
    park_result,
)

_SLUG = "branch-lifecycle-automation"
_FEATURE = "req-020-branch-lifecycle-automation"


def _executor(root, steps, *, git, runner=None, committer=None):
    return Executor(
        root=root,
        source=ListStepSource(steps),
        verifier=CommandVerifier(cwd=str(root)),
        accounts=SingleAccountProvider(),
        runner=runner or FakeRunner(default=ok_result()),
        committer=committer or RecordingCommitter(),
        production_branch="main",
        integration_branch="dev",
        feature_branch_template="req-{num}-{slug}",
        git=git,
    )


def _step(phase, *, req="REQ-020", slug=_SLUG, verify=()):
    return Step(
        id=f"{req}:{phase}",
        command=f"/advance {req} {phase}",
        verify=verify,
        phase=phase,
        req=req,
        slug=slug,
    )


def test_creates_and_switches_branch_on_first_develop(project):
    """AC1 — on the integration branch an eligible develop step creates+switches to the
    REQ's feature branch (default ``req-<nnn>-<slug>``) and runs the step, instead of
    refusing."""
    git = FakeGitTopology(current="dev")
    runner = FakeRunner(default=ok_result())
    ex = _executor(project, [_step("develop")], git=git, runner=runner)

    res = ex.advance_once()
    assert res.outcome is RunOutcome.DONE
    assert git.created == [_FEATURE]
    assert _FEATURE in git.switched  # created+switched onto the feature branch to run
    assert len(runner.calls) == 1  # the step actually ran (not refused)
    assert Ledger(project).status_of("REQ-020:develop") is StepStatus.DONE


def test_non_implementation_phase_stays_on_integration(project):
    """AC2 — a non-implementation step (phase not in ``implementation_phases``) runs on the
    integration branch with no branch created; creation is lazy on implementation only.
    After REQ-029 declaration (intake/plan) is no longer a step at all, but the guard that
    only implementation phases branch is preserved."""
    git = FakeGitTopology(current="dev")
    ex = _executor(project, [_step("note")], git=git)

    res = ex.advance_once()
    assert res.outcome is RunOutcome.DONE
    assert git.created == []
    assert git.current == "dev"


def test_auto_merges_no_ff_after_green_develop(project):
    """AC3 — after a green develop the executor merges the feature branch into the
    integration branch with --no-ff (the only merge path) and the co-author trailer."""
    git = FakeGitTopology(current="dev")
    ex = _executor(project, [_step("develop", verify=("true",))], git=git)

    res = ex.advance_once()
    assert res.outcome is RunOutcome.DONE
    assert git.created == [_FEATURE]
    assert len(git.merged) == 1
    feature, into, message = git.merged[0]
    assert feature == _FEATURE and into == "dev"
    assert "Co-Authored-By: Claude Opus 4.8" in message
    assert git.current == "dev"  # back on the integration branch at rest


def test_ledger_clean_on_integration_at_rest(project):
    """AC4 — the trailing post-land cursor write (status done + checkpoint event) is
    committed on the feature branch before the merge, so the integration branch is clean
    at rest rather than left dirty."""
    git = FakeGitTopology(current="dev")
    ex = _executor(project, [_step("develop", verify=("true",))], git=git)

    res = ex.advance_once()
    assert res.outcome is RunOutcome.DONE
    # the trailing ledger write is committed on the feature branch, before switching back
    assert any(
        branch == _FEATURE and "ledger checkpoint" in msg for branch, msg in git.commits
    )
    assert git.merged and git.merged[0][1] == "dev"
    assert git.current == "dev"
    assert Ledger(project).status_of("REQ-020:develop") is StepStatus.DONE


def test_no_merge_on_failed_or_parked_develop(project):
    """AC5 — a develop that fails verification or parks a decision is not merged; the
    feature branch stays checked out for inspection. (No repair budget on the bare
    executor, so a red gate surfaces VERIFY_FAILED directly — REQ-029.)"""
    # (a) failed verification
    git = FakeGitTopology(current="dev")
    ex = _executor(project, [_step("develop", verify=("false",))], git=git)
    res = ex.advance_once()
    assert res.outcome is RunOutcome.VERIFY_FAILED
    assert git.merged == []
    assert git.current == _FEATURE  # stays on the feature branch

    # (b) parked decision (unattended fork)
    git2 = FakeGitTopology(current="dev")
    runner = FakeRunner(default=park_result("which database?"))
    ex2 = _executor(
        project, [_step("develop", req="REQ-021", verify=("true",))], git=git2, runner=runner
    )
    res2 = ex2.advance_once()
    assert res2.outcome is RunOutcome.PARKED
    assert git2.merged == []
    assert git2.current == "req-021-branch-lifecycle-automation"


def test_reuses_existing_feature_branch(project):
    """AC6 — an existing feature branch from a partial prior run is reused, not re-created;
    a diverged branch is surfaced rather than silently merged over."""
    # (a) reuse: branch exists and has not diverged
    git = FakeGitTopology(current="dev", branches={"dev", _FEATURE})
    ex = _executor(project, [_step("develop")], git=git)
    res = ex.advance_once()
    assert res.outcome is RunOutcome.DONE
    assert git.created == []  # reused, not created
    assert _FEATURE in git.switched  # switched onto the existing feature branch

    # (b) diverged: surfaced, the step does not run, no switch, no merge. A distinct REQ id
    # keeps this eligible (part (a) already marked REQ-020:build done in the shared ledger).
    diverged = "req-099-branch-lifecycle-automation"
    git2 = FakeGitTopology(current="dev", branches={"dev", diverged}, diverged={diverged})
    runner = FakeRunner(default=ok_result())
    committer = RecordingCommitter()
    ex2 = _executor(
        project, [_step("develop", req="REQ-099")], git=git2, runner=runner, committer=committer
    )
    res2 = ex2.advance_once()
    assert res2.outcome is RunOutcome.REFUSED
    assert runner.calls == []
    assert committer.committed == []
    assert git2.switched == []
    assert git2.current == "dev"
    assert "diverged" in res2.detail


def test_production_guard_unchanged(project):
    """AC7 — the REQ-011 production guard is untouched: on the production branch the
    executor still refuses (no claude, no commit, no branch ops), step stays pending."""
    git = FakeGitTopology(current="main")
    runner = FakeRunner(default=ok_result())
    committer = RecordingCommitter()
    ex = _executor(
        project, [_step("develop", verify=("true",))], git=git, runner=runner, committer=committer
    )

    res = ex.advance_once()
    assert res.outcome is RunOutcome.REFUSED
    assert runner.calls == []
    assert committer.committed == []
    assert git.created == [] and git.merged == [] and git.switched == []
    assert "main" in res.detail
    assert Ledger(project).status_of("REQ-020:develop") is StepStatus.PENDING


def test_slug_and_branch_name_derivation(project):
    """The profile derives the slug from the REQ title; the executor formats the config
    template (keeping a lettered REQ suffix in ``num``)."""
    assert _slugify("Branch lifecycle automation — the executor manages it") == _SLUG
    assert _slugify("Converter — normalize memzy's frontmatter REQ dialect") == "converter"

    git = FakeGitTopology(current="dev")
    ex = _executor(project, [], git=git)
    step = _step("develop", req="REQ-022a", slug="onboarding-tooling")
    assert ex.feature_branch_name(step) == "req-022a-onboarding-tooling"
