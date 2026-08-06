"""REQ-087 — the north star lands at bootstrap, verified rather than asserted.

A stamped REQ-001 used to ship ``status: open`` with the whole test suite as its acceptance
criterion. The profile derives a ``:develop`` step for every *active* REQ, so the north star
was a permanently-eligible work item with nothing to build — and on the day someone finally
ran it, its whole-suite criterion failed the capture check from a bare extract (DocSteward,
2026-08-05: 517 passed in the working tree, 36 collection errors in the extract).

The cure is entirely in the scaffolding: a stdlib-only ``tests/test_project_initialized.py``
that checks *initialization* rather than function, REQ-001's criterion narrowed to it, and
``/bootstrap`` closing with ``steward checkpoint`` so the engine certifies the flip.

* **AC1** ``test_initialization_check_passes_from_bare_extract``
* **AC2** ``test_stamped_skeleton_lands_req001_via_checkpoint``
* **AC3** ``test_no_eligible_step_after_bootstrap``
* **AC4** ``test_initialization_check_fails_on_broken_skeleton``
* **AC5** ``test_shipped_contract_is_coherent``
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from devsteward.cli import main
from devsteward.core.ledger import Ledger, StepStatus

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = REPO / "devsteward" / "templates"
SHIPPED_CHECK = Path("tests") / "test_project_initialized.py"

# What `/bootstrap` fills in from its interview.
ANSWERS = {
    "PROJECT_NAME": "Consumer",
    "PROJECT_DESCRIPTION": "A consumer project stamped for this test.",
    "STACK": "Python 3.12, pytest.",
    "BUILD_COMMAND": "python -m build",
    "TEST_COMMAND": "python -m pytest",
    "NORTH_STAR_GOAL": "prove the north star lands at bootstrap",
    "NORTH_STAR_OUTCOME": "a coherent, initialized project",
    "NORTH_STAR_USER": "the operator",
}

PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")

# Modules the shipped check may import. The engine's capture check (REQ-063) re-runs it
# from a bare extract with nothing installed, so anything beyond the standard library and
# pytest would pass in the working tree and fail the gate.
ALLOWED_IMPORTS = {"__future__", "re", "pathlib", "pytest", "os", "sys", "json"}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _bootstrapped(tmp_path: Path, name: str = "consumer") -> Path:
    """A stamped project at the exact moment `/bootstrap` calls `steward checkpoint`:
    placeholders filled, first commit made on `dev`, nothing landed yet."""
    project = tmp_path / name
    result = CliRunner().invoke(main, ["new", str(project)], catch_exceptions=False)
    assert result.exit_code == 0, result.output

    for path in sorted(project.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".yaml", ".yml"}:
            continue
        if "_templates" in path.relative_to(project).parts:
            continue  # stencils keep their tokens
        if path.relative_to(project).parts[:2] == (".claude", "skills"):
            continue  # instruction text quotes the tokens on purpose
        text = path.read_text(encoding="utf-8")
        filled = PLACEHOLDER.sub(lambda m: ANSWERS.get(m.group(1), m.group(0)), text)
        if filled != text:
            path.write_text(filled, encoding="utf-8")

    _git(project, "init", "-q")
    _git(project, "config", "user.email", "req087@devsteward.test")
    _git(project, "config", "user.name", "DevSteward REQ-087 Test")
    _git(project, "checkout", "-q", "-b", "dev")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "bootstrap: initial skeleton")
    return project


def _run_shipped_check(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(SHIPPED_CHECK), "-q"],
        cwd=root,
        capture_output=True,
        text=True,
    )


def _index_status(project: Path, req: str = "REQ-001") -> str:
    index = project / "docs" / "requirements" / "REQUIREMENTS_INDEX.md"
    for line in index.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith(f"| {req} "):
            return [c.strip() for c in line.strip().strip("|").split("|")][2]
    pytest.fail(f"no index row for {req}")


# -- AC1: the shipped check survives a bare extract -----------------------------


def test_initialization_check_passes_from_bare_extract(tmp_path):
    """AC1: the criterion REQ-001 names passes from a `git archive` extract of the committed
    tree — no virtualenv, nothing installed — which is exactly where REQ-063's capture check
    runs it, and exactly where the old whole-suite criterion died."""
    project = _bootstrapped(tmp_path)

    # It passes in the working tree...
    assert _run_shipped_check(project).returncode == 0

    # ...and, the part that matters, from a bare extract of what was actually committed.
    extract = tmp_path / "extract"
    extract.mkdir()
    archive = subprocess.run(
        ["git", "archive", "HEAD"], cwd=project, check=True, capture_output=True
    )
    subprocess.run(["tar", "-x", "-C", str(extract)], input=archive.stdout, check=True)
    assert (extract / SHIPPED_CHECK).is_file(), "the check was not committed"

    done = _run_shipped_check(extract)
    assert done.returncode == 0, f"the shipped check fails from a bare extract:\n{done.stdout}"

    # The reason it survives: it imports nothing that a bare extract lacks.
    tree = ast.parse((extract / SHIPPED_CHECK).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert imported <= ALLOWED_IMPORTS, (
        f"the shipped check imports {sorted(imported - ALLOWED_IMPORTS)} — anything beyond "
        f"the stdlib and pytest breaks it in the capture extract"
    )


# -- AC2: the engine lands REQ-001 ----------------------------------------------


def test_stamped_skeleton_lands_req001_via_checkpoint(tmp_path, monkeypatch):
    """AC2: `steward checkpoint` — the closing act of `/bootstrap` — verifies REQ-001 and
    lands it: ledger step done, frontmatter and index flipped together in one commit, clean
    tree after. Nothing here asserts a status; the engine certifies it."""
    project = _bootstrapped(tmp_path)
    req_file = project / "docs" / "requirements" / "REQ-001.md"
    assert "status: open" in req_file.read_text(encoding="utf-8")

    monkeypatch.chdir(project)
    result = CliRunner().invoke(main, ["checkpoint", "REQ-001", "develop"])
    assert result.exit_code == 0, result.output

    assert Ledger(project).status_of("REQ-001:develop") is StepStatus.DONE

    text = req_file.read_text(encoding="utf-8")
    assert "status: done" in text
    assert _index_status(project).upper() == "DONE"

    # Same-commit discipline (REQ-077): the flip rode the code commit, not a follow-up.
    flip_commit = _git(project, "log", "-1", "--format=%H", "--", "docs/requirements/REQ-001.md").strip()
    touched = _git(project, "show", "--name-only", "--format=", flip_commit).split()
    assert "docs/requirements/REQUIREMENTS_INDEX.md" in touched, (
        f"the index sync did not ride the same commit as the REQ flip ({flip_commit[:8]})"
    )

    assert _git(project, "status", "--porcelain").strip() == "", "the land left a dirty tree"


# -- AC3: the north star stops being eligible ------------------------------------


def test_no_eligible_step_after_bootstrap(tmp_path, monkeypatch):
    """AC3: the defect itself. Before the checkpoint REQ-001:develop is eligible — that is
    the state every consumer used to sit in forever, advertised by `steward status` as the
    next thing to do. After it, the board is empty and the operator's next move is /intake."""
    project = _bootstrapped(tmp_path)
    monkeypatch.chdir(project)

    before = CliRunner().invoke(main, ["status"])
    assert before.exit_code == 0, before.output
    assert "REQ-001:develop" in before.output and "eligible" in before.output, (
        f"expected the pre-checkpoint north star to be eligible:\n{before.output}"
    )

    landed = CliRunner().invoke(main, ["checkpoint", "REQ-001", "develop"])
    assert landed.exit_code == 0, landed.output

    after = CliRunner().invoke(main, ["status"])
    assert after.exit_code == 0, after.output
    assert "eligible" not in after.output, (
        f"a bootstrapped project should have nothing eligible:\n{after.output}"
    )


# -- AC4: the assurance can go red -----------------------------------------------


def test_initialization_check_fails_on_broken_skeleton(tmp_path):
    """AC4: disconfirmability. Three independent corruptions, each of which means
    initialization really is incomplete, must red the shipped check. A criterion that
    cannot fail certifies nothing — which is what a green on an empty suite was."""
    # (a) the index row contradicts the frontmatter — the pair is the source of truth.
    disagree = _bootstrapped(tmp_path, "disagree")
    index = disagree / "docs" / "requirements" / "REQUIREMENTS_INDEX.md"
    index.write_text(
        index.read_text(encoding="utf-8").replace("| OPEN |", "| DONE |"), encoding="utf-8"
    )
    result = _run_shipped_check(disagree)
    assert result.returncode != 0, f"a desynced index row passed:\n{result.stdout}"

    # (b) no ledger — `steward init` never ran.
    unledgered = _bootstrapped(tmp_path, "unledgered")
    (unledgered / ".devsteward" / "state.yaml").unlink()
    result = _run_shipped_check(unledgered)
    assert result.returncode != 0, f"a missing ledger passed:\n{result.stdout}"

    # (c) an unfilled placeholder — the interview never finished.
    unfilled = _bootstrapped(tmp_path, "unfilled")
    claude_md = unfilled / "CLAUDE.md"
    claude_md.write_text(
        claude_md.read_text(encoding="utf-8") + "\nStack: {{STACK}}\n", encoding="utf-8"
    )
    result = _run_shipped_check(unfilled)
    assert result.returncode != 0, f"a surviving placeholder passed:\n{result.stdout}"


# -- AC5: the shipped contract hangs together ------------------------------------


def test_shipped_contract_is_coherent(tmp_path):
    """AC5: the four artifacts agree — the check is shipped, REQ-001 names it and not the
    whole suite, a plan artifact exists for the land gate, and `/bootstrap` closes with
    `steward checkpoint` in both copies of the skill (which are one inode)."""
    assert (TEMPLATES / SHIPPED_CHECK).is_file(), "the initialization check is not shipped"

    req_tmpl = (TEMPLATES / "docs" / "requirements" / "REQ-001.md.tmpl").read_text(encoding="utf-8")
    assert "tests/test_project_initialized.py" in req_tmpl, (
        "the stamped REQ-001 does not name the initialization check"
    )
    assert "{{TEST_COMMAND}}" not in req_tmpl, (
        "the stamped REQ-001 still carries the whole-suite acceptance criterion — the exact "
        "shape that cannot pass the capture check"
    )

    # The land gate refuses a REQ no plan names, so bootstrap's checkpoint needs one shipped.
    plans = TEMPLATES / "docs" / "plans"
    assert any("REQ-001" in p.read_text(encoding="utf-8") for p in plans.glob("*.md")), (
        "no shipped plan artifact names REQ-001 — `steward checkpoint` would refuse the land"
    )

    for skill in (
        REPO / ".claude" / "skills" / "bootstrap" / "SKILL.md",
        TEMPLATES / ".claude" / "skills" / "bootstrap" / "SKILL.md",
    ):
        assert "steward checkpoint" in skill.read_text(encoding="utf-8"), (
            f"{skill} does not instruct the closing checkpoint"
        )


def test_stamped_check_is_not_collected_by_this_project(tmp_path):
    """Guard: the shipped check lives inside the package tree at
    `devsteward/templates/tests/`. DevSteward's own `testpaths = ["tests"]` must keep it out
    of this project's collection — it asserts a *consumer's* scaffolding, not DevSteward's."""
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert "templates/tests/test_project_initialized.py" not in collected.stdout
