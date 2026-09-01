"""REQ-057 — the Claude-targeted `steward` black-box manual ships and is wired (AC2), and the
handbook, the manual, and the bundled skills carry the current verbs (AC3).

These are documentation-shape regression tests: a missing manual, a broken stamp, an unwired
CLAUDE.md, or a doc/skill that still presents `steward recover` as a live command must fail
the gate. They cannot certify "complete revision" or "black-box sufficiency" — that is AC4's
human oracle.
"""

from __future__ import annotations

import re
from pathlib import Path

import click
from click.testing import CliRunner

from devsteward.cli import _package_templates, main as cli_main

_REPO = Path(__file__).resolve().parent.parent


def test_claude_manual_ships_stamped_and_referenced(tmp_path):
    """AC2: the manual is in the package templates (package-data), `steward new` stamps it to
    the consumer root, and the stamped consumer CLAUDE.md references it as the steward doc."""
    # (a) present in the bundled templates (rides the existing `templates/**/*` package-data).
    assert (_package_templates() / "STEWARD.md").is_file()

    # (b) `steward new` stamps it into a fresh project root.
    target = tmp_path / "proj"
    res = CliRunner().invoke(cli_main, ["new", str(target)])
    assert res.exit_code == 0, res.output
    assert (target / "STEWARD.md").is_file()

    # (c) the stamped consumer CLAUDE.md points at it as the steward usage doc.
    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "STEWARD.md" in claude_md


def test_docs_and_skills_use_current_verbs():
    """AC3: the handbook and the manual name `repeat` and `revalidate`; the bundled skills name
    `repeat`; and none of the three presents `steward recover` as a live command."""
    handbook = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (_REPO / "devsteward" / "handbook").glob("*.qmd")
    )
    manual = (_REPO / "devsteward" / "templates" / "STEWARD.md").read_text(encoding="utf-8")
    skills = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (_REPO / "devsteward" / "templates" / ".claude" / "skills").rglob("SKILL.md")
    )

    assert "repeat" in handbook and "revalidate" in handbook
    assert "repeat" in manual and "revalidate" in manual
    assert "repeat" in skills

    for surface in (handbook, manual, skills):
        assert "steward recover" not in surface


# -- REQ-094: the manual's command coverage is derived from the CLI, not enumerated ----------
#
# The pre-REQ-094 guard above (`test_docs_and_skills_use_current_verbs`, REQ-057 AC3) is a
# hand-enumerated two-verb allowlist. It is retained — it is a landed REQ's oracle and it covers
# the handbook and the bundled skills, which nothing below looks at — but it is no longer the
# *guarantee*: it structurally cannot see a verb that never reached the manual, which is how ten
# consumer-facing verbs accumulated across REQ-036/066, REQ-089 and REQ-093. Completeness now
# comes from the click registry, the same way `skillsync.tracked_artifacts` derives its set from
# what the template actually ships rather than from a list someone must remember to edit.

_MANUAL = _REPO / "devsteward" / "templates" / "STEWARD.md"
_REFERENCE_HEADING = "## Command reference"


def _registered_verbs() -> set[str]:
    """Every command the `steward` CLI registers, read from the group at call time.

    Read live (not captured at import) so a test-time registration is visible — that is what
    makes the derivation disconfirmable in `test_verb_coverage_is_derived_not_enumerated`.
    """
    return set(cli_main.commands)


def _reference_rows() -> dict[str, str]:
    """The manual's command-reference table as ``{verb: run-by annotation}``.

    Parses the section under :data:`_REFERENCE_HEADING` up to the next ``## `` heading: markdown
    rows whose first cell is ``` `steward <verb>` ``` (the verb alone, no arguments — that is
    what keeps the row machine-readable) and whose third cell is the "run by / when" annotation.
    The header and separator rows carry no such first cell and drop out on their own.
    """
    text = _MANUAL.read_text(encoding="utf-8")
    if _REFERENCE_HEADING not in text:
        return {}
    section = text.split(_REFERENCE_HEADING, 1)[1].split("\n## ", 1)[0]
    rows: dict[str, str] = {}
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        m = re.fullmatch(r"`steward ([a-z][a-z-]*)`", cells[0])
        if m:
            rows[m.group(1)] = cells[2]
    return rows


def test_manual_covers_every_registered_verb():
    """AC1: the reference table and the click registry name exactly the same verbs.

    Both directions. Forward is the defect this REQ exists for — a shipped verb the manual never
    mentions, which is what a consumer agent cannot discover. Reverse catches a verb the manual
    still advertises after the engine retired it. The reverse check reads the *table*, never the
    whole file: the manual deliberately carries negative prose ("There is no `steward degrade`")
    that a whole-file scan would flag as a phantom verb.
    """
    documented = _reference_rows()
    assert documented, (
        f"{_MANUAL.name} has no parseable '{_REFERENCE_HEADING}' table — the manual is the "
        "consumer agent's whole interface to the engine and must list what it can run"
    )
    registered = _registered_verbs()

    missing = sorted(registered - documented.keys())
    assert not missing, (
        f"shipped but undocumented in {_MANUAL.name}: {missing}. A consumer drives the engine "
        "through this manual alone — a verb that is not here does not exist for them."
    )
    phantom = sorted(documented.keys() - registered)
    assert not phantom, (
        f"documented in {_MANUAL.name} but not registered: {phantom}. Either the verb was "
        "retired and its row must go, or the row has a typo."
    )


def test_verb_coverage_is_derived_not_enumerated():
    """AC2: the coverage check reads the live registry, so a new verb turns it red by itself.

    This is the test the superseded hand-enumerated allowlist could never fail: register a
    throwaway command and the missing-set must name exactly it. If coverage were a literal list,
    the difference would stay empty and a genuinely undocumented verb would ship green — which is
    precisely what happened three times.
    """
    probe = "req094-probe-verb"
    assert probe not in cli_main.commands
    cli_main.add_command(click.Command(probe, callback=lambda: None), name=probe)
    try:
        missing = _registered_verbs() - _reference_rows().keys()
        assert missing == {probe}, (
            "the coverage check did not notice a newly registered command — it is enumerating a "
            f"fixed list, not deriving from the registry (saw missing={sorted(missing)})"
        )
    finally:
        cli_main.commands.pop(probe, None)
    assert probe not in cli_main.commands


def test_command_reference_annotates_who_runs_each_verb():
    """AC3: every row says who runs the verb and when, and `cache` warns against in-session use.

    The annotation replaces an exclusion set (REQ-094 Decision 3). An exclusion list would have
    been a list someone can quietly grow to silence this test, and it would have deleted the one
    thing an agent actually needs to know about `cache`: running it from inside the session warms
    the very cache it reports on, so the reading is worthless. That is a warning, not an omission.
    """
    rows = _reference_rows()
    assert rows, f"no parseable '{_REFERENCE_HEADING}' table in {_MANUAL.name}"

    unannotated = sorted(verb for verb, note in rows.items() if not note)
    assert not unannotated, (
        f"command-reference rows with an empty 'run by / when' cell: {unannotated}. Every verb "
        "says who runs it — that is what makes documenting all of them useful instead of noisy."
    )

    cache_note = rows.get("cache", "").lower()
    assert "second shell" in cache_note, (
        f"`cache`'s annotation must send the reader to a second shell; got: {cache_note!r}"
    )
    assert "never from inside a session" in cache_note, (
        "`cache`'s annotation must forbid the in-session run outright — measuring the session's "
        f"cache warmth from inside it warms what it measures; got: {cache_note!r}"
    )


def test_manual_documents_backlog_take_up():
    """AC4: the manual carries the backlog layer REQ-093 shipped without documenting it.

    The verbs alone are not enough to use the layer: an agent must know that `backlog_refs:` is
    the *only* stored record of take-up (there is no status column anywhere), and that the
    owner's verdict cannot fail a REQ that met its specification.
    """
    manual = _MANUAL.read_text(encoding="utf-8")
    assert "backlog_refs" in manual, (
        "the manual must name `backlog_refs:` — it is the single stored record of take-up, and "
        "an agent that does not know the field cannot record one"
    )
    assert "advisory to the REQ and blocking to the item" in " ".join(manual.split()), (
        "the manual must state that an item's acceptance verdict is advisory to the REQ and "
        "blocking to the item — otherwise a denial reads as a failed REQ"
    )
