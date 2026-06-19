"""REQ-027 AC5 — the optional ``process:`` frontmatter block (intake-time declarations)."""

from __future__ import annotations

import jsonschema

from devsteward.config import Config
from devsteward.lint import _schema, lint
from devsteward.profiles.req.reqfile import parse_req

from conftest import write_index, write_req


def _cfg(tmp_path) -> Config:
    return Config(root=tmp_path, requirements_dir="reqs",
                  index_file="reqs/REQUIREMENTS_INDEX.md")


def test_process_block_schema_and_lab_resolution(tmp_path):
    """A full valid block passes schema and is echoed by ``ReqFile.process``; an absent
    block yields the defaults; an out-of-enum ``develop:`` fails schema; an unresolved
    ``lab:`` reference is a lint problem (Decision 10)."""
    req_dir = tmp_path / "reqs"

    # (a) full valid block → schema-clean, property echoes it.
    write_req(req_dir, "REQ-001", status="open",
              process={"develop": "split", "concept": True, "lab": ["REQ-002"]})
    # (b) no block → schema-clean, property returns the defaults.
    write_req(req_dir, "REQ-002", status="done")
    write_index(req_dir, [("REQ-001", "full block", "OPEN", "–"),
                          ("REQ-002", "lab owner", "DONE", "–")])
    assert lint(_cfg(tmp_path)) == []

    declared = parse_req(req_dir / "REQ-001.md")
    assert declared.process == {
        "develop": "split", "concept": True, "lab": ["REQ-002"], "fixtures": []
    }
    defaulted = parse_req(req_dir / "REQ-002.md")
    assert defaulted.process == {
        "develop": "fused", "concept": False, "lab": [], "fixtures": []
    }

    # (c) out-of-enum develop → schema problem (lint rule 1).
    write_req(req_dir, "REQ-003", status="open", process={"develop": "turbo"})
    write_index(req_dir, [("REQ-001", "full block", "OPEN", "–"),
                          ("REQ-002", "lab owner", "DONE", "–"),
                          ("REQ-003", "bad enum", "OPEN", "–")])
    problems = lint(_cfg(tmp_path))
    assert any("REQ-003" in p and "schema" in p and "develop" in p for p in problems)

    # (d) lab reference that resolves to no REQ → lint problem (like depends_on).
    write_req(req_dir, "REQ-003", status="open", process={"lab": ["REQ-099"]})
    problems = lint(_cfg(tmp_path))
    assert any("REQ-003" in p and "process.lab 'REQ-099'" in p and "resolve" in p
               for p in problems)


def test_process_block_partial_merges_over_defaults(tmp_path):
    """A partial block passes schema and keeps the unstated defaults — the accessor
    REQ-029/030 read."""
    validator = jsonschema.Draft202012Validator(_schema())
    fm = {"id": "REQ-001", "title": "t", "status": "open", "kind": "feature",
          "added": "2026-06-10", "depends_on": [], "process": {"develop": "split"}}
    assert list(validator.iter_errors(fm)) == []

    write_req(tmp_path, "REQ-001", process={"develop": "split"})
    req = parse_req(tmp_path / "REQ-001.md")
    assert req.process == {
        "develop": "split", "concept": False, "lab": [], "fixtures": []
    }
