"""REQ-002 AC1 — parse_req reads frontmatter and the acceptance block."""

from __future__ import annotations

from devsteward.profiles.req.reqfile import load_reqs, parse_req, update_acceptance_status

from conftest import write_req


def test_parse_frontmatter_and_acceptance(tmp_path):
    write_req(tmp_path, "REQ-005", status="open", depends_on=["REQ-001"])
    req = parse_req(tmp_path / "REQ-005.md")

    assert req.id == "REQ-005"
    assert req.status == "open"
    assert req.depends_on == ["REQ-001"]
    assert req.is_active
    assert len(req.acceptance) == 1
    assert req.acceptance[0].id == "AC1"
    assert req.acceptance[0].test == "true"


def test_dates_normalized_to_strings(tmp_path):
    write_req(tmp_path, "REQ-005")
    req = parse_req(tmp_path / "REQ-005.md")
    # Unquoted YAML dates must come back as ISO strings, not date objects.
    assert req.frontmatter["added"] == "2026-06-06"
    assert isinstance(req.frontmatter["added"], str)


def test_missing_frontmatter_raises(tmp_path):
    bad = tmp_path / "REQ-099.md"
    bad.write_text("no frontmatter here\n", encoding="utf-8")
    try:
        parse_req(bad)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "frontmatter" in str(exc)


def test_load_reqs_skips_templates(tmp_path):
    write_req(tmp_path, "REQ-001")
    write_req(tmp_path, "REQ-002")
    (tmp_path / "REQ-xxx.md").write_text("--- \nid: REQ-xxx\n---\n", encoding="utf-8")
    reqs = load_reqs(tmp_path)
    assert [r.id for r in reqs] == ["REQ-001", "REQ-002"]


def test_update_acceptance_status_is_surgical(tmp_path):
    write_req(tmp_path, "REQ-005")
    path = tmp_path / "REQ-005.md"
    update_acceptance_status(path, {"AC1": "pass"})
    req = parse_req(path)
    assert req.acceptance[0].status == "pass"
    # Prose around the block is preserved.
    assert "## Notes" in path.read_text(encoding="utf-8")


def test_acceptance_check_parsed_and_default_empty(tmp_path):
    """REQ-027 — `check:` is read per criterion; absent means undeclared (\"\"), so the
    linter can tell omission from a default."""
    write_req(tmp_path, "REQ-005", check="artifact")
    assert parse_req(tmp_path / "REQ-005.md").acceptance[0].check == "artifact"

    write_req(tmp_path, "REQ-006", check=None)
    assert parse_req(tmp_path / "REQ-006.md").acceptance[0].check == ""


def test_status_writeback_preserves_check(tmp_path):
    """REQ-027 — the engine's surgical status write-back must not strip the `check:` key
    (the ruamel round-trip is verified, not trusted)."""
    write_req(tmp_path, "REQ-005", check="manual")
    path = tmp_path / "REQ-005.md"
    update_acceptance_status(path, {"AC1": "fail"})
    req = parse_req(path)
    assert req.acceptance[0].status == "fail"
    assert req.acceptance[0].check == "manual"

