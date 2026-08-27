"""REQ-093 AC8 — the doctrine surfaces carry the take-up step, and the handbook is honest.

The engine can enforce that a claimed handle resolves, but it cannot enforce the rule that
actually protects the layer: **the item's acceptance criteria are authored before the
translation**. That rule lives in the `/intake` skill, so these tests guard the two ways it
silently disappears — the skill text losing it, and the stamped copy drifting away from the
repo copy so consumers get a different `/intake` than this one.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_SKILL = ROOT / ".claude" / "skills" / "intake" / "SKILL.md"
STAMPED_SKILL = ROOT / "devsteward" / "templates" / ".claude" / "skills" / "intake" / "SKILL.md"
OUTLOOK = ROOT / "devsteward" / "handbook" / "_05-outlook.qmd"
FORMAT = ROOT / "devsteward" / "handbook" / "_01-format.qmd"


def test_intake_ordering_rule_stamped_and_handbook_updated():
    """AC8 — the rule is in the skill, the two copies are one file, the handbook is current."""
    skill = REPO_SKILL.read_text(encoding="utf-8")

    # the take-up step exists and names the one stored record of take-up
    assert "Taking up backlog items" in skill
    assert "backlog_refs" in skill
    assert "steward backlog-list" in skill

    # the ordering rule — the whole point of routing intake through the backlog
    assert "before you" in skill and "design anything" in skill
    assert "get quietly bent to fit it" in skill

    # and the rule that keeps acceptance advisory: an item's criteria never become a
    # blocking AC on the REQ
    assert "backlog-deny" in skill
    assert "does **not** fail the REQ" in skill

    # one file, two paths — a stamped consumer must get exactly this `/intake`
    assert REPO_SKILL.stat().st_ino == STAMPED_SKILL.stat().st_ino, (
        "the repo skill and the stamped template are no longer one inode — an edit to one "
        "would silently leave the other behind"
    )
    assert STAMPED_SKILL.read_text(encoding="utf-8") == skill

    # the handbook documents the shipped layer …
    fmt = FORMAT.read_text(encoding="utf-8")
    assert "{#sec-backlog}" in fmt
    assert "steward backlog-add" in fmt
    assert "advisory to the REQ and blocking to" in " ".join(fmt.split())

    # … and the outlook chapter no longer presents stage one as unimplemented
    outlook = OUTLOOK.read_text(encoding="utf-8")
    assert "Nothing in this chapter is implemented" not in outlook
    assert "Stage one shipped" in outlook
    assert "@sec-backlog" in outlook
    # the two genuinely-unbuilt stages stay marked as outlook
    assert "retrospective (outlook)" in outlook
    assert "status surface (outlook)" in outlook


def test_the_stamped_intake_reaches_a_fresh_project(tmp_path):
    """AC8 — `steward new` must actually deliver the skill carrying the rule."""
    from click.testing import CliRunner

    from devsteward.cli import main

    target = tmp_path / "fresh"
    r = CliRunner().invoke(main, ["new", str(target)], catch_exceptions=False)
    assert r.exit_code == 0, r.output
    stamped = (target / ".claude" / "skills" / "intake" / "SKILL.md").read_text(encoding="utf-8")
    assert "Taking up backlog items" in stamped
    assert stamped == REPO_SKILL.read_text(encoding="utf-8")
