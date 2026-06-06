"""REQ-009 — the three bundled skills exist with frontmatter and the park contract."""

from __future__ import annotations

from pathlib import Path

import pytest

SKILLS_DIR = (
    Path(__file__).resolve().parents[1]
    / "devsteward" / "templates" / ".claude" / "skills"
)
SKILLS = ["intake", "advance", "bootstrap"]


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
