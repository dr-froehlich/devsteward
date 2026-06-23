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


def test_intake_screens_environment_bound_regression():
    """REQ-064 AC1: the skill screens every `check: regression` for a hidden-environment
    oracle and routes the fix by oracle coupling — so an AC whose green silently rides a
    DB/secret is caught at authoring time, never left a silent regression."""
    md = STAMPED.read_text(encoding="utf-8")

    # the smell is named and tied to the silent-skip failure mode.
    assert "environment-bound" in md
    assert "skip" in md and "silent" in md.lower()

    # the screening question: an oracle needing a service/secret/network absent from a
    # clean repo checkout.
    assert "secret" in md and "network" in md
    assert "clean repo checkout" in md

    # route by oracle coupling: decoupled -> reclassify artifact + declare the lab.
    assert "decoupled" in md
    assert "`artifact`" in md and "process.lab" in md

    # coupled-needs-runtime -> keep regression + record the required environment.
    assert "runtime" in md
    assert "required environment" in md
