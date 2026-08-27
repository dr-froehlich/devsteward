"""REQ-093 AC1–AC7 — the stakeholder-requirement layer above the REQ.

The invariant every test here defends: **nothing stores status.** Take-up lives once, in a
REQ's ``backlog_refs``; the acceptance verdict lives once, in an append-only log; and the
state an operator reads is derived from those two at display time. A test that could pass
while a second copy of either existed would not be testing this REQ.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from devsteward.cli import main
from devsteward.config import Config
from devsteward.core.ledger import Ledger
from devsteward.lint import lint
from devsteward.profiles.req import backlog as bl

from conftest import write_index, write_req

FIXTURE = Path(__file__).parent / "fixtures" / "drivesteward_backlog" / "BACKLOG.md"

TEMPLATE = (
    "# Backlog\n\nSome prose the project keeps.\n\n"
    "| Handle | Need | Origin |\n|---|---|---|\n\n"
    "## Notes\n\nProse that must survive a splice.\n"
)


def _project(tmp_path: Path, *, backlog: str | None = None, reqs=(), backlog_file="docs/BACKLOG.md"):
    """A temp project with a requirements dir, an index, and optionally a backlog."""
    req_dir = tmp_path / "reqs"
    req_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for rid, status, refs in reqs:
        write_req(req_dir, rid, status=status, backlog_refs=refs)
        rows.append((rid, f"{rid} title", status.upper(), "–"))
    write_index(req_dir, rows)
    if backlog is not None:
        path = tmp_path / backlog_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(backlog, encoding="utf-8")
    return Config(
        root=tmp_path,
        requirements_dir="reqs",
        index_file="reqs/REQUIREMENTS_INDEX.md",
        backlog_file=backlog_file,
    )


def _run(tmp_path, *args):
    """Invoke the CLI with the project root as cwd."""
    runner = CliRunner()
    return runner.invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def cli_project(tmp_path, monkeypatch):
    """A real on-disk project the CLI can discover by walking up from cwd."""
    Ledger.init(tmp_path, profile="req")
    (tmp_path / ".devsteward" / "config.yaml").write_text(
        "profile: req\nrequirements_dir: reqs\n"
        "index_file: reqs/REQUIREMENTS_INDEX.md\nbacklog_file: docs/BACKLOG.md\n",
        encoding="utf-8",
    )
    (tmp_path / "reqs").mkdir(parents=True, exist_ok=True)
    write_index(tmp_path / "reqs", [])
    monkeypatch.chdir(tmp_path)
    return tmp_path


# -- AC1 ----------------------------------------------------------------------


def test_add_mints_unique_handle_records_origin_and_preserves_prose(cli_project):
    """AC1 — capture appends an item, mints a unique handle, and touches nothing else."""
    before = TEMPLATE
    (cli_project / "docs").mkdir()
    (cli_project / "docs" / "BACKLOG.md").write_text(before, encoding="utf-8")

    r = _run(cli_project, "backlog-add", "The printout function should include the header")
    assert r.exit_code == 0, r.output
    r2 = _run(cli_project, "backlog-add", "The printout function should include the footer")
    assert r2.exit_code == 0, r2.output
    r3 = _run(cli_project, "backlog-add", "Buttons are green", "--origin", "proposed")
    assert r3.exit_code == 0, r3.output

    text = (cli_project / "docs" / "BACKLOG.md").read_text()
    items = bl.parse(text)
    assert [i.handle for i in items] == [
        "printout-function-include",   # stopwords dropped; three meaning-carrying words
        "printout-function-include-2",  # collision resolved, still quotable
        "buttons-green",
    ]
    assert [i.origin for i in items] == ["operator", "operator", "proposed"]
    assert items[0].need == "The printout function should include the header"

    # every byte of the surrounding prose survives — only rows were inserted
    for line in before.splitlines():
        assert line in text.splitlines()
    assert text.endswith("## Notes\n\nProse that must survive a splice.\n")

    # an explicit handle that collides is refused rather than silently suffixed
    r4 = _run(cli_project, "backlog-add", "Another", "--handle", "buttons-green")
    assert r4.exit_code != 0
    assert "already used" in r4.output


def test_add_creates_the_file_from_the_template_and_never_overwrites(cli_project):
    """AC1/AC6 — wanting to record a need is the moment a project acquires a backlog."""
    path = cli_project / "docs" / "BACKLOG.md"
    assert not path.exists()

    assert _run(cli_project, "backlog-add", "I want a dark mode").exit_code == 0
    created = path.read_text()
    assert "| Handle | Need | Origin |" in created
    assert "an item that names a mechanism" in created  # the grammar is documented in place
    assert len(bl.parse(created)) == 1

    assert _run(cli_project, "backlog-add", "I want bigger text").exit_code == 0
    # the second add appended; it did not re-stamp over the first
    assert len(bl.parse(path.read_text())) == 2


# -- AC2 ----------------------------------------------------------------------


def test_lint_referential_integrity_and_no_stored_status(tmp_path):
    """AC2 — ``backlog_refs`` is the one stored record of take-up, and it must resolve."""
    backlog = TEMPLATE.replace(
        "|---|---|---|\n",
        "|---|---|---|\n| real-need | A real need. | operator |\n",
    )
    cfg = _project(
        tmp_path,
        backlog=backlog,
        reqs=[("REQ-001", "open", ["real-need"]), ("REQ-002", "open", ["ghost-need"])],
    )
    problems = lint(cfg)
    assert not any("REQ-001" in p and "backlog_refs" in p for p in problems)
    assert any(
        "REQ-002" in p and "'ghost-need' does not resolve" in p for p in problems
    ), problems

    # the file itself carries no status/taken-up column, so there is nothing to reconcile
    assert "Status" not in backlog.split("| Handle")[1].split("\n")[0]
    assert "Taken up" not in backlog


def test_lint_rejects_a_duplicate_handle_and_an_orphan_verdict(tmp_path):
    """AC2 — uniqueness inside the file, and a verdict may not name an unknown handle."""
    dup = TEMPLATE.replace(
        "|---|---|---|\n",
        "|---|---|---|\n| same | One. | operator |\n| same | Two. | operator |\n",
    )
    cfg = _project(tmp_path, backlog=dup)
    assert any("already used" in p for p in lint(cfg)), lint(cfg)

    ok = TEMPLATE.replace("|---|---|---|\n", "|---|---|---|\n| kept | A need. | operator |\n")
    cfg2 = _project(tmp_path / "b", backlog=ok)
    (tmp_path / "b" / ".devsteward").mkdir(parents=True, exist_ok=True)
    bl.append_event(tmp_path / "b", bl.Event(handle="vanished", event=bl.DENIED, reason="x"))
    assert any("'vanished'" in p for p in lint(cfg2)), lint(cfg2)


# -- AC3 ----------------------------------------------------------------------


def test_absent_backlog_is_inert_across_lint_status_and_commands(tmp_path, cli_project):
    """AC3 — a project with no backlog file is untouched: this is devsteward's own case."""
    cfg = _project(tmp_path, backlog=None, reqs=[("REQ-001", "open", [])])
    assert lint(cfg) == [], lint(cfg)  # no backlog, no claims → nothing to say

    # but a REQ that *claims* a handle with no file is a dangling claim, not silence
    cfg2 = _project(tmp_path / "c", backlog=None, reqs=[("REQ-001", "open", ["nope"])])
    assert any("no backlog file" in p for p in lint(cfg2))

    r = _run(cli_project, "backlog-list")
    assert r.exit_code == 0, r.output
    assert "docs/BACKLOG.md" in r.output and "keeps none" in r.output

    r2 = _run(cli_project, "backlog-accept", "anything")
    assert r2.exit_code != 0
    assert "no backlog at docs/BACKLOG.md" in r2.output

    assert _run(cli_project, "status").exit_code == 0


def test_devsteward_itself_keeps_no_backlog_and_lints_green():
    """AC3 — the honor-when-present promise, checked against the live repo."""
    root = Path(__file__).resolve().parent.parent
    cfg = Config(root=root, requirements_dir="docs/requirements",
                 index_file="docs/requirements/REQUIREMENTS_INDEX.md")
    assert not cfg.backlog_path.exists()
    assert not any("backlog" in p for p in lint(cfg))


# -- AC4 ----------------------------------------------------------------------


def test_verdicts_append_only_reason_mandatory_and_history_survives(cli_project):
    """AC4 — the sequence of verdicts *is* the attempt record, so nothing is rewritten."""
    _run(cli_project, "backlog-add", "Easy to use", "--handle", "easy-to-use")

    assert _run(cli_project, "backlog-deny", "easy-to-use").exit_code != 0  # no --reason
    r = _run(cli_project, "backlog-accept", "easy-to-use")
    assert r.exit_code == 0, r.output
    r = _run(cli_project, "backlog-deny", "easy-to-use", "--reason", "still three clicks")
    assert r.exit_code == 0, r.output
    assert "stays open" in r.output
    assert _run(cli_project, "backlog-accept", "easy-to-use").exit_code == 0

    lines = (cli_project / ".devsteward" / "backlog.jsonl").read_text().strip().splitlines()
    events = [json.loads(x) for x in lines]
    assert [e["event"] for e in events] == ["accepted", "denied", "accepted"]
    assert events[1]["reason"] == "still three clicks"
    assert all(e["handle"] == "easy-to-use" for e in events)
    # a retirement also demands a reason
    assert _run(cli_project, "backlog-retire", "easy-to-use").exit_code != 0


def test_a_verdict_names_the_req_that_attempted_the_need(cli_project):
    """AC4 — the attempt record says *who* tried, without the operator retyping it."""
    _run(cli_project, "backlog-add", "Fast verdict", "--handle", "rapid-verdict")
    write_req(cli_project / "reqs", "REQ-007", status="done", backlog_refs=["rapid-verdict"])
    write_index(cli_project / "reqs", [("REQ-007", "t", "DONE", "–")])

    assert _run(cli_project, "backlog-deny", "rapid-verdict", "--reason", "too slow").exit_code == 0
    event = json.loads(
        (cli_project / ".devsteward" / "backlog.jsonl").read_text().strip().splitlines()[-1]
    )
    assert event["req"] == "REQ-007"


# -- AC5 ----------------------------------------------------------------------


def test_list_derives_all_states_from_req_graph_and_events(tmp_path):
    """AC5 — every state is computed; flipping a REQ's status alone changes what is shown."""
    rows = "".join(
        f"| {h} | Need {h}. | operator |\n"
        for h in ("untouched", "being-built", "tried", "denied-once", "accepted-one", "gone")
    )
    backlog = TEMPLATE.replace("|---|---|---|\n", "|---|---|---|\n" + rows)
    cfg = _project(
        tmp_path,
        backlog=backlog,
        reqs=[
            ("REQ-001", "open", ["being-built"]),
            ("REQ-002", "done", ["tried"]),
            ("REQ-003", "done", ["denied-once"]),
            ("REQ-004", "done", ["accepted-one"]),
        ],
    )
    bl.append_event(tmp_path, bl.Event("denied-once", bl.DENIED, req="REQ-003", reason="not yet"))
    bl.append_event(tmp_path, bl.Event("accepted-one", bl.ACCEPTED, req="REQ-004"))
    bl.append_event(tmp_path, bl.Event("gone", bl.RETIRED, reason="changed my mind"))

    from devsteward.profiles.req.reqfile import load_reqs

    def states():
        st = bl.standings(bl.load(cfg.backlog_path), load_reqs(cfg.req_dir), bl.read_events(tmp_path))
        return {s.item.handle: bl.describe(s) for s in st}

    assert states() == {
        "untouched": "open",
        "being-built": "in-progress",
        "tried": "attempted",
        "denied-once": "open (denied 1×)",   # a denial never closes an item
        "accepted-one": "accepted",
        "gone": "retired",
    }

    # the derivation is live: change only the REQ's status and the state follows, with no
    # edit to the backlog file at all.
    before = cfg.backlog_path.read_bytes()
    write_req(cfg.req_dir, "REQ-001", status="done", backlog_refs=["being-built"])
    assert states()["being-built"] == "attempted"
    assert cfg.backlog_path.read_bytes() == before

    # and taking a denied item up again outranks the past denial
    write_req(cfg.req_dir, "REQ-005", status="open", backlog_refs=["denied-once"])
    assert states()["denied-once"] == "in-progress"


def test_list_renders_the_attempt_record(cli_project):
    """AC5 — the operator can see which REQ tried and why the owner said no."""
    _run(cli_project, "backlog-add", "Easy", "--handle", "easy")
    write_req(cli_project / "reqs", "REQ-009", status="done", backlog_refs=["easy"])
    write_index(cli_project / "reqs", [("REQ-009", "t", "DONE", "–")])
    _run(cli_project, "backlog-deny", "easy", "--reason", "two clicks too many")

    r = _run(cli_project, "backlog-list")
    assert r.exit_code == 0, r.output
    assert "open (denied 1×)" in r.output
    assert "taken up by REQ-009" in r.output
    assert "two clicks too many" in r.output


# -- AC6 ----------------------------------------------------------------------


def test_new_stamps_a_backlog_whose_documented_grammar_parses(tmp_path):
    """AC6 — a fresh project gets the artifact, and the template is itself well-formed."""
    target = tmp_path / "fresh"
    r = CliRunner().invoke(main, ["new", str(target)], catch_exceptions=False)
    assert r.exit_code == 0, r.output
    path = target / "docs" / "BACKLOG.md"
    assert path.exists()
    text = path.read_text()
    assert bl.parse(text) == []          # stamped empty, not pre-populated
    assert "| Handle | Need | Origin |" in text
    # an item added to the stamped file lands in the table and round-trips
    spliced = bl.append_item(text, bl.Item("first-need", "The very first need.", "operator"))
    assert [i.handle for i in bl.parse(spliced)] == ["first-need"]


def test_sync_leaves_the_backlog_alone(tmp_path):
    """AC6 — the backlog is consumer *content*, so it never joins the tracked drift set."""
    from devsteward import skillsync

    target = tmp_path / "fresh"
    CliRunner().invoke(main, ["new", str(target)], catch_exceptions=False)
    path = target / "docs" / "BACKLOG.md"
    path.write_text(
        bl.append_item(path.read_text(), bl.Item("mine", "My own need.", "operator")),
        encoding="utf-8",
    )
    before = path.read_bytes()

    templates = Path(str(__import__("importlib.resources", fromlist=["files"]).files("devsteward"))) / "templates"
    skillsync.sync(target, templates, "docs/requirements")
    assert path.read_bytes() == before
    assert not any(
        "BACKLOG" in a.key for a in skillsync.tracked_artifacts(templates, "docs/requirements")
    )


# -- AC7 ----------------------------------------------------------------------


def test_drivesteward_corpus_parses_lints_and_rewrite_is_noop(tmp_path):
    """AC7 — the grammar survives a real corpus written before the grammar existed."""
    text = FIXTURE.read_text(encoding="utf-8")
    items = bl.parse(text)

    assert len(items) == 15
    assert sum(1 for i in items if i.origin == "operator") == 13
    assert sum(1 for i in items if i.origin == "proposed") == 2
    # the shapes that corpus actually contains
    assert any(i.need.count(".") >= 2 for i in items)              # multi-sentence need
    assert any("→" in i.need for i in items)                        # embedded fallback chain
    assert any(len(i.need) > 250 for i in items)                    # a long parenthetical need
    assert "## Notes on the seed" in text                           # prose *after* the table

    # every need survives verbatim
    assert items[0].need.startswith("The tool autostarts when booted from a stick")
    assert {i.handle for i in items} >= {"rapid-verdict", "measured-as-used", "drive-recognised"}

    # a rewrite that adds nothing changes nothing
    spliced = bl.append_item(text, bl.Item("temp", "Temp.", "operator"))
    assert spliced.replace("| temp | Temp. | operator |\n", "") == text

    # and it lints clean under a *non-default* backlog_file (REQ-084 seam)
    cfg = _project(
        tmp_path,
        backlog=text,
        backlog_file="planning/needs.md",
        reqs=[("REQ-019", "open", ["auto-smart-refresh", "drive-true-parameters"])],
    )
    assert lint(cfg) == [], lint(cfg)


def test_a_malformed_row_is_an_error_not_a_silent_drop():
    """AC7 — a dropped item is the exact failure this layer exists to prevent."""
    for bad, msg in (
        ("| Not A Handle | need | operator |\n", "kebab-case"),
        ("| ok-handle | need | shouted |\n", "origin"),
    ):
        with pytest.raises(bl.BacklogError, match=msg):
            bl.parse(TEMPLATE.replace("|---|---|---|\n", "|---|---|---|\n" + bad))


# -- item acceptance criteria (the stakeholder level) --------------------------


def test_criteria_are_scoped_to_their_section_and_must_name_a_real_item(tmp_path):
    """The owner's conditions of satisfaction attach to the item, not to the REQ.

    Scoped parsing matters: a project's ordinary prose headings must never be read as
    handles, or the linter would red on a heading that means nothing to this layer.
    """
    backlog = TEMPLATE.replace(
        "|---|---|---|\n",
        "|---|---|---|\n| easy-to-use | It should be easy. | operator |\n",
    ) + (
        "\n## Acceptance criteria\n\n"
        "### easy-to-use\n- I can do it in two clicks.\n- No manual needed.\n"
        "\n## Notes on the seed\n\n### not-a-handle\n- ordinary prose\n"
    )
    assert bl.parse_criteria(backlog) == {
        "easy-to-use": ["I can do it in two clicks.", "No manual needed."]
    }
    cfg = _project(tmp_path, backlog=backlog)
    assert lint(cfg) == [], lint(cfg)

    orphan = backlog.replace("### easy-to-use", "### vanished-need")
    cfg2 = _project(tmp_path / "d", backlog=orphan)
    assert any("'vanished-need'" in p for p in lint(cfg2)), lint(cfg2)


def test_the_verdict_surface_shows_the_criteria_being_judged(cli_project):
    """The owner is asked to judge against their own words, not against the REQ's tests."""
    _run(cli_project, "backlog-add", "It should be easy", "--handle", "easy-to-use")
    path = cli_project / "docs" / "BACKLOG.md"
    path.write_text(
        path.read_text()
        + "\n## Acceptance criteria\n\n### easy-to-use\n- I can do it in two clicks.\n",
        encoding="utf-8",
    )
    r = _run(cli_project, "backlog-deny", "easy-to-use", "--reason", "it takes four")
    assert r.exit_code == 0, r.output
    assert "I can do it in two clicks." in r.output
    assert "stays open" in r.output

    assert "I can do it in two clicks." in _run(cli_project, "backlog-list").output


def test_the_stamped_template_documents_the_criteria_convention(tmp_path):
    """A stamped project can author criteria without reading the engine's source."""
    target = tmp_path / "fresh"
    CliRunner().invoke(main, ["new", str(target)], catch_exceptions=False)
    text = (target / "docs" / "BACKLOG.md").read_text()
    assert "## Acceptance criteria" in text
    assert "before* translating" in text or "*before*" in text
    # the commented example must not itself register as an item's criteria
    assert bl.parse_criteria(text) == {}


def test_held_is_neither_open_nor_retired(cli_project):
    """The state DriveSteward's live corpus surfaced: parked with a reason, not withdrawn.

    `open` would read as available and `retired` as withdrawn; both lose the owner's ruling.
    Taking the item up lifts the hold, because a live REQ outranks a past verdict.
    """
    _run(cli_project, "backlog-add", "Measured as really used", "--handle", "measured-as-used")

    assert _run(cli_project, "backlog-hold", "measured-as-used").exit_code != 0  # needs a reason
    r = _run(cli_project, "backlog-hold", "measured-as-used",
             "--reason", "waiting on a reason to be believed, not on a session")
    assert r.exit_code == 0, r.output
    assert "the need stands" in r.output
    assert "held" in _run(cli_project, "backlog-list").output

    write_req(cli_project / "reqs", "REQ-030", status="open", backlog_refs=["measured-as-used"])
    write_index(cli_project / "reqs", [("REQ-030", "t", "OPEN", "–")])
    assert "in-progress" in _run(cli_project, "backlog-list").output
