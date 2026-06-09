"""REQ-009 — the three bundled skills exist with frontmatter and the park contract."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = _REPO_ROOT / "devsteward" / "templates" / ".claude" / "skills"
SKILLS = ["intake", "advance", "bootstrap"]

# REQ-021 AC5: both intake SKILL.md copies — the stamped template and DevSteward's own
# dogfood copy — must instruct stripping a trailing letter before computing the next id.
INTAKE_COPIES = [
    SKILLS_DIR / "intake" / "SKILL.md",
    _REPO_ROOT / ".claude" / "skills" / "intake" / "SKILL.md",
]


@pytest.mark.parametrize("skill", SKILLS)
def test_skills_have_frontmatter(skill):
    md = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    assert md.startswith("---\n")
    head = md.split("---", 2)[1]
    assert "name:" in head
    assert "description:" in head


@pytest.mark.parametrize("skill", SKILLS)
def test_skills_document_park(skill):
    md = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "DEVSTEWARD_UNATTENDED" in md
    assert "park" in md.lower()


@pytest.mark.parametrize("path", INTAKE_COPIES, ids=["template", "dogfood"])
def test_intake_next_id_strips_letter_suffix(path):
    """REQ-021 AC5 — next-id allocation is a skill instruction, not code: both intake
    copies must tell the model to strip a trailing letter so a lettered id (REQ-028p) is
    read as 028, never skewing the max."""
    md = path.read_text(encoding="utf-8").lower()
    assert "strip" in md and "trailing letter" in md
    assert "next free id" in md
