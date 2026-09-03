"""REQ-096 — the package ships ``req.schema.json`` exactly once.

The stamped twin under ``templates/docs/requirements/schema/`` had drifted two REQ-cycles
behind the packaged copy: REQ-048 widened ``supersedes`` to accept a list and REQ-051 added
``process.fixtures``, and neither reached it. The cause was not an unknown duty — REQ-021's
own text names both paths — but a hand-remembered obligation with nothing mechanical behind
it.

It was deleted rather than fixed-and-guarded, because nothing read it: no Python resolved
the stamped path (``lint`` reads ``files("devsteward") / "schema"`` in every project), no
shipped doc pointed at it, ``steward sync`` never tracked it, and half the consumer fleet
had none. Every *other* artifact this package ships twice is unified at the filesystem
(inode-shared or symlinked), so after this deletion there is no duplicate left for a guard
to police — the invariant is carried by doctrine in DevSteward's own ``CLAUDE.md`` instead.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

import devsteward
from devsteward.cli import main
from devsteward.config import load_config
from devsteward.lint import lint

PACKAGE = Path(devsteward.__file__).parent
REPO_ROOT = PACKAGE.parent


# -- AC1 — exactly one schema ships -------------------------------------------


def test_package_ships_exactly_one_schema():
    """Exactly one ``req.schema.json`` exists in the package, at ``devsteward/schema/``,
    and the stamped directory is gone."""
    found = sorted(p.relative_to(PACKAGE).as_posix()
                   for p in PACKAGE.rglob("req.schema.json"))
    assert found == ["schema/req.schema.json"], found

    stamped = PACKAGE / "templates" / "docs" / "requirements" / "schema"
    assert not stamped.exists()


# -- AC2 — a stamped project needs no schema of its own -----------------------


def test_stamped_project_has_no_schema_dir_and_lints(tmp_path):
    """``steward new`` produces a project with no ``docs/requirements/schema/`` that still
    lints with no schema problems.

    This is the criterion with teeth: it drives the real stamper end-to-end and would fail
    if the deleted copy had been load-bearing for a fresh project. It passes because
    ``lint`` validates against the *packaged* schema regardless of the project it runs in —
    which is exactly why the stamped copy could rot unnoticed.
    """
    target = tmp_path / "consumer"
    result = CliRunner().invoke(main, ["new", str(target)])
    assert result.exit_code == 0, result.output

    assert not (target / "docs" / "requirements" / "schema").exists()
    # the rest of the requirements tree is untouched by the deletion
    assert (target / "docs" / "requirements" / "REQ-001.md").exists()
    assert (target / "docs" / "requirements" / "_templates" / "req.md").exists()

    problems = lint(load_config(target))
    schema_problems = [p for p in problems if "schema:" in p]
    assert schema_problems == [], schema_problems


# -- AC3 — the invariant is engine-dev doctrine, and stays out of the ship ----


def test_claude_md_records_the_one_file_invariant():
    """DevSteward's own CLAUDE.md carries the one-artifact-one-file invariant, and no
    shipped artifact does.

    The boundary is pinned in both directions on purpose (REQ-096 decision 3): the rule
    governs *developing* DevSteward, and the bundled skills are inode-shared with their
    templates, so a rule added to a shipped surface would ship to every consumer.
    """
    own = " ".join((REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8").split())
    assert "One artifact, one file" in own
    assert "inode-shared" in own and "symlink" in own
    assert "REQ-096" in own

    shipped = [
        PACKAGE / "templates" / "CLAUDE.md.tmpl",
        PACKAGE / "templates" / "STEWARD.md",
        *sorted((PACKAGE / "handbook").glob("*.qmd")),
        *sorted((PACKAGE / "templates" / ".claude" / "skills").rglob("SKILL.md")),
    ]
    for path in shipped:
        text = " ".join(path.read_text(encoding="utf-8").split())
        assert "One artifact, one file" not in text, path.name
