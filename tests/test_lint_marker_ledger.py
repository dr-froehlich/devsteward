"""REQ-028 AC5 — `steward lint` reconciles the REQ marker against the ledger.

FlowSteward REQ-003a's frontmatter was hand-edited to ``status: done`` while the ledger's
terminal land record for it was ``failed``. Lint checked frontmatter↔index agreement but
never the ledger, so the false ``done`` was invisible. Now a ledger-*tracked* REQ marked
``done`` whose ``land`` step is not ``DONE`` (it is failed, or absent under a tracked REQ)
is a hard lint error — the ledger is the cursor of record and the marker must not outrun it.
A ``done`` REQ with no ledger footprint (pre-ledger or imported) stays outside its purview.
"""

from __future__ import annotations

from devsteward.config import Config
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.lint import lint

from conftest import write_index, write_req


def _cfg(root):
    return Config(root=root, requirements_dir="reqs",
                  index_file="reqs/REQUIREMENTS_INDEX.md")


def test_lint_fails_on_done_contradicted_by_ledger(tmp_path):
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="open")
    write_req(req_dir, "REQ-002", status="done", depends_on=["REQ-001"])
    write_index(req_dir, [("REQ-001", "north", "OPEN", "–"),
                          ("REQ-002", "two", "DONE", "REQ-001")])

    # The engine drove REQ-002 but its land FAILED — a `done` marker the ledger contradicts.
    ledger = Ledger.init(tmp_path, profile="req")
    ledger.set_status("REQ-002:design", StepStatus.DONE)
    ledger.set_status("REQ-002:build", StepStatus.DONE)
    ledger.set_status("REQ-002:land", StepStatus.FAILED)
    ledger.save()

    problems = lint(_cfg(tmp_path))
    assert any("REQ-002" in p and "ledger" in p for p in problems), problems
    # REQ-001 (open) and the absence of a ledger footprint are not flagged for it.
    assert not any("REQ-001" in p and "ledger" in p for p in problems)

    # An absent land under a tracked REQ is the same contradiction.
    ledger2 = Ledger.init(tmp_path, profile="req")
    ledger2.set_status("REQ-002:design", StepStatus.DONE)
    ledger2.set_status("REQ-002:build", StepStatus.DONE)  # land never recorded
    ledger2.save()
    assert any("REQ-002" in p and "absent" in p for p in lint(_cfg(tmp_path)))

    # Agreement clears it: a green land matches the `done` marker.
    ledger2.set_status("REQ-002:land", StepStatus.DONE)
    ledger2.save()
    assert not any("contradicts the marker" in p for p in lint(_cfg(tmp_path)))


def test_lint_leaves_untracked_done_alone(tmp_path):
    """A `done` REQ the engine never drove (no ledger footprint) is outside the ledger's
    purview — flagging it would break a green dogfood lint over imported/pre-ledger dones."""
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="done")
    write_index(req_dir, [("REQ-001", "north", "DONE", "–")])
    Ledger.init(tmp_path, profile="req")  # empty steps overlay
    assert not any("ledger" in p for p in lint(_cfg(tmp_path)))
