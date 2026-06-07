"""REQ-013 — the reality harness: prove the engine drives a *real* ``claude -p``.

Every other test in this suite mocks Claude (``FakeRunner``), which is exactly why the
engine could look "done" while never having driven a real session end to end. This module
closes that gap with a single opt-in test that:

1. scaffolds a real, lint-clean throwaway project (with the bundled skills and one
   trivial, observably-checkable REQ);
2. runs the production executor, which shells out to a **real** ``claude -p``;
3. asserts the chain actually happened — a real file edit the engine then verified and
   committed.

The real run needs network, quota, and ``claude`` on PATH, so it is **opt-in**: it skips
unless ``DEVSTEWARD_REALITY=1`` and ``claude`` is present. The default ``pytest`` run
stays hermetic. The three hermetic meta-tests below (REQ-013's acceptance) guard the
gate's own plumbing so that a red real-run indicts the *engine*, never the fixture.

Run the real gate with::

    DEVSTEWARD_REALITY=1 python -m pytest tests/test_reality_harness.py -k real -s

It is expected to be **RED** until the engine can actually edit files (the headless
invocation must pass a permission mode) and rotate accounts (the cswap fix). That red is
the point: it is the trust gate the repair work has to turn green.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from devsteward.build import build_executor
from devsteward.cli import _package_templates, _stamp
from devsteward.config import load_config
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.lint import lint

REALITY_ENV = "DEVSTEWARD_REALITY"

# Provider is `single`: the harness proves the executor → claude → edit → verify → commit
# chain. cswap rotation has its own acceptance tests (REQ-012); pinning to single keeps
# this gate's failure mode unambiguous.
_CONFIG = """\
profile: req
accounts:
  provider: single
git:
  production_branch: main
  integration_branch: dev
"""

# The smallest possible real task: one observable artifact a real run must produce. The
# acceptance `test:` is a plain shell check the engine's verifier re-runs independently.
_REQ_001 = """\
---
id: REQ-001
title: "Emit a greeting file"
status: open
kind: feature
added: 2026-06-07
completed: null
verified_by: null
depends_on: []
concept_refs: []
scenario_refs: []
supersedes: null
tags: [reality]
---

## Context

The reality harness needs the smallest possible real task: one observable artifact a real
`claude -p` run must produce, so the end-to-end chain (executor -> claude -> edit ->
verify -> commit) is proven against reality rather than a mock.

## Requirement

Create a file `greeting.txt` at the project root whose content is the single word
`hello`.

```yaml acceptance
- id: AC1
  text: greeting.txt exists at the project root and contains the word hello.
  test: "grep -qx hello greeting.txt"
  status: pending
```

## Notes

Deliberately trivial — the harness proves the *chain*, not the task.
"""

_INDEX = """\
# Requirements Index

| ID | Title | Status | File | Depends on |
|----|-------|--------|------|------------|
| REQ-001 | Emit a greeting file | OPEN | [REQ-001](REQ-001.md) | – |
"""


def reality_skip_reason() -> str | None:
    """``None`` ⇒ run the real end-to-end gate; a string ⇒ the reason to skip it.

    Opt-in and degrading: the default test run never shells out to ``claude``, and an
    enabled-but-unavailable ``claude`` skips with a clear reason rather than erroring.
    """
    import os

    if not os.environ.get(REALITY_ENV):
        return (
            f"reality gate disabled — set {REALITY_ENV}=1 to drive a real `claude -p` "
            "end-to-end (needs network, quota, and claude on PATH)"
        )
    if shutil.which("claude") is None:
        return "claude is not on PATH — cannot run the reality gate"
    return None


def scaffold_reality_project(root: Path) -> None:
    """Stamp a real, lint-clean throwaway project: bundled skills + one trivial REQ."""
    _stamp(_package_templates(), root)
    Ledger.init(root, profile="req")
    (root / ".devsteward" / "config.yaml").write_text(_CONFIG, encoding="utf-8")
    req_dir = root / "docs" / "requirements"
    for stale in req_dir.glob("REQ-*.md"):  # drop the stamped template REQ set
        stale.unlink()
    (req_dir / "REQ-001.md").write_text(_REQ_001, encoding="utf-8")
    (req_dir / "REQUIREMENTS_INDEX.md").write_text(_INDEX, encoding="utf-8")


def init_git(root: Path) -> None:
    """A real git repo on a non-production branch so the engine is allowed to commit."""

    def g(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    g("init", "-q")
    g("config", "user.email", "reality@devsteward.test")
    g("config", "user.name", "DevSteward Reality Harness")
    g("checkout", "-q", "-b", "dev")  # off `main`, so the branch guard allows commits
    g("add", "-A")
    g("commit", "-q", "-m", "Reality harness: initial throwaway project")


# -- hermetic meta-tests (REQ-013 acceptance) ---------------------------------


def test_gate_is_opt_in_by_default(monkeypatch):
    """AC1: without the env flag the gate skips, so the default suite stays hermetic."""
    monkeypatch.delenv(REALITY_ENV, raising=False)
    reason = reality_skip_reason()
    assert reason is not None and REALITY_ENV in reason


def test_gate_skips_without_claude(monkeypatch):
    """AC2: enabled but claude absent degrades to a skip (named), never a hard error."""
    monkeypatch.setenv(REALITY_ENV, "1")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    reason = reality_skip_reason()
    assert reason is not None and "claude" in reason.lower()


def test_fixture_project_is_lintable_and_has_one_eligible_step(tmp_path):
    """AC3: the throwaway project lints green and yields exactly one eligible step.

    This is what lets a red real-run indict the engine and not the harness.
    """
    scaffold_reality_project(tmp_path)
    cfg = load_config(tmp_path)
    assert lint(cfg) == []
    ex = build_executor(cfg)
    assert [s.id for s in ex.eligible_steps()] == ["REQ-001:design"]


# -- the real end-to-end gate (opt-in) ----------------------------------------


def test_real_claude_end_to_end(tmp_path):
    """Drive a real ``claude -p`` through the production executor and prove the chain.

    Skipped unless ``DEVSTEWARD_REALITY=1`` and claude is on PATH. Expected to be RED
    until the engine can edit files and rotate accounts; that red is the trust gate.
    """
    reason = reality_skip_reason()
    if reason:
        pytest.skip(reason)

    scaffold_reality_project(tmp_path)
    init_git(tmp_path)
    cfg = load_config(tmp_path)
    ex = build_executor(cfg)

    results = ex.run(max_steps=3)  # design -> build -> land
    outcomes = {r.step.id: r.outcome.value for r in results}

    greeting = tmp_path / "greeting.txt"
    assert greeting.exists(), f"no real edit produced; outcomes={outcomes}"
    assert "hello" in greeting.read_text().split(), greeting.read_text()

    # The engine's own acceptance check is genuinely green.
    check = subprocess.run("grep -qx hello greeting.txt", shell=True, cwd=tmp_path)
    assert check.returncode == 0

    # The land step reached DONE and a real commit landed beyond the initial one.
    assert Ledger(tmp_path).status_of("REQ-001:land") is StepStatus.DONE
    count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=tmp_path, capture_output=True, text=True
    )
    assert int(count.stdout.strip()) >= 2, f"engine committed nothing; outcomes={outcomes}"
