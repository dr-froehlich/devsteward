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
    """Each taxonomy value (incl. REQ-068 ``live``) passes the enum gate on an active REQ."""
    req_dir = tmp_path / "reqs"
    for i, value in enumerate(("regression", "live", "artifact", "manual"), start=1):
        write_req(req_dir, f"REQ-00{i}", status="open", check=value)
    write_index(req_dir, [(f"REQ-00{i}", v, "OPEN", "–")
                          for i, v in enumerate(("r", "l", "a", "m"), start=1)])
    assert not any("check" in p for p in lint(_cfg(tmp_path)))


def test_check_live_accepted_and_enumerated(tmp_path):
    """REQ-068 AC1: lint accepts ``check: live`` on an active REQ (the enum is now
    {regression, live, artifact, manual}) and still rejects an out-of-enum value; a draft
    fixture is unaffected (REQ-027 Decision 9 scope — drafts/terminals exempt)."""
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="open", check="live")       # the new value: accepted
    write_req(req_dir, "REQ-002", status="open", check="smoke")      # still rejected
    write_req(req_dir, "REQ-003", status="draft", check="live")      # draft: exempt anyway
    write_index(req_dir, [("REQ-001", "live ok", "OPEN", "–"),
                          ("REQ-002", "bad enum", "OPEN", "–"),
                          ("REQ-003", "draft", "DRAFT", "–")])
    problems = lint(_cfg(tmp_path))

    assert not any("REQ-001" in p and "check" in p for p in problems)
    assert any("REQ-002" in p and "'smoke'" in p for p in problems)
    # the rejection message advertises the four-value enum, live among them.
    assert any("live" in p for p in problems if "REQ-002" in p)
    assert not any("REQ-003" in p and "check" in p for p in problems)
