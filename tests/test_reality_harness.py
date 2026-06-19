"""REQ-013 — the reality-gate fixture plumbing (hermetic).

REQ-013 introduced an opt-in test that drove a **real** ``claude -p`` end-to-end, to close
the gap that every other test mocks Claude (``FakeRunner``). That real-run test
(``test_real_claude_end_to_end``) was removed in REQ-052: a once-observed end-to-end
validation is not a regression test — it could only ever skip in CI (it needs network,
quota, and ``claude`` on PATH), and Claude should not be spun up as the object of a
regression test. Run that kind of check as a validation, observed, not on every suite.

What remains are REQ-013's actual acceptance criteria: the **hermetic meta-tests** that
guard the gate's own fixture plumbing — a lint-clean throwaway project with exactly one
eligible step, and the opt-in skip logic — so the fixtures stay sound and executable.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from devsteward.build import build_executor
from devsteward.cli import _package_templates, _stamp
from devsteward.config import load_config
from devsteward.core.ledger import Ledger
from devsteward.lint import lint

REALITY_ENV = "DEVSTEWARD_REALITY"

# Provider is `single`: the fixture project exercises the executor → verify chain. cswap
# rotation has its own acceptance tests (REQ-012); pinning to single keeps the fixture's
# behaviour unambiguous.
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
  check: regression
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
    """``None`` ⇒ the real end-to-end gate could run; a string ⇒ the reason it would skip.

    Kept as the predicate the opt-in meta-tests exercise: the default test run never shells
    out to ``claude``, and an enabled-but-unavailable ``claude`` degrades to a clear reason
    rather than an error.
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
    # REQ-029: the mechanical land refuses to land a REQ with no plan that names it. The
    # harness's trivial REQ gets a one-line plan so the real e2e still reaches DONE.
    plans_dir = root / "docs" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "0001-greeting.md").write_text(
        "# Plan 0001 — REQ-001 greeting\n\nWrite `greeting.txt` containing `hello`.\n",
        encoding="utf-8",
    )


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
    assert [s.id for s in ex.eligible_steps()] == ["REQ-001:develop"]
