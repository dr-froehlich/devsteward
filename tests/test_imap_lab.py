"""REQ-031 — the consumer-owned-lab pattern is documented in the handbook (AC1).

The lab itself lives in its home repo, FlowSteward (its REQ-008): DevSteward ships no
domain fixtures. REQ-031's AC2 graded captured evidence through that lab's own offline
verify — but that is a System-Test/acceptance check, and it was wired here as a *regression*
test that could only ever **skip** in this repo (it needs another project's lab plus its
credentials). REQ-052 removed it: a regression test that can never run is not a regression
test, and FlowSteward's validation lab is not ours to drive from here (no substitute).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HANDBOOK_WORKFLOW = ROOT / "devsteward" / "handbook" / "_03-workflow.qmd"


# -- AC1: the consumer-owned lab pattern is documented -----------------------------------


def test_handbook_documents_consumer_owned_lab_pattern():
    """The handbook's workflow chapter states the lab pattern the first lab set
    (REQ-031 AC1): consumer-owned, real-system-first, self-contained, hard-failing,
    reality-derived corpus."""
    text = HANDBOOK_WORKFLOW.read_text(encoding="utf-8")
    assert "## Labs" in text
    section = text.split("## Labs", 1)[1].split("\n## ", 1)[0]
    assert "consumer repo" in section
    assert "registry-local" in section
    assert "real server" in section and "never production" in section
    assert "stdlib-only" in section and "shares no code" in section
    assert "hard failure, never a skip" in section
    assert "reality-derived" in section and "provenance" in section
