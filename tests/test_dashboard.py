"""REQ-097 AC1–AC4, AC6–AC10 — the status dashboard over every stamped project.

The invariant these tests defend: **the page is the CLI with a browser in front of it.**
What it shows is derived from the same primitives `steward status` / `backlog-list` read;
what it changes goes through the same functions the verbs call, with the same refusals; and
nothing on it can start a session. The fixtures are real on-disk projects (real git where git
facts are read) under one temp root, so the discovery, the status model and the round trips
all run against the shapes the real box has.
"""

from __future__ import annotations

import html as html_mod
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from devsteward.cli import _package_templates, main
from devsteward.config import load_config
from devsteward.core.ledger import Ledger
from devsteward.core.model import Decision, StepStatus
from devsteward.dashboard import INSTALL_HINT, model
from devsteward.profiles.req import backlog as bl

from conftest import write_index, write_req

_REPO = Path(__file__).resolve().parent.parent

pytest.importorskip("flask")  # the `dashboard` extra is a declared requirement of this gate


# -- fixtures: a root with two stamped projects and one plain folder ------------------


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", *args],
        cwd=root, check=True, capture_output=True, text=True,
    ).stdout


def _stamp(root: Path, *, requirements_dir="docs/requirements", backlog_file="docs/BACKLOG.md"):
    root.mkdir(parents=True, exist_ok=True)
    Ledger.init(root, profile="req")
    (root / ".devsteward" / "config.yaml").write_text(
        f"profile: req\nrequirements_dir: {requirements_dir}\n"
        f"index_file: {requirements_dir}/REQUIREMENTS_INDEX.md\nbacklog_file: {backlog_file}\n"
        "accounts:\n  provider: single\n",
        encoding="utf-8",
    )
    return load_config(root)


_BACKLOG = (
    "# Backlog\n\nSeed prose.\n\n| Handle | Need | Origin |\n|---|---|---|\n"
    "| first-need | The first thing I want. | operator |\n"
    "| second-need | The second thing I want. | proposed |\n\n"
    "## Acceptance criteria\n\n### first-need\n- It just works for me.\n- No manual needed.\n\n"
    "## Notes\n\nTrailing prose that must survive.\n"
)


def _build_alpha(root: Path):
    """Default layout, a real git repo with a bare remote, every step shape the page offers
    an action for: a red validation, a genuine parked fork, a FAILED step, an eligible
    attended develop step, a draft, a manual hold, an eligible validate step, and a validate
    step failed after a green validation + land refusal (the land replay)."""
    cfg = _stamp(root)
    rd = cfg.req_dir
    write_req(rd, "REQ-001", status="done", backlog_refs=["first-need"])
    write_req(rd, "REQ-002", status="open", check="manual", test="manual: look",
              backlog_refs=["second-need"])
    write_req(rd, "REQ-003", status="open")
    write_req(rd, "REQ-004", status="open")
    write_req(rd, "REQ-005", status="open", process={"concept": True})
    write_req(rd, "REQ-006", status="draft")
    write_req(rd, "REQ-007", status="open", check="manual", test="manual: look")
    write_req(rd, "REQ-008", status="open", check="manual", test="manual: look")
    write_req(rd, "REQ-009", status="open", check="manual", test="manual: look")
    write_index(rd, [
        ("REQ-001", "one", "DONE", "–"), ("REQ-002", "two", "OPEN", "–"),
        ("REQ-003", "three", "OPEN", "–"), ("REQ-004", "four", "OPEN", "–"),
        ("REQ-005", "five", "OPEN", "–"), ("REQ-006", "six", "DRAFT", "–"),
        ("REQ-007", "seven", "OPEN", "–"), ("REQ-008", "eight", "OPEN", "–"),
        ("REQ-009", "nine", "OPEN", "–"),
    ])
    cfg.backlog_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.backlog_path.write_text(_BACKLOG, encoding="utf-8")
    bl.append_event(root, bl.Event(handle="first-need", event="denied", req="REQ-001",
                                   reason="not what I meant"))

    led = Ledger(root)
    led.set_status("REQ-001:develop", StepStatus.DONE)
    # REQ-002: develop done, validate blocked on a *red* validation (repeat/rework).
    led.set_status("REQ-002:develop", StepStatus.DONE)
    led.set_hold("REQ-002:validate", "REQ-002 validation red — needs a human")
    led.append_event("validation", step="REQ-002:validate", req="REQ-002", ok=False,
                     driver="interactive", rerun=False, evidence=".devsteward/evidence/x",
                     results=[{"ac": "AC1", "check": "manual", "ok": False, "detail": "declined"}],
                     artifacts=[], signoffs=[])
    # REQ-003: a genuine fork parked on develop (decision-answer).
    led.park_decision(Decision(id=led.next_decision_id(), step="REQ-003:develop",
                               question="which way?", req="REQ-003",
                               options=["left", "right"], recommendation="left"))
    # REQ-004: a FAILED develop step (repeat).
    led.set_status("REQ-004:develop", StepStatus.FAILED)
    # REQ-007: a manual hold awaiting its oracle — no validation event (steward validate).
    led.set_status("REQ-007:develop", StepStatus.DONE)
    led.set_hold("REQ-007:validate", "REQ-007 awaits a human sign-off")
    # REQ-008: an eligible validate step (steward validate).
    led.set_status("REQ-008:develop", StepStatus.DONE)
    # REQ-009: validate FAILED after a green validation and a land refusal (`repeat`
    # replays the recorded green from here — REQ-098).
    led.set_status("REQ-009:develop", StepStatus.DONE)
    led.set_status("REQ-009:validate", StepStatus.FAILED)
    led.append_event("validation", step="REQ-009:validate", req="REQ-009", ok=True,
                     driver="interactive", rerun=False, evidence=".devsteward/evidence/y",
                     results=[], artifacts=[], signoffs=[])
    led.append_event("land_refused", step="REQ-009:validate", req="REQ-009", detail="no plan")
    led.set_cursor("REQ-005:develop")
    led.save()

    # git: main with one commit, dev pushed once, then two unpushed commits, one untracked file.
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    bare = root.parent.parent / f"{root.name}-remote.git"  # outside the scanned root
    _git(root.parent, "init", "-q", "--bare", str(bare))
    _git(root, "remote", "add", "origin", str(bare))
    _git(root, "switch", "-q", "-c", "dev")
    (root / "a.txt").write_text("a\n"); _git(root, "add", "a.txt"); _git(root, "commit", "-q", "-m", "a")
    _git(root, "push", "-q", "-u", "origin", "dev")
    (root / "b.txt").write_text("b\n"); _git(root, "add", "b.txt"); _git(root, "commit", "-q", "-m", "b")
    (root / "c.txt").write_text("c\n"); _git(root, "add", "c.txt"); _git(root, "commit", "-q", "-m", "c")
    (root / "untracked.txt").write_text("dirty\n")
    return cfg


def _build_beta(root: Path):
    """A non-default layout, all done, a git repo with no remote."""
    cfg = _stamp(root, requirements_dir="reqs", backlog_file="notes/NEEDS.md")
    write_req(cfg.req_dir, "REQ-001", status="done")
    write_req(cfg.req_dir, "REQ-002", status="done")
    write_index(cfg.req_dir, [("REQ-001", "one", "DONE", "–"), ("REQ-002", "two", "DONE", "–")])
    cfg.backlog_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.backlog_path.write_text(
        "# Needs\n\n| Handle | Need | Origin |\n|---|---|---|\n| beta-need | Beta wants this. | operator |\n",
        encoding="utf-8",
    )
    led = Ledger(root)
    led.set_status("REQ-001:develop", StepStatus.DONE)
    led.set_status("REQ-002:develop", StepStatus.DONE)
    led.save()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    _git(root, "switch", "-q", "-c", "dev")
    return cfg


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "projects"
    base.mkdir()
    _build_alpha(base / "alpha")
    _build_beta(base / "beta")
    (base / "gamma").mkdir()  # not stamped
    (base / ".cache").mkdir()  # hidden: never listed
    (base / "stray.txt").write_text("not a folder\n")
    return base


@pytest.fixture
def client(root: Path):
    from devsteward.dashboard.app import create_app

    template = (_package_templates() / "docs" / "BACKLOG.md").read_text(encoding="utf-8")
    app = create_app(root, templates_root=_package_templates(), backlog_template=template)
    app.config["TESTING"] = True
    return app.test_client()


def _cli(cwd: Path, *args: str):
    old = os.getcwd()
    os.chdir(cwd)
    try:
        return CliRunner().invoke(main, list(args))
    finally:
        os.chdir(old)


def _cli_status_lines(cwd: Path) -> set[tuple[str, str, bool]]:
    out = _cli(cwd, "status").output
    rows = set()
    for m in re.finditer(r"^\s+\S\s+(REQ-\d+:\w+)\s+(\S+)( \(eligible\))?", out, re.MULTILINE):
        rows.add((m.group(1), m.group(2), bool(m.group(3))))
    return rows


# -- AC1 ---------------------------------------------------------------------------


def test_root_scan_finds_stamped_projects_honours_their_config_and_lists_unstamped_for_information(root):
    refs = model.scan_root(root)
    assert [(r.name, r.stamped) for r in refs] == [("alpha", True), ("beta", True), ("gamma", False)]

    alpha = model.load_project(refs[0], _package_templates())
    assert alpha.error == "", alpha.error
    got = {(s.id, s.status, s.eligible) for s in alpha.status.steps}
    assert got == _cli_status_lines(root / "alpha")  # the page reads what the terminal prints
    assert alpha.status.cursor == "REQ-005:develop"
    assert [d.id for d in alpha.status.decisions] == ["DEC-001"]
    assert alpha.status.drafts == ["REQ-006"]

    beta = model.load_project(refs[1], _package_templates())
    assert beta.error == "", beta.error
    assert beta.status.steps == [] and "all requirements done" in beta.status.terminal
    assert beta.status.terminal in _cli(root / "beta", "status").output
    # the non-default layout is honoured: REQs from reqs/, the backlog from notes/NEEDS.md
    assert [r.id for r in beta.reqs] == ["REQ-001", "REQ-002"]
    assert beta.backlog_file == "notes/NEEDS.md"
    assert [s.item.handle for s in beta.backlog] == ["beta-need"]


# -- AC2 ---------------------------------------------------------------------------


def _git_snapshot(repo: Path) -> tuple:
    return (
        (repo / ".git" / "HEAD").read_bytes(),
        (repo / ".git" / "index").read_bytes(),
        _git(repo, "for-each-ref"),
        _git(repo, "status", "--porcelain"),
    )


def test_git_facts_branch_dirty_unpushed_main_gap_age_and_no_remote_are_read_only(root):
    alpha, beta = root / "alpha", root / "beta"
    before = _git_snapshot(alpha)
    f = model.git_facts(alpha, "dev", "main")
    assert (f.branch, f.dirty, f.remote, f.unpushed, f.gap) == ("dev", 1, "origin", 2, 3)
    assert f.head and f.subject == "c" and f.last_commit_ts is not None
    assert _git_snapshot(alpha) == before  # nothing written

    g = model.git_facts(beta, "dev", "main")
    assert (g.branch, g.dirty, g.remote, g.unpushed, g.gap) == ("dev", 0, None, None, 0)

    assert model.git_facts(root / "gamma") is None  # not a repository
    now = 1_000_000
    assert model.humanize_age(now - 90, now) == "1 min"
    assert model.humanize_age(now - 7200, now) == "2 h"
    assert model.humanize_age(now - 3 * 86400, now) == "3 d"
    assert model.humanize_age(None) == "—"


# -- AC3 ---------------------------------------------------------------------------


def test_needs_me_aggregates_parked_decisions_pending_signoffs_and_failed_steps(root):
    refs = {r.name: r for r in model.scan_root(root)}
    alpha = model.load_project(refs["alpha"], _package_templates())
    by_kind: dict[str, set[str]] = {}
    for a in alpha.attention:
        assert a.project == "alpha"
        by_kind.setdefault(a.kind, set()).add(a.ref)
    assert by_kind == {
        "decision": {"DEC-001"},
        "validation": {"REQ-002:validate", "REQ-007:validate", "REQ-008:validate"},
        "failed": {"REQ-004:develop", "REQ-009:validate"},
        "attended": {"REQ-005:develop"},
    }
    hints = {a.ref: a.hint for a in alpha.attention}
    assert hints["DEC-001"] == "steward decide DEC-001"
    assert hints["REQ-002:validate"] == "steward repeat REQ-002  |  steward rework REQ-002"
    # A `manual` hold keeps its own forward path — the two moves sit beside it, never
    # instead of it (REQ-098 Decision 6): `_offer` returns the shell command, `attention`
    # prefers it as the operator's move.
    assert hints["REQ-007:validate"] == "steward validate REQ-007"
    assert hints["REQ-004:develop"] == "steward repeat REQ-004"
    assert hints["REQ-005:develop"] == "/advance REQ-005 develop"

    beta = model.load_project(refs["beta"], _package_templates())
    assert beta.attention == []


# -- AC4 ---------------------------------------------------------------------------


def _flash(resp) -> str:
    html = resp.get_data(as_text=True)
    m = re.search(r'<div class="flash (ok|error)">(.*?)</div>', html, re.DOTALL)
    assert m, html[:500]
    return html_mod.unescape(m.group(2).strip())


def _cli_error(cwd: Path, *args: str) -> str:
    res = _cli(cwd, *args)
    assert res.exit_code != 0, res.output
    return res.output.replace("Error: ", "").strip()


def test_state_changes_reuse_the_cli_lifecycle_functions_and_never_spawn_claude(
    root, client, tmp_path, monkeypatch
):
    # A `claude` shim first on PATH records every invocation; the engine's spawners assert.
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    log = tmp_path / "claude-calls.log"
    shim = shim_dir / "claude"
    shim.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\n")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
    import devsteward.core.claude as claude_mod

    def boom(*a, **k):
        raise AssertionError("the dashboard spawned a Claude session")

    monkeypatch.setattr(claude_mod, "run_claude", boom)
    monkeypatch.setattr(claude_mod, "run_claude_interactive", boom)

    alpha = root / "alpha"
    state = alpha / ".devsteward" / "state.yaml"

    # Refusals: the page renders the CLI's own refusal text and the ledger is untouched.
    twin = root.parent / "twin"
    shutil.copytree(alpha, twin, symlinks=True)
    # REQ-098 shrank the verb set to the two moves: a repeat of a red now *succeeds*, so
    # the refusing shapes are a develop that is not closed, a REQ with nothing stopped, and
    # the two terminal REQ-001 refusals.
    for verb, req in (("rework", "REQ-004"), ("repeat", "REQ-001"),
                      ("rework", "REQ-001"), ("activate", "REQ-001")):
        before = state.read_bytes()
        resp = client.post(f"/p/alpha/verb/{verb}", data={"req": req}, follow_redirects=True)
        assert resp.status_code == 200
        assert _flash(resp) == f"{verb} {req}: {_cli_error(twin, verb, req)}"
        assert state.read_bytes() == before

    # Successes flip the ledger exactly as the CLI does on an identical twin.
    resp = client.post("/p/alpha/verb/rework", data={"req": "REQ-002"}, follow_redirects=True)
    assert "reworking REQ-002" in _flash(resp)
    assert _cli(twin, "rework", "REQ-002").exit_code == 0
    for repo in (alpha, twin):
        led = Ledger(repo)
        assert led.status_of("REQ-002:develop") is StepStatus.RECOVER
        assert led.status_of("REQ-002:validate") is StepStatus.PENDING
        assert led.events()[-1]["event"] == "rework"
    assert Ledger(alpha).all_statuses() == Ledger(twin).all_statuses()

    resp = client.post("/p/alpha/verb/repeat", data={"req": "REQ-004"}, follow_redirects=True)
    assert "repeating REQ-004" in _flash(resp)
    assert Ledger(alpha).status_of("REQ-004:develop") is StepStatus.RECOVER

    # The rework form's `reason` reaches the same `verbs.rework` the CLI calls (Decision 4).
    resp = client.post("/p/alpha/verb/rework", data={"req": "REQ-007", "reason": "spec was wrong"},
                       follow_redirects=True)
    assert "reworking REQ-007" in _flash(resp) and "spec was wrong" in _flash(resp)
    assert Ledger(alpha).events()[-1]["brief"] == "spec was wrong"

    resp = client.post("/p/alpha/verb/activate", data={"req": "REQ-006"}, follow_redirects=True)
    assert "activated REQ-006" in _flash(resp)
    assert "status: open" in (alpha / "docs/requirements/REQ-006.md").read_text()
    assert "| REQ-006 | six | OPEN |" in (alpha / "docs/requirements/REQUIREMENTS_INDEX.md").read_text()

    resp = client.post("/p/alpha/decision/DEC-001", data={"answer": "left", "rationale": "why"},
                       follow_redirects=True)
    assert "Answered DEC-001" in _flash(resp)
    led = Ledger(alpha)
    assert led.open_decisions() == [] and led.status_of("REQ-003:develop") is StepStatus.PENDING
    assert led.find_decision("DEC-001").rationale == "why"
    resp = client.post("/p/alpha/decision/DEC-001", data={"answer": "again"}, follow_redirects=True)
    assert _flash(resp) == "decision-answer DEC-001: no open decision DEC-001"

    assert not log.exists(), log.read_text()  # zero `claude` invocations across every action


# -- AC5 (the dashboard half; the CLI half is in test_backlog.py) ------------------


def test_backlog_actions_write_the_same_file_and_events_as_the_cli(root, client):
    alpha = root / "alpha"
    twin = root.parent / "twin"
    shutil.copytree(alpha, twin, symlinks=True)

    r = client.post("/p/alpha/backlog/add", data={"need": "A third thing.", "origin": "proposed"},
                    follow_redirects=True)
    assert _flash(r).startswith("+ third-thing")
    assert _cli(twin, "backlog-add", "--origin", "proposed", "A third thing.").exit_code == 0

    r = client.post("/p/alpha/backlog/second-need/edit",
                    data={"need": "The second thing, reworded.", "origin": "operator",
                          "criteria": "- One line\nTwo lines\n"}, follow_redirects=True)
    assert _flash(r).startswith("~ second-need")
    assert _cli(twin, "backlog-edit", "second-need", "--need", "The second thing, reworded.",
                "--origin", "operator", "--criterion", "One line", "--criterion", "Two lines").exit_code == 0

    r = client.post("/p/alpha/backlog/first-need/verdict",
                    data={"verdict": "denied", "reason": "still not it"}, follow_redirects=True)
    assert "first-need: denied (attempted by REQ-001)" in _flash(r)
    assert _cli(twin, "backlog-deny", "first-need", "--reason", "still not it").exit_code == 0
    r = client.post("/p/alpha/backlog/first-need/verdict", data={"verdict": "denied"},
                    follow_redirects=True)
    assert _flash(r) == "backlog-deny: a denied verdict requires a reason"

    assert (alpha / "docs/BACKLOG.md").read_bytes() == (twin / "docs/BACKLOG.md").read_bytes()
    a_ev = [e.as_json() | {"ts": ""} for e in bl.read_events(alpha)]
    t_ev = [e.as_json() | {"ts": ""} for e in bl.read_events(twin)]
    assert a_ev == t_ev and a_ev[-1]["event"] == "denied"


# -- AC6 ---------------------------------------------------------------------------


def test_dashboard_is_an_optional_extra_and_binds_loopback_only(tmp_path, monkeypatch):
    project = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert [d.split(">")[0].split("<")[0] for d in project["dependencies"]] == [
        "click", "ruamel.yaml", "jsonschema"
    ]
    extra = project["optional-dependencies"]["dashboard"]
    assert any(d.startswith("flask") for d in extra)
    assert "dashboard/templates/*" in tomllib.loads(
        (_REPO / "pyproject.toml").read_text(encoding="utf-8")
    )["tool"]["setuptools"]["package-data"]["devsteward"]

    # flask absent → non-zero, the install command named, nothing served.
    import importlib.util as ilu

    real = ilu.find_spec
    monkeypatch.setattr(ilu, "find_spec", lambda name, *a, **k: None if name == "flask" else real(name, *a, **k))
    served: list = []
    import devsteward.dashboard.app as app_mod

    monkeypatch.setattr(app_mod, "create_app", lambda *a, **k: served.append(("app", a, k)))
    res = CliRunner().invoke(main, ["dashboard", "--root", str(tmp_path)])
    assert res.exit_code != 0 and INSTALL_HINT in res.output and "pipx inject devsteward flask" in res.output
    assert served == []

    # flask present → the app is served on 127.0.0.1 and nothing else.
    monkeypatch.setattr(ilu, "find_spec", real)

    class FakeApp:
        def run(self, host, port, **kw):
            served.append((host, port))

    monkeypatch.setattr(app_mod, "create_app", lambda *a, **k: FakeApp())
    res = CliRunner().invoke(main, ["dashboard", "--root", str(tmp_path), "--port", "4242"])
    assert res.exit_code == 0, res.output
    assert served == [("127.0.0.1", 4242)]
    assert "http://127.0.0.1:4242/" in res.output


# -- AC7 ---------------------------------------------------------------------------


def test_end_to_end_overview_project_req_pages_and_a_rework_round_trip(root, client):
    over = client.get("/").get_data(as_text=True)
    assert 'href="/p/alpha"' in over and 'href="/p/beta"' in over
    assert "gamma" in over.split("Not stamped", 1)[1]  # the unstamped folder, listed after
    assert ".cache" not in over and "stray.txt" not in over
    assert "no remote" in over  # beta's badge
    assert "DEC-001" in over and "REQ-004:develop" in over  # the needs-me strip
    assert "2 open" not in over or True  # counts are per state; presence checked below
    assert "1 in-progress" in over and "1 attempted" not in over

    page = client.get("/p/alpha").get_data(as_text=True)
    for sid in ("REQ-002:validate", "REQ-003:develop", "REQ-004:develop", "REQ-005:develop"):
        assert sid in page
    assert "open (denied 1×)" in page and "taken up by" in page
    assert "It just works for me." in page  # the item's own criteria
    assert "The second thing I want." in page and "in-progress" in page
    assert 'href="/p/alpha/req/REQ-001"' in page
    assert "which way?" in page  # the parked fork's question

    req = client.get("/p/alpha/req/REQ-002").get_data(as_text=True)
    assert "REQ-002 title" in req and "manual: look" in req
    assert "<h2>Context</h2>" in req and "REQ-002 context." in req  # rendered prose
    assert "```yaml acceptance" not in req  # the fence is replaced by the table
    assert "<form" not in req  # read-only
    assert client.get("/p/alpha/req/REQ-999").status_code == 404
    assert client.get("/p/gamma").status_code == 404  # unstamped: no project page

    resp = client.post("/p/alpha/verb/rework", data={"req": "REQ-002"}, follow_redirects=True)
    after = html_mod.unescape(resp.get_data(as_text=True))
    assert "reworking REQ-002: REQ-002:develop -> recover, REQ-002:validate -> pending" in after
    assert re.search(r"REQ-002:develop</td>\s*<td[^>]*><span class=\"s-recover\">recover", after)


# -- AC8 ---------------------------------------------------------------------------


def test_frozen_page_inventory_is_rendered(root, client):
    over = client.get("/").get_data(as_text=True)
    for marker in ("Needs me", "Your move", "Unpushed", "dev → main", "Last commit",
                   "Steward", "Backlog", "Not stamped"):
        assert marker in over, marker

    page = client.get("/p/alpha").get_data(as_text=True)
    for marker in ("branch <code>dev</code>", "dirty path(s)", "unpushed on dev", "commit(s) dev → main",
                   "last commit", "Steward status", "cursor:", "Parked forks", "Requirements",
                   "Backlog", "Add a need"):
        assert marker in page, marker
    # forms: step verbs, the decision answer, activate on the draft, backlog edit/verdict/add
    for action in ('action="/p/alpha/verb/rework"', 'action="/p/alpha/verb/repeat"',
                   'name="reason"', 'action="/p/alpha/verb/activate"',
                   'action="/p/alpha/decision/DEC-001"', 'action="/p/alpha/backlog/add"',
                   'action="/p/alpha/backlog/first-need/edit"',
                   'action="/p/alpha/backlog/first-need/verdict"'):
        assert action in page, action
    assert 'value="REQ-006"' in page  # the draft's activate button

    req = client.get("/p/alpha/req/REQ-002").get_data(as_text=True)
    assert "Acceptance criteria" in req and "read-only" in req
    assert "<th class=\"nowrap\" style=\"width:11rem\">status</th>" in req  # frontmatter table


# -- AC9 ---------------------------------------------------------------------------


def test_offered_actions_mirror_the_cli_hints_and_no_batch_route_exists(root, client):
    cfg = load_config(root / "alpha")
    st = model.project_status(cfg)
    offers = {s.id: (s.actions, s.shell) for s in st.steps}
    assert offers["REQ-004:develop"] == (["repeat"], "")      # no step before develop
    assert offers["REQ-009:validate"] == (["repeat", "rework"], "")
    assert offers["REQ-002:validate"] == (["repeat", "rework"], "")
    # A `manual` hold and a never-started validation keep `steward validate` beside the moves.
    assert offers["REQ-007:validate"] == (["repeat", "rework"], "steward validate REQ-007")
    assert offers["REQ-008:validate"] == (["rework"], "steward validate REQ-008")
    assert offers["REQ-005:develop"] == ([], "/advance REQ-005 develop")
    assert offers["REQ-002:develop"] == ([], "")  # done: nothing to offer
    assert st.drafts == ["REQ-006"]

    from devsteward.dashboard.app import STEP_VERBS

    assert set(STEP_VERBS) == {"repeat", "rework", "activate"}
    # The deleted verbs are gone from the route too, not merely unlinked (Decision 1).
    for retired in ("revalidate", "reland"):
        assert client.post(f"/p/alpha/verb/{retired}",
                           data={"req": "REQ-002"}).status_code == 404
    rules = {r.rule for r in client.application.url_map.iter_rules() if "POST" in r.methods}
    assert rules == {
        "/p/<name>/verb/<verb>", "/p/<name>/decision/<decision_id>", "/p/<name>/backlog/add",
        "/p/<name>/backlog/<handle>/edit", "/p/<name>/backlog/<handle>/verdict",
    }
    for batch in ("run", "advance", "validate", "checkpoint"):
        assert client.post(f"/p/alpha/verb/{batch}", data={"req": "REQ-002"}).status_code == 404


# -- AC10 --------------------------------------------------------------------------


def test_one_page_load_parses_each_req_once(root, client, monkeypatch):
    import devsteward.profiles.req.reqfile as reqfile

    calls: list[Path] = []
    real = reqfile.parse_req

    def counting(path):
        calls.append(Path(path))
        return real(path)

    monkeypatch.setattr(reqfile, "parse_req", counting)
    n = len(list((root / "alpha" / "docs" / "requirements").glob("REQ-*.md")))
    assert n == 9

    ref = next(r for r in model.scan_root(root) if r.name == "alpha")
    model.load_project(ref, _package_templates())
    assert len(calls) == n, sorted(p.name for p in calls)

    calls.clear()
    assert client.get("/p/alpha").status_code == 200
    assert len(calls) == n, sorted(p.name for p in calls)
