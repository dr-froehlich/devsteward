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


class AuthoringRunner:
    """A fake :func:`run_claude` that authors the session's files *during* the call.

    The real headless shape: the develop/validate session writes its work into the tree and
    the engine's whole-tree stage (REQ-079) commits it. ``writes`` maps a repo-relative path
    → its contents, written into ``cwd`` when the runner is invoked; ``result`` is the
    returned outcome (default OK). Records each call for assertions.
    """

    def __init__(self, writes: dict[str, str] | None = None, *,
                 result: claude_mod.Result | None = None):
        self.writes = writes or {}
        self.result = result or ok_result()
        self.calls: list[dict] = []

    def __call__(self, command, *, argv_prefix=None, cwd=None, env=None,
                 timeout=1800.0, unattended=True, permission_mode=None,
                 model=None, effort=None, on_event=None, on_spawn=None):
        self.calls.append({"command": command, "cwd": cwd, "unattended": unattended})
        root = Path(cwd)
        for rel, content in self.writes.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return self.result


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
    """In-memory :class:`devsteward.core.seams.GitTopology` (REQ-048: trunk-based).

    The engine works on one branch and makes two commits per landed step (code, then
    ledger) — there is no branch/switch/merge to model. Records the checked-out branch and
    the commit sequence as ``commits`` (``(branch, message)``) so the loop is exercised and
    assertable without a real checkout (``conftest``'s no-git goal).
    """

    def __init__(self, current: str = "dev"):
        self.current = current
        self.commits: list[tuple[str, str]] = []
        self.resets: list[str] = []
        self.forced_paths: set[str] = set()

    def current_branch(self) -> str:
        return self.current

    def head_sha(self) -> str:
        return f"sha{len(self.commits):04d}"

    def dirty_paths(self) -> set[str]:
        # No working tree to inspect: nothing is ever left dirty, so the post-land
        # clean-tree assertion (REQ-077) is trivially satisfied under the fake.
        return set()

    def commit_code(self, message: str, *, force_paths=()) -> str | None:
        # ``force_paths`` (REQ-088) is a real-git staging concern — there is no stat cache to
        # defeat here. Recorded so a test can assert what the executor handed over.
        self.forced_paths = {str(p) for p in force_paths}
        self.commits.append((self.current, message))
        return f"sha{len(self.commits):04d}"

    def write_code_tree(self) -> str | None:
        # No real object store — the capture self-check is a no-op under the fake (it is also
        # gated on a real ``.git`` dir before ever reaching here).
        return None

    def commit_ledger(self, message: str) -> str | None:
        self.commits.append((self.current, message))
        return f"sha{len(self.commits):04d}"

    def reset_hard(self, sha: str) -> None:
        # The in-memory loop never raises, so the transaction rollback is not exercised here;
        # record the call and truncate the recorded commits to the snapshot for fidelity.
        self.resets.append(sha)
        n = int(sha[3:]) if sha.startswith("sha") else len(self.commits)
        del self.commits[n:]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """An empty project dir with an initialized ledger."""
    from devsteward.core.ledger import Ledger

    Ledger.init(tmp_path, profile="req")
    return tmp_path


def write_req(req_dir: Path, rid: str, *, status="open", depends_on=(), acceptance=True,
              title=None, kind="feature", check="regression", process=None, concept_refs=(),
              test=None, supersedes=None, tags=(), backlog_refs=()):
    """Write a minimal, schema-valid REQ file into ``req_dir``.

    ``check`` classifies the single acceptance criterion (REQ-027/REQ-068); ``None`` omits
    the line (an undeclared check). ``test`` overrides the AC's runnable ``test:`` string
    (default ``"true"``) — used to give an ``artifact``/``manual`` AC a real node-id.
    ``process`` is an optional dict rendered as the ``process:`` frontmatter block.
    ``concept_refs`` populates the ``concept_refs:`` list (REQ-039 — the develop land gate
    for a concept REQ checks it references the doc). ``supersedes`` takes a single id or a
    list of ids and ``tags`` a list of labels (REQ-092 — the ``north-star`` tag marks the
    REQ holding the compass). ``backlog_refs`` populates the ``backlog_refs:`` list
    (REQ-093 — the backlog item handles the REQ takes up).
    """
    req_dir.mkdir(parents=True, exist_ok=True)
    title = title or f"{rid} title"
    deps = "[" + ", ".join(depends_on) + "]"
    acc = ""
    if acceptance:
        check_line = f"  check: {check}\n" if check else ""
        test_str = test if test is not None else "true"
        acc = (
            "\n```yaml acceptance\n"
            "- id: AC1\n"
            f"  text: {rid} works.\n"
            f'  test: "{test_str}"\n'
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
    refs = "[" + ", ".join(concept_refs) + "]"
    if supersedes is None:
        sup = "null"
    elif isinstance(supersedes, str):
        sup = supersedes
    else:
        sup = "[" + ", ".join(supersedes) + "]"
    tag_list = "[" + ", ".join(tags) + "]"
    backlog_list = "[" + ", ".join(backlog_refs) + "]"
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
        f"concept_refs: {refs}\n"
        f"scenario_refs: []\n"
        f"supersedes: {sup}\n"
        f"tags: {tag_list}\n"
        f"backlog_refs: {backlog_list}\n"
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
