"""REQ-017 — the legacy prose-header REQ converter.

Drives ``scripts/convert_reqs_prose.py`` (on ``sys.path`` via the conftest shim) against all
12 captured **THermo** REQs. Two oracles, because they disconfirm different failures
(REQ-017 Decision 8): ``steward lint`` is decoupled — it predates this converter and knows
nothing about it — but only proves the output is *schema-valid*; the committed goldens prove
*fidelity*, that 122 lines of REQ-012's prose survived byte-for-byte, but are authored
alongside the converter and can only confirm what the author already believed.

Every test is hermetic: the fixtures are captured files and no THermo checkout is read.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import convert_reqs as cv
import convert_reqs_prose as cvp
import pytest
from devsteward.config import Config
from devsteward.lint import lint
from devsteward.profiles.req.index import read_statuses as _index_rows
from devsteward.profiles.req.reqfile import parse_req

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "thermo_reqs"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "thermo_reqs_golden"

# The prose dialect's eight field bullets, normalized.
_FIELDS = {
    "status", "added", "completed", "verified_by", "depends_on",
    "description", "acceptance_criteria", "notes",
}


def _seed_index(dst: Path) -> Path:
    """Put THermo's real index in place so the conversion *splices* rather than rebuilds."""
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "REQUIREMENTS_INDEX.md", dst / "REQUIREMENTS_INDEX.md")
    return dst


def _convert_one(tmp_path: Path, name: str):
    out = tmp_path / name
    out.write_text(
        cvp.convert_prose_text((FIXTURES / name).read_text(encoding="utf-8"), name=name),
        encoding="utf-8",
    )
    return parse_req(out)


# --- AC1 -------------------------------------------------------------------------------


def test_parses_headers_and_ignores_body_bullets(tmp_path):
    raw = (FIXTURES / "REQ-004.md").read_text(encoding="utf-8")
    rid, title, segments = cvp.split_fields(raw, name="REQ-004.md")

    assert rid == "REQ-004"
    assert title == "WhoAmI device identity"
    assert set(segments) == _FIELDS

    # The Description body carries bullets that look exactly like fields at column 0. They
    # are prose — only the eight known names are fields — so they stay in the segment.
    assert "mac_address" not in segments
    assert "hostname" not in segments
    assert "- **MAC address**: Replace `WiFi.macAddress()`" in segments["description"]
    assert "- **Base32 encoding**: Pure C++ logic" in segments["description"]

    # A backticked look-alike in another file must survive the same way.
    _, _, six = cvp.split_fields(
        (FIXTURES / "REQ-006.md").read_text(encoding="utf-8"), name="REQ-006.md"
    )
    assert "`StoreConfigToFile()`" in six["description"]

    # The scalars land in frontmatter, carried verbatim.
    req = _convert_one(tmp_path, "REQ-004.md")
    assert req.status == "done"
    assert req.frontmatter["added"] == "2026-04-07"
    assert req.frontmatter["completed"] == "2026-04-07"
    assert req.frontmatter["verified_by"] == "idf.py build clean 2026-04-07"
    assert req.depends_on == []  # the source's en-dash placeholder

    # …and a real dependency list is split into ids.
    assert _convert_one(tmp_path, "REQ-009.md").depends_on == ["REQ-008", "REQ-004", "REQ-006"]


# --- AC2 -------------------------------------------------------------------------------


def test_status_vocabulary_and_unknown_token_aborts(tmp_path):
    assert cvp.coerce_status("DONE", name="x") == "done"
    assert cvp.coerce_status("OPEN", name="x") == "open"
    assert cvp.coerce_status("IN_PROGRESS", name="x") == "in-progress"
    # separator-insensitive, so `in progress` / `in-progress` land on the same entry
    assert cvp.coerce_status("in progress", name="x") == "in-progress"

    # placeholders → null / []
    assert cvp.coerce_date("–", field="completed", name="x") is None
    assert cvp.coerce_deps("–", name="x") == []
    # …but a placeholder-prefixed *sentence* is real text, not a placeholder (REQ-011's
    # "– (code-only smoke tests pass; …)"), so it is kept rather than dropped.
    assert cvp.coerce_text("– (code-only smoke tests pass)") == "– (code-only smoke tests pass)"

    # An unrecognized token is an abort naming the file and the token — never a guess.
    with pytest.raises(cvp.ProseParseError) as exc:
        cvp.coerce_status("WONTFIX", name="REQ-042.md")
    assert "REQ-042.md" in str(exc.value) and "WONTFIX" in str(exc.value)

    # …and it takes the whole corpus down without writing anything.
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(FIXTURES / "REQ-004.md", src / "REQ-004.md")
    (src / "REQ-005.md").write_text(
        (FIXTURES / "REQ-005.md").read_text(encoding="utf-8").replace(
            "- **Status:** DONE", "- **Status:** WONTFIX"
        ),
        encoding="utf-8",
    )
    dst = tmp_path / "dst"
    with pytest.raises(cvp.ProseParseError):
        cvp.convert_corpus_prose(src, dst)
    assert not dst.exists()


# --- AC3 -------------------------------------------------------------------------------


def test_acceptance_transcodes_via_shared_core(tmp_path):
    req = _convert_one(tmp_path, "REQ-004.md")
    assert [ac.id for ac in req.acceptance] == [f"AC{i}" for i in range(1, 10)]
    assert all(ac.status == "passed" for ac in req.acceptance)  # every source box was [x]
    assert req.acceptance[0].text == (
        "`WhoAmI` class compiles under ESP-IDF with no Arduino dependencies"
    )

    # An all-unchecked source keeps every verdict pending — no verdict is re-adjudicated.
    twelve = _convert_one(tmp_path, "REQ-012.md")
    assert len(twelve.acceptance) == 13
    assert all(ac.status == "pending" for ac in twelve.acceptance)

    # The block is REQ-010's transcoder output, not a reimplementation (Decision 3): feeding
    # the raw segment through the shared core reproduces it exactly.
    _, _, segments = cvp.split_fields(
        (FIXTURES / "REQ-004.md").read_text(encoding="utf-8"), name="REQ-004.md"
    )
    import textwrap

    expected = cv.transcode_acceptance_block(
        cv.parse_acceptance_checkboxes(textwrap.dedent(segments["acceptance_criteria"]))
    )
    assert expected in (tmp_path / "REQ-004.md").read_text(encoding="utf-8")


# --- AC4 -------------------------------------------------------------------------------


def test_body_sections_map_and_prose_rides_verbatim(tmp_path):
    out = (tmp_path / "REQ-004.md")
    _convert_one(tmp_path, "REQ-004.md")
    text = out.read_text(encoding="utf-8")

    # the header is preserved (deliberately), then the sections in order
    assert text.index("### REQ-004: WhoAmI device identity") < text.index("## Requirement")
    assert text.index("## Requirement") < text.index("## Acceptance criteria")
    assert text.index("## Acceptance criteria") < text.index("## Notes")

    # sub-headings ride through
    assert "#### Changes from legacy" in text
    assert "#### Replaces global `deviceId`" in text
    assert "#### Location" in text

    # sections with no source field are not invented
    assert "## Context" not in text
    assert "## Decisions" not in text

    # REQ-012's tables and fenced JSON survive intact
    twelve = tmp_path / "REQ-012.md"
    _convert_one(tmp_path, "REQ-012.md")
    twelve_text = twelve.read_text(encoding="utf-8")
    assert "| `currentTarget` | 18.0, 20.5, 22.0 |" in twelve_text
    assert '"thermotest_version": "0.1.0"' in twelve_text
    assert "```json" in twelve_text

    # the sweep: every non-field prose line of every source REQ appears in its output
    for path in sorted(FIXTURES.glob("REQ-*.md")):
        if path.stem == "REQ-xxx":
            continue
        converted = cvp.convert_prose_text(path.read_text(encoding="utf-8"), name=path.name)
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if (
                not stripped
                or stripped.startswith("- **")
                or stripped.startswith("- [")
                or stripped.startswith("###")
            ):
                continue  # a field bullet, a checkbox or the header — restructured by design
            assert stripped in converted, f"{path.name}: lost prose line {stripped[:60]!r}"


# --- AC5 -------------------------------------------------------------------------------


def test_header_title_wins_and_conflict_is_reported(tmp_path):
    dst = _seed_index(tmp_path)
    report = cvp.convert_corpus_prose(FIXTURES, dst)

    conflicts = {rid: (idx, hdr) for rid, idx, hdr in report.title_conflicts}
    assert conflicts["REQ-002"] == (
        "Message & MessageQueue (thread-safe)", "Message and MessageQueue (thread-safe)"
    )
    assert conflicts["REQ-011"] == (
        "Python CLI tool (thermoctl)", "Python CLI tool for device deployment and maintenance"
    )
    # the twelve-file corpus drifted in exactly these two places
    assert set(conflicts) == {"REQ-002", "REQ-011"}

    # the header title wins in the frontmatter *and* in the regenerated row
    assert parse_req(dst / "REQ-002.md").title == "Message and MessageQueue (thread-safe)"
    index_text = (dst / "REQUIREMENTS_INDEX.md").read_text(encoding="utf-8")
    assert "| REQ-002 | Message and MessageQueue (thread-safe) |" in index_text
    assert "Message & MessageQueue" not in index_text


# --- AC6 -------------------------------------------------------------------------------


def test_unparseable_aborts_atomically_and_stub_is_skipped(tmp_path):
    # an in-place corpus (src == dst) with one file the parser cannot read
    src = _seed_index(tmp_path / "corpus")
    for path in FIXTURES.glob("REQ-*.md"):
        shutil.copy(path, src / path.name)
    (src / "REQ-003.md").write_text("no header here at all\n", encoding="utf-8")

    before = {p.name: p.read_bytes() for p in src.iterdir()}
    with pytest.raises(cvp.ProseParseError) as exc:
        cvp.convert_corpus_prose(src, src)
    assert "REQ-003.md" in str(exc.value)
    assert "nothing written" in str(exc.value)

    # every file — REQs and index alike — is byte-unchanged: no partial corpus.
    assert {p.name: p.read_bytes() for p in src.iterdir()} == before

    # the template stub is skipped by name, not treated as an error
    dst = _seed_index(tmp_path / "clean")
    report = cvp.convert_corpus_prose(FIXTURES, dst)
    assert len(report.reqs) == 12
    assert "REQ-xxx" not in {r.id for r in report.reqs}
    assert not (dst / "REQ-xxx.md").exists()


# --- AC7 -------------------------------------------------------------------------------


def test_thermo_corpus_matches_goldens_and_is_idempotent(tmp_path):
    dst = _seed_index(tmp_path / "out")
    cvp.convert_corpus_prose(FIXTURES, dst)

    produced = sorted(p.name for p in dst.glob("*.md"))
    assert produced == sorted(p.name for p in GOLDEN.glob("*.md"))
    for name in produced:
        assert (dst / name).read_text(encoding="utf-8") == (
            GOLDEN / name
        ).read_text(encoding="utf-8"), f"{name} diverged from its golden"

    # a second run over the converted output is a byte-identical no-op
    snapshot = {p.name: p.read_bytes() for p in dst.iterdir()}
    cvp.convert_corpus_prose(dst, dst)
    assert {p.name: p.read_bytes() for p in dst.iterdir()} == snapshot


# --- AC8 -------------------------------------------------------------------------------


def test_thermo_corpus_lints_clean_and_index_prose_survives(tmp_path):
    dst = _seed_index(tmp_path / "out")
    report = cvp.convert_corpus_prose(FIXTURES, dst)

    cfg = Config(root=dst, requirements_dir=".", index_file="REQUIREMENTS_INDEX.md")
    assert lint(cfg) == []

    # Decision 10 is *why* lint is clean: the two active REQs whose criteria carry no test id
    # come in as draft (exempt from rule 5), and are reported. Terminal REQs are never
    # demoted, and no verdict is touched.
    assert report.demotions == [("REQ-011", "in-progress"), ("REQ-012", "open")]
    assert parse_req(dst / "REQ-011.md").status == "draft"
    assert parse_req(dst / "REQ-001.md").status == "done"
    assert all(ac.status == "pending" for ac in parse_req(dst / "REQ-012.md").acceptance)

    # the index rows are parseable and in sync with the frontmatter
    rows = _index_rows(dst / "REQUIREMENTS_INDEX.md")
    assert set(rows) == {r.id for r in report.reqs}
    for r in report.reqs:
        assert rows[r.id] == r.status.lower()

    # …and the splice preserved everything around the REQ table
    index_text = (dst / "REQUIREMENTS_INDEX.md").read_text(encoding="utf-8")
    assert "# Requirements Index — Phase 5 Integration" in index_text
    assert "## Dependency graph" in index_text
    assert "REQ-001 (ArduinoJson)──┬──REQ-002 (Message)" in index_text
    assert "## Implementation order" in index_text
    assert "New requirement template: [REQ-xxx.md](REQ-xxx.md)" in index_text
