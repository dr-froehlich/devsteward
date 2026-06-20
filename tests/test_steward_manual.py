"""REQ-057 — the Claude-targeted `steward` black-box manual ships and is wired (AC2), and the
handbook, the manual, and the bundled skills carry the current verbs (AC3).

These are documentation-shape regression tests: a missing manual, a broken stamp, an unwired
CLAUDE.md, or a doc/skill that still presents `steward recover` as a live command must fail
the gate. They cannot certify "complete revision" or "black-box sufficiency" — that is AC4's
human oracle.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from devsteward.cli import _package_templates, main as cli_main

_REPO = Path(__file__).resolve().parent.parent


def test_claude_manual_ships_stamped_and_referenced(tmp_path):
    """AC2: the manual is in the package templates (package-data), `steward new` stamps it to
    the consumer root, and the stamped consumer CLAUDE.md references it as the steward doc."""
    # (a) present in the bundled templates (rides the existing `templates/**/*` package-data).
    assert (_package_templates() / "STEWARD.md").is_file()

    # (b) `steward new` stamps it into a fresh project root.
    target = tmp_path / "proj"
    res = CliRunner().invoke(cli_main, ["new", str(target)])
    assert res.exit_code == 0, res.output
    assert (target / "STEWARD.md").is_file()

    # (c) the stamped consumer CLAUDE.md points at it as the steward usage doc.
    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "STEWARD.md" in claude_md


def test_docs_and_skills_use_current_verbs():
    """AC3: the handbook and the manual name `repeat` and `revalidate`; the bundled skills name
    `repeat`; and none of the three presents `steward recover` as a live command."""
    handbook = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (_REPO / "devsteward" / "handbook").glob("*.qmd")
    )
    manual = (_REPO / "devsteward" / "templates" / "STEWARD.md").read_text(encoding="utf-8")
    skills = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (_REPO / "devsteward" / "templates" / ".claude" / "skills").rglob("SKILL.md")
    )

    assert "repeat" in handbook and "revalidate" in handbook
    assert "repeat" in manual and "revalidate" in manual
    assert "repeat" in skills

    for surface in (handbook, manual, skills):
        assert "steward recover" not in surface
