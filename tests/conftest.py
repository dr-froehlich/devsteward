"""Shared test fixtures and fakes for the DevSteward engine.

The fakes let us drive the full executor loop without a real ``claude`` on PATH and
without committing to git, so the tests are fast and deterministic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devsteward.core import claude as claude_mod
from devsteward.core.model import Step


class FakeRunner:
    """Stand-in for :func:`devsteward.core.claude.run_claude`.

    ``script`` maps a substring-of-command → the :class:`Result` to return, so a test can
    make one step "park" (sentinel in text) and another succeed. Records every call's
    ``unattended`` flag and command for assertions.
    """

    def __init__(self, script: dict[str, claude_mod.Result] | None = None,
                 default: claude_mod.Result | None = None):
        self.script = script or {}
        self.default = default or claude_mod.Result(
            outcome=claude_mod.Outcome.OK, text="done", raw_lines=[], returncode=0
        )
        self.calls: list[dict] = []

    def __call__(self, command, *, argv_prefix=None, cwd=None, env=None,
                 timeout=1800.0, unattended=True, on_event=None):
        self.calls.append(
            {"command": command, "argv_prefix": argv_prefix, "cwd": cwd,
             "unattended": unattended}
        )
        for key, result in self.script.items():
            if key in command:
                return result
        return self.default


def ok_result(text: str = "ok") -> claude_mod.Result:
    return claude_mod.Result(claude_mod.Outcome.OK, text, [], 0)


def park_result(question: str) -> claude_mod.Result:
    from devsteward.core.executor import PARK_SENTINEL

    return claude_mod.Result(
        claude_mod.Outcome.OK, f"{PARK_SENTINEL} {question}", [], 0
    )


def limit_result() -> claude_mod.Result:
    return claude_mod.Result(claude_mod.Outcome.USAGE_LIMIT, "usage limit reached", [], 0)


class ListStepSource:
    """A trivial StepSource returning a fixed list — for core-only tests."""

    def __init__(self, steps: list[Step]):
        self._steps = steps

    def steps(self, ledger=None) -> list[Step]:
        return list(self._steps)


class RecordingCommitter:
    """A committer stub: returns a fake sha and records which steps it committed."""

    def __init__(self):
        self.committed: list[str] = []

    def __call__(self, step: Step) -> str:
        self.committed.append(step.id)
        return "deadbeef" + step.id.replace(":", "")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """An empty project dir with an initialized ledger."""
    from devsteward.core.ledger import Ledger

    Ledger.init(tmp_path, profile="req")
    return tmp_path


def write_req(req_dir: Path, rid: str, *, status="open", depends_on=(), acceptance=True,
              title=None, kind="feature"):
    """Write a minimal, schema-valid REQ file into ``req_dir``."""
    req_dir.mkdir(parents=True, exist_ok=True)
    title = title or f"{rid} title"
    deps = "[" + ", ".join(depends_on) + "]"
    acc = ""
    if acceptance:
        acc = (
            "\n```yaml acceptance\n"
            "- id: AC1\n"
            f"  text: {rid} works.\n"
            '  test: "true"\n'
            "  status: pending\n"
            "```\n"
        )
    text = (
        f"---\n"
        f"id: {rid}\n"
        f'title: "{title}"\n'
        f"status: {status}\n"
        f"kind: {kind}\n"
        f"added: 2026-06-06\n"
        f"completed: null\n"
        f"verified_by: null\n"
        f"depends_on: {deps}\n"
        f"concept_refs: []\n"
        f"scenario_refs: []\n"
        f"supersedes: null\n"
        f"tags: []\n"
        f"---\n\n"
        f"## Context\n\n{rid} context.\n\n"
        f"## Requirement\n\nDo the thing.\n{acc}\n"
        f"## Notes\n\nNone.\n"
    )
    (req_dir / f"{rid}.md").write_text(text, encoding="utf-8")


def write_index(req_dir: Path, rows: list[tuple[str, str, str, str]]):
    """Write a REQUIREMENTS_INDEX.md. ``rows`` = (id, title, STATUS, deps)."""
    lines = [
        "# Requirements Index", "",
        "| ID | Title | Status | File | Depends on |",
        "|----|-------|--------|------|------------|",
    ]
    for rid, title, status, deps in rows:
        lines.append(f"| {rid} | {title} | {status} | [{rid}]({rid}.md) | {deps or '–'} |")
    (req_dir / "REQUIREMENTS_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
