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


def test_cycle_detected(tmp_path):
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="open", depends_on=["REQ-002"])
    write_req(req_dir, "REQ-002", status="open", depends_on=["REQ-001"])
    write_index(req_dir, [("REQ-001", "a", "OPEN", "REQ-002"),
                          ("REQ-002", "b", "OPEN", "REQ-001")])
    problems = lint(_cfg(tmp_path))
    assert any("cycle" in p for p in problems)
