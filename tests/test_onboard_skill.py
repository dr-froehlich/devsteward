"""REQ-024 — the operator ``onboard`` skill: orchestrate migrating an existing project
under the engine.

A skill's guarantee is its documented procedure and the existence of the tools it names —
so the honest test is a content assertion plus a tool-availability check (the same posture
as REQ-021 Decision 5 / REQ-009), not an end-to-end pytest that re-migrates a project. The
live memzy retrofit is its own proof REQ (REQ-062).

``onboard`` is an *operator* skill that migrates *external* projects, so — unlike
intake/advance/bootstrap — it lives only in DevSteward's own ``.claude/skills/`` and is
deliberately absent from ``devsteward/templates/`` (Decision 2): a stamped consumer is
already onboarded and never runs it.
"""

from __future__ import annotations

from pathlib import Path

from devsteward.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = _REPO_ROOT / ".claude" / "skills" / "onboard" / "SKILL.md"


def _md() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_onboard_documents_pipeline_in_order():
    """AC1 — the skill exists with frontmatter and documents the four pipeline steps
    (convert → seed → stamp → reconcile) in order."""
    md = _md()
    assert md.startswith("---\n")
    head = md.split("---", 2)[1]
    assert "name:" in head and "onboard" in head
    assert "description:" in head

    low = md.lower()
    steps = ["convert the req corpus", "seed the ledger", "stamp the scaffold",
             "reconcile claude.md"]
    positions = [low.find(s) for s in steps]
    assert all(p != -1 for p in positions), f"all four pipeline steps present: {positions}"
    assert positions == sorted(positions), f"pipeline steps must appear in order: {positions}"


def test_onboard_tools_exist():
    """AC2 — the skill names the real tools it orchestrates and they exist:
    convert_reqs.py is present and ``steward seed-ledger`` is a registered subcommand."""
    md = _md()
    assert "convert_reqs.py" in md
    assert "seed-ledger" in md

    assert (_REPO_ROOT / "scripts" / "convert_reqs.py").exists(), \
        "the converter the skill orchestrates must exist"
    assert "seed-ledger" in main.commands, \
        "seed-ledger must be a registered steward subcommand"


def test_onboard_documents_verification_gates():
    """AC3 — a verification gate after each mutating step (steward lint after convert,
    steward status after seed) and a hard stop on a red gate."""
    md = _md()
    low = md.lower()

    # lint gates the conversion, status gates the seed — and lint comes first.
    assert "steward lint" in md and "steward status" in md
    assert low.index("steward lint") < low.index("steward status")

    # the skill stops, never proceeds, on a red gate.
    assert "red" in low and "gate" in low
    assert "stop" in low


def test_onboard_merge_and_scope():
    """AC4 — merge-not-overwrite for an existing .claude/ and CLAUDE.md, and
    scenarios/ROADMAP marked out of scope."""
    md = _md()
    low = md.lower()

    assert "merge" in low and "overwrite" in low
    assert ".claude/" in md and "claude.md" in low

    assert "out of scope" in low
    assert "scenario" in low and "roadmap" in low


def test_onboard_documents_park():
    """AC5 — the park-and-surface contract (honours DEVSTEWARD_UNATTENDED)."""
    md = _md()
    assert "DEVSTEWARD_UNATTENDED" in md
    assert "park" in md.lower()
