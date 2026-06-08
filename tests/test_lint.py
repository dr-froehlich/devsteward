"""REQ-002 AC2 — the linter flags schema, deps, cycles, and index drift."""

from __future__ import annotations

from devsteward.config import Config
from devsteward.lint import lint

from conftest import write_index, write_req


def _cfg(tmp_path) -> Config:
    return Config(root=tmp_path, requirements_dir="reqs",
                  index_file="reqs/REQUIREMENTS_INDEX.md")


def test_clean_project_lints_green(tmp_path):
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="open")
    write_req(req_dir, "REQ-002", status="done", depends_on=["REQ-001"])
    write_index(req_dir, [("REQ-001", "north", "OPEN", "–"),
                          ("REQ-002", "two", "DONE", "REQ-001")])
    assert lint(_cfg(tmp_path)) == []


def test_unresolved_dependency_flagged(tmp_path):
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="open", depends_on=["REQ-099"])
    write_index(req_dir, [("REQ-001", "north", "OPEN", "REQ-099")])
    problems = lint(_cfg(tmp_path))
    assert any("REQ-099" in p and "resolve" in p for p in problems)


def test_status_drift_flagged(tmp_path):
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="done")
    write_index(req_dir, [("REQ-001", "north", "OPEN", "–")])  # index says OPEN
    problems = lint(_cfg(tmp_path))
    assert any("index status" in p for p in problems)


def test_missing_index_row_flagged(tmp_path):
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="open")
    write_index(req_dir, [])  # no rows
    problems = lint(_cfg(tmp_path))
    assert any("missing a row" in p for p in problems)


def test_acceptance_without_test_flagged(tmp_path):
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="open", acceptance=False)
    write_index(req_dir, [("REQ-001", "north", "OPEN", "–")])
    problems = lint(_cfg(tmp_path))
    assert any("no acceptance" in p for p in problems)


def _write_testless_req(req_dir, rid, status):
    """A schema-valid REQ whose single acceptance criterion has an empty ``test:``."""
    req_dir.mkdir(parents=True, exist_ok=True)
    text = (
        "---\n"
        f"id: {rid}\n"
        f'title: "{rid}"\n'
        f"status: {status}\n"
        "kind: feature\n"
        "added: 2026-06-06\n"
        "completed: null\n"
        "verified_by: null\n"
        "depends_on: []\n"
        "concept_refs: []\n"
        "scenario_refs: []\n"
        "supersedes: null\n"
        "tags: []\n"
        "---\n\n"
        "## Requirement\n\nDo it.\n\n"
        "```yaml acceptance\n"
        "- id: AC1\n"
        '  text: "works"\n'
        '  test: ""\n'
        "  status: passed\n"
        "```\n"
    )
    (req_dir / f"{rid}.md").write_text(text, encoding="utf-8")


def test_test_id_required_only_for_active(tmp_path):
    # REQ-010: a terminal imported REQ with test-less criteria lints clean...
    done_dir = tmp_path / "done"
    _write_testless_req(done_dir, "REQ-001", "done")
    write_index(done_dir, [("REQ-001", "REQ-001", "DONE", "–")])
    cfg = Config(root=done_dir, requirements_dir="", index_file="REQUIREMENTS_INDEX.md")
    assert not any("test id" in p for p in lint(cfg))

    # ...while an active REQ with a test-less criterion still fails.
    open_dir = tmp_path / "open"
    _write_testless_req(open_dir, "REQ-001", "open")
    write_index(open_dir, [("REQ-001", "REQ-001", "OPEN", "–")])
    cfg = Config(root=open_dir, requirements_dir="", index_file="REQUIREMENTS_INDEX.md")
    assert any("test id" in p for p in lint(cfg))


def test_cycle_detected(tmp_path):
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="open", depends_on=["REQ-002"])
    write_req(req_dir, "REQ-002", status="open", depends_on=["REQ-001"])
    write_index(req_dir, [("REQ-001", "a", "OPEN", "REQ-002"),
                          ("REQ-002", "b", "OPEN", "REQ-001")])
    problems = lint(_cfg(tmp_path))
    assert any("cycle" in p for p in problems)
