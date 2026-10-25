"""REQ-102 AC1–AC4 — a non-governed repository joins joint tasks as a joint-only participant.

The invariant these tests defend: **the governed side cannot tell, and the REQ workflow keeps
out.** A repository joins with one file, the REQ verbs refuse to touch it, the dashboard shows
it without REQ sections, and a governed project works a thread with it in both directions
using nothing but REQ-101's verbs and options — the take-up of a request it sends is read from
the participant's own acknowledgement. The fixtures are real on-disk folders under one temp
root, joined through the real `steward new --profile joint`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from devsteward.cli import _package_templates, main
from devsteward.config import load_config
from devsteward.core.ledger import Ledger
from devsteward.profiles.req import joint

from conftest import write_req


# -- fixtures --------------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", *args],
        cwd=root, check=True, capture_output=True, text=True,
    ).stdout


def _stamp(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    Ledger.init(root, profile="req")
    (root / ".devsteward" / "config.yaml").write_text(
        "profile: req\nrequirements_dir: docs/requirements\n"
        "index_file: docs/requirements/REQUIREMENTS_INDEX.md\nbacklog_file: docs/BACKLOG.md\n"
        "accounts:\n  provider: single\n",
        encoding="utf-8",
    )
    return root


def _ungoverned_repo(root: Path) -> Path:
    """A repository shaped like system-admin: documents, a log, an open-items index, git."""
    (root / "log").mkdir(parents=True)
    (root / "README.md").write_text("# system-admin\n\nThe record of the machines.\n", encoding="utf-8")
    (root / "log" / "0001-start.md").write_text("# LOG-0001 — start\n", encoding="utf-8")
    (root / "open.md").write_text("| Item | Owner |\n|---|---|\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "dev")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "start")
    return root


def _cli(cwd: Path, *args: str):
    old = os.getcwd()
    os.chdir(cwd)
    try:
        return CliRunner().invoke(main, list(args))
    finally:
        os.chdir(old)


def _ok(cwd: Path, *args: str) -> str:
    res = _cli(cwd, *args)
    assert res.exit_code == 0, f"steward {' '.join(args)} in {cwd.name}:\n{res.output}"
    return res.output


def _refused(cwd: Path, *args: str) -> str:
    res = _cli(cwd, *args)
    assert res.exit_code != 0, f"steward {' '.join(args)} in {cwd.name} should be refused:\n{res.output}"
    return res.output


def _snapshot(project: Path) -> dict[str, bytes]:
    return {str(p.relative_to(project)): p.read_bytes() for p in sorted(project.rglob("*")) if p.is_file()}


def _log(project: Path) -> list[dict]:
    path = joint.log_path(project)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _section(output: str, title: str) -> str:
    out, inside = [], False
    for line in output.splitlines():
        if line.startswith(title):
            inside = True
            continue
        if inside and line and not line.startswith(" "):
            break
        if inside:
            out.append(line)
    return "\n".join(out)


@pytest.fixture()
def box(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    sarah = _stamp(root / "sarah")
    _git(sarah, "init", "-q", "-b", "dev")
    _ungoverned_repo(root / "system-admin")
    return root


def _join(box: Path) -> Path:
    target = box / "system-admin"
    _ok(box, "new", str(target), "--profile", "joint")
    return target


# -- AC1 -----------------------------------------------------------------------------------


def test_joining_writes_only_the_declaration_and_the_req_workflow_leaves_it_alone(box, monkeypatch):
    monkeypatch.delenv("DEVSTEWARD_UNATTENDED", raising=False)
    target = box / "system-admin"
    before = _snapshot(target)

    # Joining a non-empty repository needs no --force and writes exactly one file.
    out = _ok(box, "new", str(target), "--profile", "joint")
    assert "joint-only participant" in out
    after = _snapshot(target)
    added = after.keys() - before.keys()
    assert added == {".devsteward/config.yaml"}, added
    assert {k: after[k] for k in before} == before, "joining changed an existing file"
    assert load_config(target).profile == "joint"
    assert "profile: joint" in after[".devsteward/config.yaml"].decode()

    # A second join is refused and changes nothing.
    assert "already exists" in _refused(box, "new", str(target), "--profile", "joint")
    assert _snapshot(target) == after

    # status, lint and sync leave it alone.
    status = _ok(target, "status")
    assert "joint-only participant" in status and "sync" not in status
    _ok(target, "lint")
    _ok(target, "sync")
    assert _snapshot(target) == after

    # Every REQ-workflow verb refuses, naming the profile, and writes nothing.
    for args in (("advance",), ("checkpoint",), ("activate", "REQ-001"), ("backlog-add", "a need")):
        out = _refused(target, *args)
        assert "joint-only participant (profile: joint)" in out and f"steward {args[0]}" in out, out
        assert _snapshot(target) == after, f"steward {args[0]} wrote into a joint-only participant"


# -- AC2 -----------------------------------------------------------------------------------


def test_the_dashboard_lists_a_joint_only_participant_without_req_sections(box):
    pytest.importorskip("flask")  # the `dashboard` extra is a declared requirement of this gate
    from devsteward.dashboard import model
    from devsteward.dashboard.app import create_app

    _join(box)
    refs = {r.name: r for r in model.scan_root(box)}
    view = model.load_project(refs["system-admin"], _package_templates())
    assert view.joint_only and view.error == ""
    assert view.git is not None and view.git.branch == "dev"
    assert view.status is None and view.backlog == [] and view.reqs == [] and view.attention == []
    assert not model.load_project(refs["sarah"], _package_templates()).joint_only

    template = (_package_templates() / "docs" / "BACKLOG.md").read_text(encoding="utf-8")
    app = create_app(box, templates_root=_package_templates(), backlog_template=template)
    app.config["TESTING"] = True
    client = app.test_client()

    overview = client.get("/").get_data(as_text=True)
    assert "system-admin" in overview and "joint-only participant" in overview

    page = client.get("/p/system-admin")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "joint-only participant" in html
    for heading in ("<h2>Steward status", "<h2>Backlog", "<h2>Requirements"):
        assert heading not in html, heading
    assert "<form" not in html
    assert client.post("/p/system-admin/verb/activate", data={"req": "REQ-001"}).status_code == 404

    governed = client.get("/p/sarah").get_data(as_text=True)
    assert "<h2>Steward status" in governed


# -- AC3 -----------------------------------------------------------------------------------


def test_a_governed_project_and_a_joint_only_participant_work_a_thread_both_ways(box):
    sarah = box / "sarah"
    sysadm = _join(box)
    governed_calls: list[tuple[str, ...]] = []

    def gov(*args: str) -> str:
        governed_calls.append(args)
        return _ok(sarah, *args)

    # Governed → joint-only.
    gov("joint-send", "--to", "system-admin", "--need", "Grant sarah's broker account the pump topics")
    handle = _log(sarah)[0]["thread"]
    candidates = _section(_ok(sysadm, "joint-list"), "Requests to take up")
    assert handle in candidates and "from sarah" in candidates

    _ok(sysadm, "joint-ack", handle, "sarah#1", "--filed-as", "OPEN-0181")
    assert "Requests to take up" not in _ok(sysadm, "joint-list")
    assert "filed as OPEN-0181 by system-admin" in gov("joint-show", handle)

    _ok(sysadm, "joint-send", handle, "--kind", "ask", "--body", "Read only, or write as well?")
    assert "system-admin#2" in _section(gov("joint-list"), "Waiting for sarah")
    gov("joint-send", handle, "--kind", "tell", "--reply-to", "system-admin#2", "--body", "Write on set.")
    _ok(sysadm, "joint-ack", handle, "sarah#2")
    _ok(sysadm, "joint-send", handle, "--kind", "done", "--body", "OPEN-0181 closes.")
    gov("joint-send", handle, "--kind", "done")
    assert handle not in gov("joint-list")
    assert handle not in _ok(sysadm, "joint-list")

    # Joint-only → governed, under system-admin's own handle convention.
    need = "A target set on a zone's thermostat shows up to a minute late"
    _ok(sysadm, "joint-send", "sysadmin-open-0177", "--to", "sarah", "--need", need)
    ref = f"system-admin#{_log(sysadm)[-1]['seq']}"
    assert "sysadmin-open-0177" in _section(gov("joint-list"), "Requests to take up")
    gov("backlog-add", "--handle", "sysadmin-open-0177", "--origin", "proposed", need)
    gov("joint-ack", "sysadmin-open-0177", ref)
    assert "Requests to take up" not in gov("joint-list")
    assert "filed in sarah's backlog, no REQ yet" in _ok(sysadm, "joint-show", "sysadmin-open-0177")
    write_req(sarah / "docs" / "requirements", "REQ-052", status="open", backlog_refs=["sysadmin-open-0177"])
    assert "taken up by REQ-052 (open)" in _ok(sysadm, "joint-show", "sysadmin-open-0177")

    # Nothing changed for the governed side: only REQ-101 verbs and options.
    req101 = {"joint-send", "joint-ack", "joint-list", "joint-show", "backlog-add"}
    assert {c[0] for c in governed_calls} <= req101
    assert not any("--filed-as" in c for c in governed_calls)


# -- AC4 -----------------------------------------------------------------------------------


def test_filed_as_is_only_the_requests_acknowledgement_and_take_up_follows_its_order(box):
    sarah = box / "sarah"
    sysadm = _join(box)

    # Before any take-up: not taken up. A reply sent before filing does not block filing.
    _ok(sarah, "joint-send", "first-job", "--to", "system-admin", "--need", "The first job")
    assert "not taken up by system-admin yet" in _ok(sarah, "joint-show", "first-job")
    _ok(sysadm, "joint-send", "first-job", "--kind", "ask", "--reply-to", "sarah#1", "--body", "Scope?")
    _ok(sarah, "joint-send", "first-job", "--kind", "tell", "--reply-to", "system-admin#1", "--body", "All.")

    # --filed-as belongs on the request's acknowledgement, never on another message's.
    before = joint.log_path(sysadm).read_bytes()
    out = _refused(sysadm, "joint-ack", "first-job", "sarah#2", "--filed-as", "OPEN-0190")
    assert "belongs on the acknowledgement of the request" in out
    assert joint.log_path(sysadm).read_bytes() == before
    _ok(sysadm, "joint-ack", "first-job", "sarah#1", "--filed-as", "OPEN-0190")
    assert "filed as OPEN-0190 by system-admin" in _ok(sarah, "joint-show", "first-job")
    # The same acknowledgement again writes nothing; a different one is refused.
    before = joint.log_path(sysadm).read_bytes()
    _ok(sysadm, "joint-ack", "first-job", "sarah#1", "--filed-as", "OPEN-0190")
    assert "never changed" in _refused(sysadm, "joint-ack", "first-job", "sarah#1", "--filed-as", "OPEN-0191")
    assert joint.log_path(sysadm).read_bytes() == before

    # A request already acknowledged without --filed-as cannot gain one afterwards.
    _ok(sarah, "joint-send", "second-job", "--to", "system-admin", "--need", "The second job")
    second = f"sarah#{_log(sarah)[-1]['seq']}"
    _ok(sysadm, "joint-ack", "second-job", second)
    before = joint.log_path(sysadm).read_bytes()
    assert "without --filed-as" in _refused(sysadm, "joint-ack", "second-job", second, "--filed-as", "OPEN-0192")
    assert joint.log_path(sysadm).read_bytes() == before

    # For an addressee with a backlog, its backlog item comes before any filed-as.
    _ok(sysadm, "joint-send", "sysadmin-open-0200", "--to", "sarah", "--need", "A governed job")
    ref = f"system-admin#{_log(sysadm)[-1]['seq']}"
    _ok(sarah, "joint-ack", "sysadmin-open-0200", ref, "--filed-as", "a note of sarah's")
    assert "filed as a note of sarah's by sarah" in _ok(sysadm, "joint-show", "sysadmin-open-0200")
    _ok(sarah, "backlog-add", "--handle", "sysadmin-open-0200", "--origin", "proposed", "A governed job")
    shown = _ok(sysadm, "joint-show", "sysadmin-open-0200")
    take_up = next(line for line in shown.splitlines() if "take-up:" in line)
    assert "filed in sarah's backlog, no REQ yet" in take_up and "filed as" not in take_up
