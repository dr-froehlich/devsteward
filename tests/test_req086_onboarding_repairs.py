"""REQ-086 — the three onboarding-machinery repairs from the live memzy run (REQ-062).

Findings 1–3 of the ``docs/reports/2026-08-01-req062-memzy-onboarding-report.md``: the
pipeline works but misinforms its operator at three points. They are three disjoint surfaces
— a skill's documented ordering, ``steward sync``'s tracked set, and the memzy converter's
operator report — so they get three independent oracles here.

AC1's oracle is deliberately the **weak** one (REQ-086 Decision 3): an assertion over the text
of a skill, authored alongside the change, which can confirm only what its author already
believed. It is worth having because the ordering can then never silently regress; "the
operator was never asked to override a red gate" is an observation about a *live* migration
and its decoupled proof is REQ-085's THermo run, one REQ downstream.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from click.testing import CliRunner

import convert_reqs
from devsteward import skillsync
from devsteward.cli import _package_templates, main

_REPO_ROOT = Path(__file__).resolve().parents[1]
ONBOARD_SKILL = _REPO_ROOT / ".claude" / "skills" / "onboard" / "SKILL.md"


def _stamp_project(tmp_path: Path, name: str = "consumer") -> Path:
    target = tmp_path / name
    result = CliRunner().invoke(main, ["new", str(target)])
    assert result.exit_code == 0, result.output
    return target


def _templates_copy(tmp_path: Path) -> Path:
    """A mutable copy of the bundled templates, standing in for the installed engine."""
    dst = tmp_path / "templates"
    shutil.copytree(_package_templates(), dst, symlinks=False)
    return dst


# -- AC1: /onboard commits the converted corpus before seeding the ledger -----


def test_onboard_sequences_commit_before_seed_ledger():
    """The skill's documented sequence puts the conversion **commit** between the convert
    step and ``steward seed-ledger``, and states the REQ-077 HEAD-marker reason for it — so a
    correct onboarding never presents its operator with a red lint gate to wave through."""
    md = ONBOARD_SKILL.read_text(encoding="utf-8")
    low = md.lower()

    # Anchor on the step *headings*, not on any mention: the preamble names every tool the
    # skill orchestrates (`steward seed-ledger` among them) long before the steps start.
    convert_at = low.find("## 1. convert the req corpus")
    commit_at = low.find("## 2. commit the converted corpus")
    seed_at = low.find("## 3. seed the ledger")
    stamp_at = low.find("## 4. stamp the scaffold")
    assert commit_at != -1, "the skill must document a commit step for the converted corpus"
    assert 0 <= convert_at < commit_at < seed_at < stamp_at, (
        "sequence must be convert → commit → seed-ledger → stamp: "
        f"{convert_at} {commit_at} {seed_at} {stamp_at}"
    )
    # The seeding *command* is inside the seed step, i.e. after the commit — not merely the
    # heading order.
    assert md.index("steward seed-ledger", seed_at) > commit_at

    # The *reason* is stated, not just the ordering — otherwise a later reader "tidies" it
    # back. REQ-077's rule compares a seeded `done` step against the committed marker.
    reason = md[commit_at:seed_at]
    assert "REQ-077" in reason, "the commit step must name the rule that requires it"
    assert "HEAD" in reason, "the reason must be the HEAD-vs-working-tree comparison"
    assert "ABSENT" in reason, "quote the actual red the operator would otherwise see"

    # And the cure is ordering, never suppression of a correctly-firing rule (Decision 2).
    assert "suppress" in reason.lower() or "weaken" in reason.lower()

    # The absolutism the ordering protects is unchanged: red is still a hard stop.
    assert "red" in low and "stop" in low


# -- AC2: steward sync seeds <requirements_dir>/_templates/req.md -------------


def test_sync_seeds_req_template(tmp_path):
    """A project lacking the REQ template acquires it through ``sync``, at the path its
    configured ``requirements_dir`` names, reported in the refreshed set — closing the gap
    that made memzy's next ``/intake`` unrunnable (Finding 2)."""
    target = _stamp_project(tmp_path)
    templates = _package_templates()

    # A project onboarded by the skill as written: no _templates/ at all. Use THermo's
    # singular `doc/` layout (REQ-084 seam) so the relocation is exercised, not assumed.
    req_dir = "doc/requirements"
    shutil.rmtree(target / "docs" / "requirements" / "_templates")
    (target / req_dir).mkdir(parents=True)

    dest = target / req_dir / "_templates" / "req.md"
    assert not dest.exists()
    assert skillsync.REQ_TEMPLATE_KEY in {
        d.name for d in skillsync.drift(target, templates, req_dir)
    }, "an absent REQ template must show as drift, not be invisible"

    result = skillsync.sync(target, templates, req_dir)

    assert skillsync.REQ_TEMPLATE_KEY in result.synced
    assert dest.is_file(), "the template must land under the configured requirements_dir"
    assert dest.read_bytes() == (
        templates / "docs" / "requirements" / "_templates" / "req.md"
    ).read_bytes()
    # The `/intake`-style read the stamped skill performs now succeeds and finds a REQ
    # template, not an empty file.
    text = dest.read_text(encoding="utf-8")
    assert "id:" in text and "status:" in text

    # Provenance recorded under a location-independent key, and the artifact is now in-sync.
    assert skillsync.REQ_TEMPLATE_KEY in skillsync.read_lock(target)
    assert skillsync.drift(target, templates, req_dir) == []


def test_sync_refuses_customized_req_template(tmp_path):
    """A project that has tailored its REQ template never has it clobbered — same
    customized-refusal semantics as a customized skill."""
    target = _stamp_project(tmp_path)
    templates = _templates_copy(tmp_path)
    tmpl = target / "docs" / "requirements" / "_templates" / "req.md"

    customized = tmpl.read_text(encoding="utf-8") + "\n<!-- this project's own house rule -->\n"
    tmpl.write_text(customized, encoding="utf-8")

    # The engine advances too, so the artifact is genuinely both-moved — the hardest case.
    src = templates / "docs" / "requirements" / "_templates" / "req.md"
    src.write_text(src.read_text(encoding="utf-8") + "\n<!-- engine moved on -->\n",
                   encoding="utf-8")

    result = skillsync.sync(target, templates, "docs/requirements")

    assert skillsync.REQ_TEMPLATE_KEY in result.refused
    assert skillsync.REQ_TEMPLATE_KEY not in result.synced + result.forced
    assert tmpl.read_text(encoding="utf-8") == customized, "byte-unchanged, no clobber"
    assert not tmpl.with_name("req.md.orig").exists(), "no backup without --force"

    # --force refreshes it, but only after backing the consumer's bytes up.
    forced = skillsync.sync(target, templates, "docs/requirements", force=True)
    assert skillsync.REQ_TEMPLATE_KEY in forced.forced
    assert tmpl.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")
    assert tmpl.with_name("req.md.orig").read_text(encoding="utf-8") == customized


# -- AC4: the converter reports dropped non-schema frontmatter keys -----------


_WITH_UNKNOWN_KEYS = """---
id: REQ-039
title: "A REQ whose author recorded a relation the schema has no field for"
status: done
added: 2026-07-01
completed: 2026-07-02
depends_on: [REQ-013]
amends: [REQ-013]
superseded_by: null
tags: [example]
---

## Requirement

Do the thing.
"""

_CLEAN = """---
id: REQ-040
title: "A REQ with nothing to drop"
status: done
added: 2026-07-01
depends_on: []
tags: []
---

## Requirement

Do the other thing.
"""


def test_converter_reports_dropped_frontmatter_keys(tmp_path, capsys):
    """Every dropped non-schema key is reported per file, while the emitted frontmatter is
    byte-identical to the pre-REQ-086 conversion — the cure is a report, not preservation
    (Decision 5), so no existing conversion output changes."""
    src = tmp_path / "requirements"
    src.mkdir()
    (src / "REQ-039.md").write_text(_WITH_UNKNOWN_KEYS, encoding="utf-8")
    (src / "REQ-040.md").write_text(_CLEAN, encoding="utf-8")

    # The pure oracle: source order, every key the hybrid schema will not carry.
    fm = {"id": "REQ-039", "amends": ["REQ-013"], "superseded_by": None, "title": "t"}
    assert convert_reqs.dropped_frontmatter_keys(fm) == ["amends", "superseded_by"]

    scan = convert_reqs.scan_dropped_keys(src)
    assert scan == {"REQ-039.md": ["amends", "superseded_by"]}, \
        "only files that actually drop a key are reported"

    # The conversion output itself is unchanged: the report adds no frontmatter key.
    before = convert_reqs.convert_req_text(_WITH_UNKNOWN_KEYS)
    dst = tmp_path / "out"
    assert convert_reqs.main([str(src), str(dst)]) == 0
    assert (dst / "REQ-039.md").read_text(encoding="utf-8") == before
    assert "amends" not in (dst / "REQ-039.md").read_text(encoding="utf-8")

    # …and it reached the operator, on the same channel as the other converter reports.
    out = capsys.readouterr().out
    assert "REQ-039.md" in out
    assert "amends" in out and "superseded_by" in out
    assert "REQ-040.md" not in out, "a file with nothing dropped is not reported"
