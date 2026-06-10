"""REQ-027 AC1 — lint enforces the per-criterion ``check:`` routing key on active REQs."""

from __future__ import annotations

from devsteward.config import Config
from devsteward.lint import lint

from conftest import write_index, write_req


def _cfg(tmp_path) -> Config:
    return Config(root=tmp_path, requirements_dir="reqs",
                  index_file="reqs/REQUIREMENTS_INDEX.md")


def test_check_field_required_and_enumerated(tmp_path):
    """An active REQ needs a valid ``check:`` on every AC; drafts and terminal REQs are
    exempt (Decision 9 — same scoping as the test-id rule, no backfill of history)."""
    req_dir = tmp_path / "reqs"
    # active + classified → accepted; active + missing / out-of-enum → flagged;
    # draft + done without check: → exempt.
    write_req(req_dir, "REQ-001", status="open", check="regression")
    write_req(req_dir, "REQ-002", status="open", check=None)
    write_req(req_dir, "REQ-003", status="in-progress", check="smoke")
    write_req(req_dir, "REQ-004", status="draft", check=None)
    write_req(req_dir, "REQ-005", status="done", check=None)
    write_index(req_dir, [("REQ-001", "ok", "OPEN", "–"),
                          ("REQ-002", "missing", "OPEN", "–"),
                          ("REQ-003", "bad enum", "IN-PROGRESS", "–"),
                          ("REQ-004", "draft", "DRAFT", "–"),
                          ("REQ-005", "done", "DONE", "–")])
    problems = lint(_cfg(tmp_path))

    assert not any("REQ-001" in p and "check" in p for p in problems)
    assert any("REQ-002" in p and "no check: classification" in p for p in problems)
    assert any("REQ-003" in p and "'smoke'" in p for p in problems)
    # exempt: a draft may be incomplete, a terminal REQ is history.
    assert not any("REQ-004" in p and "check" in p for p in problems)
    assert not any("REQ-005" in p and "check" in p for p in problems)


def test_all_enum_values_accepted(tmp_path):
    """Each of the three taxonomy values passes the enum gate on an active REQ."""
    req_dir = tmp_path / "reqs"
    for i, value in enumerate(("regression", "artifact", "manual"), start=1):
        write_req(req_dir, f"REQ-00{i}", status="open", check=value)
    write_index(req_dir, [(f"REQ-00{i}", v, "OPEN", "–")
                          for i, v in enumerate(("r", "a", "m"), start=1)])
    assert not any("check" in p for p in lint(_cfg(tmp_path)))
