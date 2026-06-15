"""Shared test fixtures and fakes for the DevSteward engine.

The fakes let us drive the full executor loop without a real ``claude`` on PATH and
without committing to git, so the tests are fast and deterministic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from devsteward.core import claude as claude_mod
from devsteward.core.model import Step

# REQ-010: the memzy converter lives in scripts/ (a run-once migration tool), not in the
# installable package. Put scripts/ on sys.path so the acceptance tests can import it.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


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
                 timeout=1800.0, unattended=True, permission_mode=None,
                 model=None, effort=None, on_event=None, on_spawn=None):
        self.calls.append(
            {"command": command, "argv_prefix": argv_prefix, "cwd": cwd,
             "unattended": unattended, "permission_mode": permission_mode,
             "model": model, "effort": effort, "on_spawn": on_spawn}
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


class FakeGitTopology:
    """In-memory :class:`devsteward.core.seams.GitTopology` (REQ-020).

    Models the checked-out branch, the set of existing branches, and a minimal divergence
    relation, so create→run→merge is exercised and assertable without a real checkout
    (``conftest``'s no-git goal). Records the op sequence: ``created``, ``switched``,
    ``commits`` (``(branch, message)``), ``merged`` (``(feature, into, message)``).
    """

    def __init__(self, current: str = "dev", branches=None, diverged=()):
        self.current = current
        self.branches = set(branches or [current])
        self._diverged = set(diverged)
        self.created: list[str] = []
        self.switched: list[str] = []
        self.commits: list[tuple[str, str]] = []
        self.merged: list[tuple[str, str, str]] = []
        self.reconciled: list[tuple[str, str]] = []

    def current_branch(self) -> str:
        return self.current

    def branch_exists(self, name: str) -> bool:
        return name in self.branches

    def create_and_switch(self, name: str) -> None:
        self.branches.add(name)
        self.current = name
        self.created.append(name)
        self.switched.append(name)

    def switch(self, name: str) -> None:
        self.branches.add(name)
        self.current = name
        self.switched.append(name)

    def integration_is_ancestor(self, integration: str, feature: str) -> bool:
        return feature not in self._diverged

    def commit_all(self, message: str, *, exclude_ledger: bool = False) -> str | None:
        self.commits.append((self.current, message))
        return f"sha{len(self.commits):04d}"

    def merge_no_ff(self, feature: str, message: str) -> None:
        self.merged.append((feature, self.current, message))

    def reconcile_from_integration(
        self, integration: str, feature: str, message: str
    ) -> None:
        self.switch(feature)
        self._diverged.discard(feature)  # behind-but-merged → current again (REQ-034 D5)
        self.commits.append((self.current, message))
        self.reconciled.append((integration, feature))

    # -- REQ-037: the in-memory fake never models *which branch* the ledger lands on (that is
    # exactly the blind spot the real-git ACs exist to cover), so it reports "no worktree"
    # and the executor keeps its legacy single-tree path; the atomic merge/reconcile delegate
    # to the conflict-free in-memory ops.
    def integration_worktree(self, integration: str) -> str | None:
        return None

    def remove_integration_worktree(self, integration: str) -> None:
        return None

    def clean_untracked_ledger(self) -> None:
        return None

    def commit_ledger_at(self, worktree: str, message: str) -> str | None:
        self.commits.append((self.current, message))
        return f"sha{len(self.commits):04d}"

    def fetch(self) -> bool:
        return False

    def feature_behind_remote(self, feature: str) -> bool:
        return False

    def incorporate_remote(self, feature: str) -> str | None:
        return None

    def try_merge_no_ff(self, feature: str, message: str) -> str | None:
        self.merge_no_ff(feature, message)
        return None

    def try_reconcile_from_integration(
        self, integration: str, feature: str, message: str
    ) -> str | None:
        self.reconcile_from_integration(integration, feature, message)
        return None


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """An empty project dir with an initialized ledger."""
    from devsteward.core.ledger import Ledger

    Ledger.init(tmp_path, profile="req")
    return tmp_path


def write_req(req_dir: Path, rid: str, *, status="open", depends_on=(), acceptance=True,
              title=None, kind="feature", check="regression", process=None):
    """Write a minimal, schema-valid REQ file into ``req_dir``.

    ``check`` classifies the single acceptance criterion (REQ-027); ``None`` omits the
    line (an undeclared check). ``process`` is an optional dict rendered as the
    ``process:`` frontmatter block.
    """
    req_dir.mkdir(parents=True, exist_ok=True)
    title = title or f"{rid} title"
    deps = "[" + ", ".join(depends_on) + "]"
    acc = ""
    if acceptance:
        check_line = f"  check: {check}\n" if check else ""
        acc = (
            "\n```yaml acceptance\n"
            "- id: AC1\n"
            f"  text: {rid} works.\n"
            '  test: "true"\n'
            f"{check_line}"
            "  status: pending\n"
            "```\n"
        )
    proc = ""
    if process is not None:
        lines = ["process:"]
        for key, value in process.items():
            if isinstance(value, list):
                lines.append(f"  {key}: [{', '.join(value)}]")
            elif isinstance(value, bool):
                lines.append(f"  {key}: {str(value).lower()}")
            else:
                lines.append(f"  {key}: {value}")
        proc = "\n".join(lines) + "\n"
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
        f"{proc}"
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
