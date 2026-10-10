"""REQ-069 — the Develop phase delivers the validation fixtures it owes.

Both criteria are one-time `artifact` validations (REQ-069 Decision 5): each grades a copy the
System Tester captured into the evidence dir, never the live tree. The engine hands the
grading command that dir as ``DEVSTEWARD_EVIDENCE_DIR`` (REQ-075), and the develop gate
deselects both node-ids project-wide (REQ-068).

Skip-if-absent: outside a validation there is no evidence dir, so a bare ``python -m pytest``
skips these. A captured file that is missing is a red, never a skip.

`-k` selector tokens (`stamped_advance_skill`, `handbook_workflow`) are disjoint from the
module name (REQ-080's selector lesson).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

# The public contract in STEWARD.md, spelled out rather than imported: a grader of captured
# documents shares no code with the engine it validates.
EVIDENCE_ENV_VAR = "DEVSTEWARD_EVIDENCE_DIR"
_DEPLOY_BULLET = "A proof that needs a deploy belongs in"
_REQ051_BULLET = "Fixtures are committed upstream; the System Tester never improvises"


def _evidence(name: str) -> str:
    raw = os.environ.get(EVIDENCE_ENV_VAR)
    if not raw:
        pytest.skip(f"{EVIDENCE_ENV_VAR} unset: a one-time validation, graded only in validate")
    path = Path(raw) / name
    assert path.is_file(), f"the System Tester did not capture {name} into {raw}"
    return path.read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    """The text between the heading line starting with ``start`` and the next one starting
    with ``end``."""
    m = re.search(rf"^{re.escape(start)}.*?(?=^{re.escape(end)})", text, re.M | re.S)
    assert m, f"no section from {start!r} to {end!r}"
    return m.group(0)


def _bullets(section: str) -> list[str]:
    """Top-level ``- `` bullets, each with its indented continuation lines, in order."""
    bullets: list[str] = []
    for line in section.splitlines():
        if line.startswith("- "):
            bullets.append(line)
        elif bullets and line.startswith("  "):
            bullets[-1] += "\n" + line
        elif bullets and line.strip():
            bullets.append("")  # prose between bullets breaks adjacency
    return [" ".join(b.split()) for b in bullets]


def _index(bullets: list[str], needle: str) -> int:
    hits = [i for i, b in enumerate(bullets) if needle in b]
    assert len(hits) == 1, f"expected one bullet containing {needle!r}, found {len(hits)}"
    return hits[0]


def _states_the_duty(bullet: str) -> None:
    for phrase in ("`artifact`", "`manual`", "fixture", "seeded sample project",
                   "lab starting-state", "commit", "`dev`", "System Tester", "REQ-051"):
        assert phrase in bullet, f"the REQ-069 bullet does not say {phrase!r}: {bullet}"


def test_evidence_stamped_advance_skill():
    """AC1: the stamped `/advance` skill's §2 states the builder's fixture duty, next to the
    REQ-089 deploy-proof bullet."""
    skill = _evidence("advance-SKILL.md")
    bullets = _bullets(_section(skill, "## 2.", "## 3."))
    duty = _index(bullets, "REQ-069")
    _states_the_duty(bullets[duty])
    assert abs(duty - _index(bullets, _DEPLOY_BULLET)) == 1, (
        "the REQ-069 bullet is not adjacent to the REQ-089 deploy-proof bullet"
    )


def test_evidence_handbook_workflow():
    """AC2: the handbook's workflow section carries the REQ-051 prohibition and the REQ-069
    builder duty as adjacent bullets of one section."""
    handbook = _evidence("_03-workflow.qmd")
    sections = re.split(r"^## ", handbook, flags=re.M)
    home = [s for s in sections if _REQ051_BULLET in s]
    assert len(home) == 1, "the REQ-051 bullet is missing or appears in more than one section"
    bullets = _bullets(home[0])
    duty = _index(bullets, "REQ-069")
    _states_the_duty(bullets[duty])
    assert abs(duty - _index(bullets, _REQ051_BULLET)) == 1, (
        "the REQ-069 bullet is not adjacent to the REQ-051 bullet"
    )
