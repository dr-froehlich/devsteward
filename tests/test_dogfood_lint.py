"""REQ-001 AC2 — DevSteward's own requirements lint green in the format it ships.

This is the dogfood proof and Phase-1 verification #1: the framework's own REQs are
schema-valid, their deps resolve, the index is in sync, and every acceptance criterion
names a test.
"""

from __future__ import annotations

from pathlib import Path

from devsteward.config import load_config
from devsteward.lint import lint

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_devsteward_own_reqs_lint_green():
    cfg = load_config(REPO_ROOT)
    problems = lint(cfg)
    assert problems == [], "\n".join(problems)
