"""REQ-031 — consuming the first lab (FlowSteward's IMAP lab) through the System-Test
phase: the documented consumer-owned-lab pattern (AC1) and the artifact gate that grades
captured evidence through the lab's own offline verify (AC2's engine-run command).

The lab itself lives in its home repo, FlowSteward (its REQ-008): DevSteward ships no
domain fixtures. The seam is ``DEVSTEWARD_LAB_IMAP_ENV`` — the path to the dotenv file
carrying the ``FLOWSTEWARD_IMAP_*`` credentials inside the FlowSteward checkout; the
lab tool is ``<checkout>/labs/imap/lab.py``, stdlib-only and runnable by any
interpreter, including ours.

AC2's test **skips** when no evidence has been captured (clean checkouts keep the
develop full-suite gate green; the validate gate counts a skip as red — the
missing-artifact semantics). Once evidence exists, a missing or unreachable lab is a
**failure**, not a skip: a validation is being graded, and a lab that cannot come up is
a hard red (REQ-030 Decision 3).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_ROOT = ROOT / ".devsteward" / "evidence" / "REQ-031"
HANDBOOK_WORKFLOW = ROOT / "devsteward" / "handbook" / "_03-workflow.qmd"
ENV_POINTER = "DEVSTEWARD_LAB_IMAP_ENV"


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


# -- AC2: the artifact gate (engine-run at validate) --------------------------------------


def _latest_evidence_fetch() -> Path | None:
    if not EVIDENCE_ROOT.is_dir():
        return None
    for run in sorted(EVIDENCE_ROOT.iterdir(), reverse=True):
        candidate = run / "fetched-seed.eml"
        if candidate.is_file():
            return candidate
    return None


def _lab_tool() -> Path:
    """Resolve FlowSteward's lab tool through the env seam — a hard red when evidence
    is being graded and the lab cannot be located."""
    env_file = os.environ.get(ENV_POINTER, "")
    assert env_file, (
        f"{ENV_POINTER} is not set but evidence exists — point it at the FlowSteward "
        f"checkout's .env so the lab can grade the capture (a lab skip is a hard red)"
    )
    lab_py = Path(env_file).resolve().parent / "labs" / "imap" / "lab.py"
    assert lab_py.is_file(), f"lab tool not found at {lab_py} — is the lab landed in FlowSteward?"
    return lab_py


def test_evidence_artifact_matches_golden():
    """The newest captured live-socket fetch passes the lab's own offline golden verify
    (REQ-031 AC2). Skips when no evidence exists yet, or when the lab seam is absent
    (develop full-suite: skips are green; validate gate: skip ≠ green — still red)."""
    fetched = _latest_evidence_fetch()
    if fetched is None:
        pytest.skip("no evidence captured under .devsteward/evidence/REQ-031/ yet")
    if not os.environ.get(ENV_POINTER):
        pytest.skip(
            f"{ENV_POINTER} not set — point it at the FlowSteward checkout's .env "
            f"to grade the captured evidence; a skip is red in the validate gate (skip ≠ green)"
        )
    lab = _lab_tool()  # hard-fails if seam is set but the lab tool file is missing
    proc = subprocess.run(
        [sys.executable, str(lab), "verify", "--against", str(fetched)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"lab verify red: {proc.stderr}{proc.stdout}"
    assert "verify OK" in proc.stdout
