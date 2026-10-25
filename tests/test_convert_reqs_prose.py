"""REQ-017 + REQ-085 — the legacy prose-header REQ converter.

Drives ``scripts/convert_reqs_prose.py`` (on ``sys.path`` via the conftest shim) against all
**28** captured **THermo** REQs — re-captured wholesale at THermo ``e45f4ac`` (REQ-085
Decision 8), replacing REQ-017's 12. Two oracles, because they disconfirm different failures
(REQ-017 Decision 8): ``steward lint`` is decoupled — it predates this converter and knows
nothing about it — but only proves the output is *schema-valid*; the committed goldens prove
*fidelity*, that REQ-012's 122 lines of prose survived byte-for-byte, but are authored
alongside the converter and can only confirm what the author already believed.

The re-capture is the point, not bookkeeping: the sixteen REQs added between REQ-017's census
and REQ-085 brought four grammar constructs the parser had never seen, five files that aborted
the run, and title drift from 2-of-12 to 11-of-28. The REQ-085 block at the bottom covers
those; the REQ-017 blocks above it are its original guarantees, re-asserted over the bigger
corpus.

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
    # REQ-085: the 28-REQ corpus drifted in exactly eleven places, not the two REQ-017's
    # 12-REQ census saw — the index rows are systematically the shorter, more editorial
    # wording. Decision 5 still stands (the file's header wins) but the operator is expected
    # to *read* this report, not skim it, which is why the whole set is pinned.
    assert set(conflicts) == {
        "REQ-002", "REQ-011", "REQ-014", "REQ-017", "REQ-018", "REQ-020",
        "REQ-021", "REQ-022", "REQ-026", "REQ-027", "REQ-028",
    }
    assert conflicts["REQ-028"] == (
        "Rooms-set merge semantics + device routes survive rebuild",
        "Device-level rooms-set must merge, not clobber; device routes must survive a "
        "rooms rebuild",
    )

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
    assert len(report.reqs) == 28
    assert "REQ-xxx" not in {r.id for r in report.reqs}
    assert not (dst / "REQ-xxx.md").exists()


# --- AC7 -------------------------------------------------------------------------------


def test_thermo28_corpus_matches_goldens_and_is_idempotent(tmp_path):
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


def test_thermo28_lints_clean_under_doc_layout_and_index_prose_survives(tmp_path):
    """REQ-085 AC7 — the converted corpus lints clean in a project laid out the way THermo
    actually is: the **singular** ``doc/`` tree, carried by REQ-084's config seams rather than
    the engine's conventional ``docs/`` default."""
    root = tmp_path / "project"
    dst = _seed_index(root / "doc" / "requirements")
    report = cvp.convert_corpus_prose(FIXTURES, dst)

    cfg = Config(
        root=root,
        requirements_dir="doc/requirements",
        index_file="doc/requirements/REQUIREMENTS_INDEX.md",
        plans_dir="doc/plans",
        concepts_dir="doc/concepts",
    )
    assert lint(cfg) == []

    # The corpus is now entirely terminal, so REQ-017 Decision 10 (an active REQ with no
    # runnable criteria imports as `draft`) has nothing to fire on — dormant, not dead. No
    # verdict is touched either way: every imported checkbox keeps its own state.
    assert report.demotions == []
    assert {r.status for r in report.reqs} == {"done", "superseded"}
    assert parse_req(dst / "REQ-011.md").status == "superseded"
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


# =======================================================================================
# REQ-085 — the four grammar constructs the live corpus grew after REQ-017's census, plus
# the `supersedes:` extraction. Every one of them arrived in the ~24 hours between that
# census and REQ-085's intake, which is the lesson: a converter specced against a snapshot
# of a *live* corpus is specced against a moving target. The answer is not a better
# snapshot but a tool that tolerates an **enumerated class** of variation and still fails
# atomically and legibly outside it (Decision 3).
# =======================================================================================


# --- AC1 -------------------------------------------------------------------------------


def test_header_banner_rides_through_as_body_prose(tmp_path):
    """A blockquote banner between the header and the first field bullet parses, rides into
    the body verbatim, and is never mistaken for a field — the construct that aborted
    THermo's REQ-011/REQ-012."""
    raw = (FIXTURES / "REQ-011.md").read_text(encoding="utf-8")
    assert raw.split("\n")[2].startswith("> **SUPERSEDED by"), "fixture still has the banner"

    parsed = cvp.parse_prose_req(raw, name="REQ-011.md")
    assert parsed.banner.startswith("> **SUPERSEDED by [REQ-026](REQ-026.md)**")
    assert "legacy-tree-removal milestone" in parsed.banner  # the whole block, not line one
    assert "banner" not in parsed.segments and set(parsed.segments) <= _FIELDS

    req = _convert_one(tmp_path, "REQ-011.md")
    text = (tmp_path / "REQ-011.md").read_text(encoding="utf-8")
    for line in parsed.banner.splitlines():
        assert line in text, f"banner line lost: {line!r}"
    # …as body prose under the preserved header, ahead of the first generated section.
    assert text.index("### REQ-011:") < text.index("> **SUPERSEDED") < text.index("## Requirement")
    # …and nothing of it leaked into frontmatter.
    assert "SUPERSEDED" not in text.split("---")[1]
    assert req.status == "superseded"

    # Leading content that is *not* a blockquote still aborts: the tolerance is for one
    # recognized shape, never for stray content (Decision 3).
    with pytest.raises(cvp.ProseParseError) as exc:
        cvp.parse_prose_req(
            raw.replace("> **SUPERSEDED by", "SUPERSEDED by"), name="REQ-011.md"
        )
    assert "content before the first field bullet" in str(exc.value)


# --- AC2 -------------------------------------------------------------------------------


def test_prose_depends_on_extracts_ids_and_preserves_source(tmp_path):
    """Both live shapes: ids extracted in source order, the raw line preserved verbatim in
    the body so no qualifier is lost, and the carry reported."""
    # shape 1 — a parenthetical qualifier
    assert cvp.dependency_prose("REQ-011 (supersedes it)") == "REQ-011 (supersedes it)"
    # shape 2 — a semicolon clause naming further ids
    long = "REQ-026; exercises REQ-016, REQ-019, REQ-020, REQ-022, REQ-023, REQ-024"
    assert cvp.dependency_prose(long) == long
    # a bare list carries nothing extra, so nothing is preserved and nothing is reported
    assert cvp.dependency_prose("REQ-008, REQ-009") == ""
    assert cvp.dependency_prose("–") == ""

    twenty_six = _convert_one(tmp_path, "REQ-026.md")
    assert twenty_six.depends_on == ["REQ-011"]
    text = (tmp_path / "REQ-026.md").read_text(encoding="utf-8")
    assert "**Depends on:** REQ-011 (supersedes it)" in text, "the qualifier must survive"

    twenty_seven = _convert_one(tmp_path, "REQ-027.md")
    assert twenty_seven.depends_on == [
        "REQ-026", "REQ-016", "REQ-019", "REQ-020", "REQ-022", "REQ-023", "REQ-024"
    ], "every REQ-NNN token, in source order"
    assert f"**Depends on:** {long}" in (tmp_path / "REQ-027.md").read_text(encoding="utf-8")

    # The carry is reported for exactly the four lines that have one — the converter is an
    # archivist, so the operator (not the tool) adjudicates whether `exercises` is a
    # dependency.
    dst = _seed_index(tmp_path / "corpus")
    report = cvp.convert_corpus_prose(FIXTURES, dst)
    assert {rid for rid, _ in report.dep_carries} == {
        "REQ-012", "REQ-026", "REQ-027", "REQ-028"
    }
    assert ("REQ-026", "REQ-011 (supersedes it)") in report.dep_carries


# --- AC3 -------------------------------------------------------------------------------


def test_repeated_field_bullets_merge_in_source_order(tmp_path):
    """Two `- **Notes:**` bullets are two notes: merged in source order, no text lost, and
    reported — rather than the abort THermo's REQ-017 hit when REQ-025's work prepended one."""
    raw = (FIXTURES / "REQ-017.md").read_text(encoding="utf-8")
    notes = [ln for ln in raw.splitlines() if ln.startswith("- **Notes:**")]
    assert len(notes) == 2, "fixture still carries the repeated bullet"

    parsed = cvp.parse_prose_req(raw, name="REQ-017.md")
    assert parsed.merges == ["notes"]
    merged = parsed.segments["notes"]
    first, second = (n[len("- **Notes:** "):] for n in notes)
    assert merged.index(first[:40]) < merged.index(second[:40]), "source order preserved"

    _convert_one(tmp_path, "REQ-017.md")
    text = (tmp_path / "REQ-017.md").read_text(encoding="utf-8")
    assert first[:60] in text and second[:60] in text, "neither note is lost"
    assert text.count("## Notes") == 1, "one section, not two"

    dst = _seed_index(tmp_path / "corpus")
    report = cvp.convert_corpus_prose(FIXTURES, dst)
    assert report.merges == [("REQ-017", "notes")]


# --- AC4 -------------------------------------------------------------------------------


def test_implementation_plan_field_renders_as_body_prose(tmp_path):
    """The ninth known field: rendered as a body prose line, never dropped, never parsed as a
    body bullet, and inventing no frontmatter key."""
    assert "implementation_plan" in cvp.KNOWN_FIELDS

    parsed = cvp.parse_prose_req(
        (FIXTURES / "REQ-026.md").read_text(encoding="utf-8"), name="REQ-026.md"
    )
    link = "[doc/plans/REQ-026-thermoctl-fleet.md](../plans/REQ-026-thermoctl-fleet.md)"
    assert parsed.segments["implementation_plan"] == link

    req = _convert_one(tmp_path, "REQ-026.md")
    text = (tmp_path / "REQ-026.md").read_text(encoding="utf-8")
    assert f"**Implementation plan:** {link}" in text
    # No new frontmatter key — the plans gate finds `<plans_dir>/REQ-NNN*.md` by convention,
    # so a `plan_refs:` field would be machinery for one migration's convenience (Decision 6).
    assert "plan_refs" not in text
    assert "implementation_plan" not in text
    assert set(req.frontmatter) <= set(cv._FIELD_ORDER) | {"process"}

    # Before REQ-085 this bullet was *unknown*, so it was appended to whatever segment was
    # open — `depends_on` — which is what actually aborted REQ-026/REQ-027. Now it does not.
    assert req.depends_on == ["REQ-011"]


# --- AC5 -------------------------------------------------------------------------------


def test_supersedes_populated_from_both_encodings_and_conflict_aborts(tmp_path):
    """`supersedes:` lands on the **superseding** REQ from either stated encoding, every
    extraction is reported, and a disagreement between the two aborts the run."""
    dst = _seed_index(tmp_path / "out")
    report = cvp.convert_corpus_prose(FIXTURES, dst)

    # Direction matters and is easy to get backwards: REQ-011's banner says it is superseded
    # *by* REQ-026, so `supersedes: REQ-011` lands on REQ-026.
    assert parse_req(dst / "REQ-026.md").frontmatter["supersedes"] == "REQ-011"
    assert parse_req(dst / "REQ-027.md").frontmatter["supersedes"] == "REQ-012"
    assert parse_req(dst / "REQ-011.md").frontmatter["supersedes"] is None

    assert report.supersedes == [
        ("REQ-026", "REQ-011", "banner"),
        ("REQ-026", "REQ-011", "depends-on qualifier"),
        ("REQ-027", "REQ-012", "banner"),
    ]

    # The index's `SUPERSEDED (by REQ-026)` annotation is regenerated away by build_index —
    # this is where that fact now survives, in frontmatter, where the linter resolves it.
    index_text = (dst / "REQUIREMENTS_INDEX.md").read_text(encoding="utf-8")
    assert "(by REQ-026)" not in index_text

    # Each encoding works alone.
    banner_only, _ = cvp.resolve_supersedes([("REQ-026", "REQ-011", "banner")])
    assert banner_only == {"REQ-026": "REQ-011"}
    qualifier_only, _ = cvp.resolve_supersedes([("REQ-026", "REQ-011", "depends-on qualifier")])
    assert qualifier_only == {"REQ-026": "REQ-011"}

    # …and a disagreement between them is a hard stop, never a silent pick.
    with pytest.raises(cvp.ProseParseError) as exc:
        cvp.resolve_supersedes([
            ("REQ-026", "REQ-011", "banner"),
            ("REQ-026", "REQ-009", "depends-on qualifier"),
        ])
    assert "conflicting" in str(exc.value)
    assert "REQ-011" in str(exc.value) and "REQ-009" in str(exc.value)


# --- AC8 -------------------------------------------------------------------------------


#: The five files a trial conversion of THermo `e45f4ac` aborted on before REQ-085.
_BLOCKERS = ("REQ-011.md", "REQ-012.md", "REQ-017.md", "REQ-026.md", "REQ-027.md")


def test_atomic_abort_survives_and_the_five_blockers_convert(tmp_path):
    """The new tolerances did not weaken REQ-017 AC6: a genuinely unparseable file still
    takes the whole run down with every file byte-unchanged — while the five that blocked
    the live corpus now convert cleanly."""
    dst = _seed_index(tmp_path / "clean")
    report = cvp.convert_corpus_prose(FIXTURES, dst)
    converted = {r.id for r in report.reqs}
    for name in _BLOCKERS:
        assert Path(name).stem in converted, f"{name} must convert now"
        assert (dst / name).is_file()

    # An unrecognized status is still an abort (the tolerances are enumerated, not general).
    src = _seed_index(tmp_path / "corpus")
    for path in FIXTURES.glob("REQ-*.md"):
        shutil.copy(path, src / path.name)
    (src / "REQ-020.md").write_text(
        (FIXTURES / "REQ-020.md").read_text(encoding="utf-8").replace(
            "- **Status:** DONE", "- **Status:** MOSTLY"
        ),
        encoding="utf-8",
    )
    before = {p.name: p.read_bytes() for p in src.iterdir()}
    with pytest.raises(cvp.ProseParseError) as exc:
        cvp.convert_corpus_prose(src, src)
    assert "REQ-020.md" in str(exc.value) and "nothing written" in str(exc.value)
    assert {p.name: p.read_bytes() for p in src.iterdir()} == before, "no partial corpus"

    # Stray non-blockquote content before the first field bullet is likewise still fatal,
    # and likewise atomic — the banner rule did not turn into a shrug.
    (src / "REQ-020.md").write_text(
        (FIXTURES / "REQ-020.md").read_text(encoding="utf-8").replace(
            "- **Status:** DONE", "a stray sentence\n\n- **Status:** DONE"
        ),
        encoding="utf-8",
    )
    before = {p.name: p.read_bytes() for p in src.iterdir()}
    with pytest.raises(cvp.ProseParseError):
        cvp.convert_corpus_prose(src, src)
    assert {p.name: p.read_bytes() for p in src.iterdir()} == before
