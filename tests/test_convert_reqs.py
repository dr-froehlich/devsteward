"""REQ-010 — the memzy dialect converter.

Drives the importable functions of ``scripts/convert_reqs.py`` (on ``sys.path`` via the
conftest shim) against captured memzy fixtures. The converter is an archivist: it preserves
every verdict and all prose, injects only what the schema requires, and is idempotent.
"""

from __future__ import annotations

from pathlib import Path

import convert_reqs as cv
from devsteward.config import Config
from devsteward.lint import _index_rows, lint
from devsteward.profiles.req.reqfile import parse_req

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "memzy_reqs"


def _convert_to(tmp_path: Path, name: str):
    """Convert one fixture REQ into ``tmp_path`` and return its parsed ReqFile."""
    out = tmp_path / name
    out.write_text(cv.convert_req_text((FIXTURES / name).read_text(encoding="utf-8")),
                   encoding="utf-8")
    return parse_req(out)


# --- AC1 -------------------------------------------------------------------------------


def test_injects_kind_preserves_fields(tmp_path):
    req = _convert_to(tmp_path, "REQ-002.md")
    fm = req.frontmatter
    # kind is injected, schema-valid, and inferred (a plain feature here).
    assert fm["kind"] == "feature"
    # everything else is carried through unchanged.
    assert req.status == "done"
    assert req.depends_on == ["REQ-001"]
    assert fm["added"] == "2026-05-30"
    assert fm["completed"] == "2026-05-31"
    assert fm["tags"] == ["bootstrap", "django", "postgres", "docker", "infrastructure"]
    # the north star is inferred as a spec, not a feature.
    assert _convert_to(tmp_path, "REQ-001.md").frontmatter["kind"] == "spec"


# --- AC2 -------------------------------------------------------------------------------


def test_transcodes_acceptance_verdicts(tmp_path):
    # [x] → passed, and the block is parseable by the REQ profile parser.
    done = _convert_to(tmp_path, "REQ-002.md")
    assert [ac.id for ac in done.acceptance] == ["AC1", "AC2", "AC3"]
    assert all(ac.status == "passed" for ac in done.acceptance)
    # a single-line criterion is preserved verbatim.
    assert done.acceptance[2].text == (
        "Postgres data persists across `docker compose down` && `docker compose up`."
    )

    # [ ] → pending, across both checkbox groups of the north star (3 + 2 criteria).
    draft = _convert_to(tmp_path, "REQ-001.md")
    assert [ac.id for ac in draft.acceptance] == ["AC1", "AC2", "AC3", "AC4", "AC5"]
    assert all(ac.status == "pending" for ac in draft.acceptance)


# --- AC3 -------------------------------------------------------------------------------


def test_test_id_is_best_effort(tmp_path):
    req = _convert_to(tmp_path, "REQ-003.md")
    # an embedded test_* name is copied into test:
    assert req.acceptance[0].test == "test_entities_and_owner_fks"
    assert req.acceptance[1].test == "test_no_pyfsrs"
    # a criterion with no embedded test gets an empty test, with the verdict untouched.
    assert req.acceptance[2].test == ""
    assert req.acceptance[2].status == "passed"
    # REQ-002 mentions `core/tests.py` (not a test_* name) → no fabricated id.
    done = _convert_to(tmp_path, "REQ-002.md")
    assert all(ac.test == "" for ac in done.acceptance)


# --- AC4 -------------------------------------------------------------------------------


def test_normalizes_supersedes(tmp_path):
    # the function itself, on the three shapes.
    assert cv.normalize_supersedes([]) is None
    assert cv.normalize_supersedes(["REQ-018"]) == "REQ-018"
    assert cv.normalize_supersedes(None) is None

    # [] → null on the north star; [REQ-018] → "REQ-018" on its reverser.
    assert _convert_to(tmp_path, "REQ-001.md").frontmatter["supersedes"] is None
    assert _convert_to(tmp_path, "REQ-020.md").frontmatter["supersedes"] == "REQ-018"
    # the non-schema superseded_by key is dropped entirely.
    req18 = _convert_to(tmp_path, "REQ-018.md")
    assert "superseded_by" not in req18.frontmatter
    assert "superseded_by" not in (tmp_path / "REQ-018.md").read_text(encoding="utf-8")


# --- AC5 -------------------------------------------------------------------------------


def test_index_rows_parseable_and_synced(tmp_path):
    reqs = cv.convert_corpus(FIXTURES, tmp_path)
    rows = _index_rows(tmp_path / "REQUIREMENTS_INDEX.md")
    assert set(rows) == {r.id for r in reqs}
    for r in reqs:
        assert rows[r.id] == r.status.lower()


# --- AC6 -------------------------------------------------------------------------------


def test_idempotent_and_preserves_prose(tmp_path):
    raw = (FIXTURES / "REQ-001.md").read_text(encoding="utf-8")
    once = cv.convert_req_text(raw)
    twice = cv.convert_req_text(once)
    assert once == twice  # a second run is a no-op

    # prose sections are spliced through byte-for-byte.
    assert "## Context\n\nMemzy is a multi-student web app" in once
    assert (
        "| D1 | Backend stack | **Django 5.x (Python)** | "
        "Built-in auth, admin as a day-one teacher console. |"
    ) in once
    assert "**Why Django over Flask-Security-Too**" in once


# --- AC8 -------------------------------------------------------------------------------


def test_memzy_fixture_corpus_lints_clean(tmp_path):
    reqs = cv.convert_corpus(FIXTURES, tmp_path)
    # REQ-021: the corpus carries a lettered-id fixture (REQ-028p) — the umbrella-split id
    # converts and round-trips through the schema like any other.
    assert "REQ-028p" in {r.id for r in reqs}
    cfg = Config(root=tmp_path, requirements_dir=".",
                 index_file="REQUIREMENTS_INDEX.md")
    assert lint(cfg) == []
