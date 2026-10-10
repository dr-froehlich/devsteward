"""REQ-100 AC1–AC4 — a backlog item survives what the owner types.

The invariant these tests defend: **the backlog's writer and reader are an exact inverse
pair.** Whatever the owner types into the dashboard or passes to the CLI is either stored so
that it reads back as stored — folded to one line, ``|`` and comment markers intact — or the
write is refused and the file is left byte-for-byte as it was. The incident behind the REQ was
the third outcome: a write that succeeded and left a file nothing could read.

Every path goes through the real entrypoints: the Flask app's routes (as a browser posts a
textarea, CRLF line breaks included) and the click CLI with the project as cwd.
"""

from __future__ import annotations

import html as html_mod
import os
import re
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from devsteward.cli import _package_templates, main
from devsteward.config import load_config
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.profiles.req import backlog as bl

from conftest import write_index, write_req

pytest.importorskip("flask")  # the `dashboard` extra is a declared requirement of this gate

#: Every line boundary ``str.splitlines`` recognizes — each one used to split a row in two.
_BOUNDARIES = ["\r\n", "\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85",
               " ", " "]

_SEED = (
    "# Backlog\n\nSeed prose.\n\n| Handle | Need | Origin |\n|---|---|---|\n"
    "| before-it | Something before. | operator |\n"
    "| after-it | Something after. | proposed |\n\n"
    "## Acceptance criteria\n\n"
    "### before-it\n- A criterion before.\n\n"
    "### after-it\n- A criterion after.\n\n"
    # the stamped template's worked example — documentation, never content
    "<!-- Example:\n\n### rapid-verdict\n"
    "- In under five minutes I can see whether this drive is worth repairing.\n\n-->\n\n"
    "## Notes\n\nTrailing prose that must survive.\n"
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", *args],
        cwd=root, check=True, capture_output=True, text=True,
    )


@pytest.fixture
def base(tmp_path: Path) -> Path:
    """A root holding one stamped project, ``alpha``, whose lint is green before any write."""
    base = tmp_path / "projects"
    root = base / "alpha"
    root.mkdir(parents=True)
    Ledger.init(root, profile="req")
    (root / ".devsteward" / "config.yaml").write_text(
        "profile: req\nrequirements_dir: docs/requirements\n"
        "index_file: docs/requirements/REQUIREMENTS_INDEX.md\nbacklog_file: docs/BACKLOG.md\n"
        "accounts:\n  provider: single\n",
        encoding="utf-8",
    )
    cfg = load_config(root)
    write_req(cfg.req_dir, "REQ-001", status="done", backlog_refs=["before-it"])
    write_index(cfg.req_dir, [("REQ-001", "one", "DONE", "–")])
    cfg.backlog_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.backlog_path.write_text(_SEED, encoding="utf-8")
    led = Ledger(root)
    led.set_status("REQ-001:develop", StepStatus.DONE)
    led.save()
    _git(root, "init", "-q", "-b", "dev")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    return base


@pytest.fixture
def client(base: Path):
    from devsteward.dashboard.app import create_app

    template = (_package_templates() / "docs" / "BACKLOG.md").read_text(encoding="utf-8")
    app = create_app(base, templates_root=_package_templates(), backlog_template=template)
    app.config["TESTING"] = True
    return app.test_client()


def _cli(cwd: Path, *args: str):
    old = os.getcwd()
    os.chdir(cwd)
    try:
        return CliRunner().invoke(main, list(args))
    finally:
        os.chdir(old)


def _flash(resp) -> tuple[str, str]:
    """The action's flash: ``(ok|error, message)`` as the owner reads it."""
    page = resp.get_data(as_text=True)
    m = re.search(r'<div class="flash (ok|error)">(.*?)</div>', page, re.DOTALL)
    assert m, page[:500]
    return m.group(1), html_mod.unescape(m.group(2).strip())


def _page(client) -> str:
    """The project page with no action flash pending — any error div is a backlog error."""
    resp = client.get("/p/alpha")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _edit_form_need(page: str, handle: str) -> str:
    """The need exactly as the edit form's textarea offers it back to the owner."""
    m = re.search(
        rf'action="/p/alpha/backlog/{handle}/edit"[^>]*>\s*<label>Need</label>'
        r'<textarea name="need">(.*?)</textarea>',
        page, re.DOTALL,
    )
    assert m, f"no edit form for {handle}"
    return html_mod.unescape(m.group(1))


def _items(path: Path) -> dict[str, bl.Item]:
    return {i.handle: i for i in bl.parse(path.read_text(encoding="utf-8"))}


# -- AC1 ---------------------------------------------------------------------------


def test_multiline_need_and_criterion_fold_to_one_line_via_dashboard_and_cli(base, client):
    proj = base / "alpha"
    path = proj / "docs" / "BACKLOG.md"

    # the dashboard's add form, as a browser submits a textarea: CRLF and a blank line
    typed = "Handover works like this:\r\n\r\n  run the command\r\nthen wait."
    folded = "Handover works like this: run the command then wait."
    r = client.post("/p/alpha/backlog/add", data={"need": typed, "handle": "typed-in-ui"},
                    follow_redirects=True)
    assert _flash(r) == ("ok", f"+ typed-in-ui — {folded}")

    # the dashboard's edit form, LF
    r = client.post("/p/alpha/backlog/before-it/edit",
                    data={"need": "Reworded\nover two lines.", "origin": "operator",
                          "criteria": "- A criterion before.\n"}, follow_redirects=True)
    assert _flash(r) == ("ok", "~ before-it — Reworded over two lines. [operator]")

    # the CLI, once per line boundary the reader splits on
    for n, ch in enumerate(_BOUNDARIES):
        res = _cli(proj, "backlog-add", "--handle", f"cli-{n}", f"left{ch}{ch}  right")
        assert res.exit_code == 0, (repr(ch), res.output)
        assert res.output.rstrip().endswith("— left right"), res.output

    # a criterion typed over several lines loses no words
    res = _cli(proj, "backlog-edit", "after-it",
               "--criterion", "first half\n  second half", "--criterion", "next one")
    assert res.exit_code == 0, res.output

    text = path.read_text(encoding="utf-8")
    assert not any(ch in text for ch in "\r\x0b\x0c\x1c\x1d\x1e\x85  ")
    items = _items(path)
    lines = text.splitlines()
    for item in items.values():  # one item, one line: the row holds its handle and whole need
        assert lines[item.line].startswith(f"| {item.handle} |"), lines[item.line]
        assert lines[item.line].endswith(f"| {item.origin} |"), lines[item.line]
    assert items["typed-in-ui"].need == folded
    assert items["before-it"].need == "Reworded over two lines."
    assert all(items[f"cli-{n}"].need == "left right" for n in range(len(_BOUNDARIES)))
    assert bl.parse_criteria(text)["after-it"] == ["first half second half", "next one"]
    assert "- first half second half\n- next one\n" in text

    page = _page(client)
    assert 'class="flash error"' not in page
    assert folded in html_mod.unescape(page)
    res = _cli(proj, "lint")
    assert res.exit_code == 0, res.output


# -- AC2 ---------------------------------------------------------------------------


def test_pipe_in_need_round_trips_without_drift(base, client):
    proj = base / "alpha"
    path = proj / "docs" / "BACKLOG.md"
    typed = "Either a | b, or a literal \\| kept as typed."

    assert _cli(proj, "backlog-add", "--handle", "piped", typed).exit_code == 0
    assert _items(path)["piped"].need == typed

    # three rewrites, alternating the surfaces; the dashboard posts back what its form shows
    for k, surface in enumerate(("dashboard", "cli", "dashboard")):
        origin = ("proposed", "operator")[k % 2]
        if surface == "dashboard":
            offered = _edit_form_need(_page(client), "piped")
            assert offered == typed  # the edit form offers the need as typed, no `\|`
            r = client.post("/p/alpha/backlog/piped/edit",
                            data={"need": offered, "origin": origin, "criteria": ""},
                            follow_redirects=True)
            assert _flash(r)[0] == "ok"
        else:
            res = _cli(proj, "backlog-edit", "piped", "--origin", origin)
            assert res.exit_code == 0, res.output
        item = _items(path)["piped"]
        assert (item.need, item.origin) == (typed, origin), f"rewrite {k + 1}"

    # on disk: exactly one escape per pipe, however many rewrites
    assert "| piped | Either a \\| b, or a literal \\\\| kept as typed. | proposed |" in (
        path.read_text(encoding="utf-8")
    )
    page = html_mod.unescape(_page(client))
    assert typed in page
    assert "a \\| b" not in page
    assert _cli(proj, "lint").exit_code == 0


# -- AC3 ---------------------------------------------------------------------------


def test_comment_markers_in_need_and_criterion_round_trip(base, client):
    proj = base / "alpha"
    path = proj / "docs" / "BACKLOG.md"
    needs = {
        "opener": "Mention <!-- in passing and keep going.",
        "closer": "An arrow --> right here.",
        "both": "Inline <!-- note --> and the words after it.",
    }
    for handle, need in needs.items():
        r = client.post("/p/alpha/backlog/add", data={"need": need, "handle": handle},
                        follow_redirects=True)
        assert _flash(r)[0] == "ok"
    assert _cli(proj, "backlog-add", "--handle", "trailing-item", "Added last.").exit_code == 0

    # an item with an item after it, rewritten through the CLI, criteria included
    criteria = ["Opens <!-- here and goes on.", "Closes --> here.", "Both <!-- x --> here."]
    res = _cli(proj, "backlog-edit", "before-it", "--need", "Before, with <!-- an opener.",
               *[a for c in criteria for a in ("--criterion", c)])
    assert res.exit_code == 0, res.output
    # and the same marker through the dashboard's criteria textarea
    r = client.post("/p/alpha/backlog/opener/edit",
                    data={"need": needs["opener"], "origin": "operator",
                          "criteria": "- Mine has <!-- one too.\n- And a second line.\n"},
                    follow_redirects=True)
    assert _flash(r)[0] == "ok"

    text = path.read_text(encoding="utf-8")
    items = _items(path)
    assert [h for h in items] == ["before-it", "after-it", "opener", "closer", "both",
                                  "trailing-item"]
    for handle, need in needs.items():
        assert items[handle].need == need
    assert items["before-it"].need == "Before, with <!-- an opener."
    assert items["after-it"].need == "Something after."
    got = bl.parse_criteria(text)
    assert got["before-it"] == criteria
    assert got["after-it"] == ["A criterion after."]
    assert got["opener"] == ["Mine has <!-- one too.", "And a second line."]
    assert "rapid-verdict" not in got  # the commented example is still documentation

    page = html_mod.unescape(_page(client))
    assert all(need in page for need in needs.values())
    assert _cli(proj, "lint").exit_code == 0


# -- AC4 ---------------------------------------------------------------------------


def test_write_that_would_not_read_back_is_refused_and_the_file_untouched(
    base, client, monkeypatch
):
    proj = base / "alpha"
    cfg = load_config(proj)
    path = cfg.backlog_path
    snapshot = path.read_bytes()

    # a broken cell encoder: it emits a raw line break for every space in a value
    real_cell = bl._cell
    monkeypatch.setattr(bl, "_cell", lambda value: real_cell(value).replace(" ", "\n"))

    with pytest.raises(bl.BacklogError, match="refused to write docs/BACKLOG.md"):
        bl.add(cfg, "two words", handle="broken")
    assert path.read_bytes() == snapshot

    for args in (("backlog-add", "--handle", "broken", "two words"),
                 ("backlog-edit", "before-it", "--need", "two words"),
                 ("backlog-edit", "before-it", "--origin", "proposed")):
        res = _cli(proj, *args)
        assert res.exit_code != 0, args
        assert "refused to write docs/BACKLOG.md" in res.output
        assert "the file is unchanged" in res.output
        assert path.read_bytes() == snapshot

    r = client.post("/p/alpha/backlog/add", data={"need": "two\r\nwords", "handle": "broken"},
                    follow_redirects=True)
    kind, msg = _flash(r)
    assert kind == "error" and msg.startswith("backlog-add: refused to write docs/BACKLOG.md")
    assert 'class="flash ok"' not in r.get_data(as_text=True)
    r = client.post("/p/alpha/backlog/before-it/edit",
                    data={"need": "two words", "origin": "operator", "criteria": ""},
                    follow_redirects=True)
    kind, msg = _flash(r)
    assert kind == "error" and msg.startswith("backlog-edit before-it: refused to write")
    assert path.read_bytes() == snapshot

    # the other half of the check: a file that parses but would hand back different text
    monkeypatch.undo()
    monkeypatch.setattr(bl, "_uncell", lambda value: value)
    with pytest.raises(bl.BacklogError, match="item 'piped' would not read back as written"):
        bl.add(cfg, "a | b", handle="piped")
    assert path.read_bytes() == snapshot
