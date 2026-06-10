"""REQ-027 AC2 — the stamped ``/intake`` skill seeds the acceptance house style.

The intake interview is the one human-in-the-loop seed before headless work; these tests
pin the *instructions* (system-level acceptance, ``check:`` classification, the three
process declarations, honest deferral) into the stamped skill so a regeneration cannot
silently drop the house style. The dogfood copy is the same file by symlink
(``.claude/skills`` → ``devsteward/templates/.claude/skills``); the identity check below
guards against the link being replaced by a diverging real copy.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
STAMPED = _REPO_ROOT / "devsteward" / "templates" / ".claude" / "skills" / "intake" / "SKILL.md"
DOGFOOD = _REPO_ROOT / ".claude" / "skills" / "intake" / "SKILL.md"


def test_intake_seeds_taxonomy_and_concept():
    md = STAMPED.read_text(encoding="utf-8")

    # system-level, measurable acceptance is interrogated, with the oracle as the
    # screening question.
    assert "system level" in md or "system-level" in md
    assert "captured" in md and "deliverable" in md
    assert "oracle" in md
    assert "coupled" in md

    # every criterion is classified with the check: routing key (full enum present).
    assert "`check:`" in md
    for value in ("regression", "artifact", "manual"):
        assert value in md

    # the three process declarations are decided while the human is present.
    assert "process:" in md or "`process:`" in md
    assert "concept" in md
    assert "lab" in md
    assert "fused" in md and "split" in md
    # fused is the default; split is the declared exception for risky REQs.
    assert "default" in md

    # honest deferral: a missing lab names its follow-on REQ, never a downgrade.
    assert "never downgrade" in md

    # emit contract: every criterion carries id + test + check.
    assert "`id`, a `test:`, and a `check:`" in md


def test_intake_copies_are_one_file():
    """The dogfood copy must stay the stamped copy (symlink today, byte-equal always)."""
    assert DOGFOOD.read_text(encoding="utf-8") == STAMPED.read_text(encoding="utf-8")
