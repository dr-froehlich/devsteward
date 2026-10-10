"""REQ-101 AC1–AC4 — joint tasks between projects.

The invariant these tests defend: **a project only ever writes its own log, and everything
else is derived on read.** Two stamped siblings under one temp root play a whole thread
through the real click verbs — request, candidate, take-up, ask, tell, the two-sided done —
while a byte snapshot of both trees proves no verb reached across. The fixtures are real
on-disk projects found by the same directory scan the dashboard uses, so the discovery,
the addressing and the derivations run against the shape the real box has.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from devsteward.cli import main
from devsteward.config import load_config
from devsteward.core.ledger import Ledger
from devsteward.profiles.req import joint

from conftest import write_req

_HANDLE_RE = joint._HANDLE_RE


# -- fixtures: a box holding stamped siblings and one plain folder -------------------------


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


@pytest.fixture()
def box(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    _stamp(root / "alpha")
    _stamp(root / "Beta")
    (root / "plain").mkdir()
    (root / "plain" / "README.md").write_text("not stamped\n", encoding="utf-8")
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


def _log(project: Path) -> list[dict]:
    path = joint.log_path(project)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _section(output: str, title: str) -> str:
    """The lines under ``title`` up to the next unindented heading."""
    lines = output.splitlines()
    out, inside = [], False
    for line in lines:
        if line.startswith(title):
            inside = True
            continue
        if inside and line and not line.startswith(" "):
            break
        if inside:
            out.append(line)
    return "\n".join(out)


# -- AC1 -----------------------------------------------------------------------------------


def test_a_whole_thread_between_two_stamped_siblings(box):
    alpha, beta = box / "alpha", box / "Beta"
    need = "A target set on a zone's thermostat shows up to a minute late"

    # alpha opens the thread; the handle is minted with alpha's name in front.
    _ok(alpha, "joint-send", "--to", "beta", "--need", need, "--body", "Seen twice on 2026-10-10.")
    (action,) = _log(alpha)
    handle = action["thread"]
    assert handle.startswith("alpha-") and _HANDLE_RE.match(handle)
    assert action["to"] == "Beta" and action["kind"] == "action"

    # Beta finds it without being told where alpha lives: a candidate, and waiting.
    listing = _ok(beta, "joint-list")
    candidates = _section(listing, "Requests to take up")
    assert handle in candidates and "from alpha" in candidates and need in candidates
    assert "alpha#1" in _section(listing, "Waiting for Beta")

    # Beta files it under the thread's handle and acknowledges: no longer a candidate.
    _ok(beta, "backlog-add", "--handle", handle, "--origin", "proposed", need)
    _ok(beta, "joint-ack", handle, "alpha#1")
    listing = _ok(beta, "joint-list")
    assert "Requests to take up" not in listing
    assert "Waiting for Beta" not in listing

    # alpha reads the take-up from Beta's own backlog — nothing travelled back.
    assert "filed in Beta's backlog, no REQ yet" in _ok(alpha, "joint-show", handle)
    write_req(beta / "docs" / "requirements", "REQ-007", status="open", backlog_refs=[handle])
    shown = _ok(alpha, "joint-show", handle)
    assert "taken up by REQ-007 (open)" in shown and "in-progress" in shown

    # Beta asks; it waits for alpha.
    _ok(beta, "joint-send", handle, "--kind", "ask", "--body", "Which payload do you send?")
    assert "Beta#2" in _section(_ok(alpha, "joint-list"), "Waiting for alpha")

    # alpha answers with a tell; the ask is handled, the tell waits for Beta until acknowledged.
    _ok(alpha, "joint-send", handle, "--kind", "tell", "--reply-to", "Beta#2",
        "--body", "A plain number on the set topic.")
    assert "Waiting for alpha" not in _ok(alpha, "joint-list")
    assert "alpha#2" in _section(_ok(beta, "joint-list"), "Waiting for Beta")
    _ok(beta, "joint-ack", handle, "alpha#2")
    assert "Waiting for Beta" not in _ok(beta, "joint-list")

    # One done is not enough: the thread stays open in both projects.
    _ok(alpha, "joint-send", handle, "--kind", "done", "--body", "Verified on our side.")
    for project in (alpha, beta):
        assert handle in _section(_ok(project, "joint-list"), "Open joint threads")

    # The second done closes it: gone from both lists, still readable in full, in time order.
    _ok(beta, "joint-send", handle, "--kind", "done", "--reply-to", "alpha#3")
    for project in (alpha, beta):
        assert handle not in _ok(project, "joint-list")
    shown = _ok(beta, "joint-show", handle)
    assert "closed" in shown.splitlines()[0]
    order = ["alpha#1", "Beta#1", "Beta#2", "alpha#2", "Beta#3", "alpha#3", "Beta#4"]
    positions = [shown.index(ref) for ref in order]
    assert positions == sorted(positions), shown

    # And nothing more can be said.
    assert "closed" in _refused(alpha, "joint-send", handle, "--kind", "tell", "--body", "one more")
    assert "closed" in _refused(beta, "joint-send", handle, "--kind", "ask", "--body", "one more")


# -- AC2 -----------------------------------------------------------------------------------


def _snapshot(project: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(project)): p.read_bytes()
        for p in sorted(project.rglob("*"))
        if p.is_file()
    }


def test_every_verb_writes_only_its_own_log_and_only_by_appending(box):
    alpha, beta = box / "alpha", box / "Beta"
    log_rel = str(Path(".devsteward") / "joint.jsonl")
    h = "alpha-shared-job"
    steps: list[tuple[Path, tuple[str, ...], bool]] = [
        (alpha, ("joint-send", h, "--to", "Beta", "--need", "Do the shared job", "--body", "Why."), True),
        (beta, ("joint-list",), False),
        (beta, ("joint-show", h), False),
        (beta, ("joint-ack", h, "alpha#1"), True),
        (beta, ("joint-send", h, "--kind", "ask", "--body", "When?"), True),
        (alpha, ("joint-list",), False),
        (alpha, ("joint-send", h, "--kind", "tell", "--reply-to", "Beta#2", "--body", "Now."), True),
        (beta, ("joint-ack", h, "alpha#2"), True),
        (beta, ("joint-ack", h, "alpha#2"), False),  # already handled: writes nothing
        (alpha, ("joint-send", h, "--kind", "done"), True),
        (beta, ("joint-send", h, "--kind", "done"), True),
        (alpha, ("joint-show", h), False),
        (beta, ("joint-list",), False),
    ]
    for actor, args, writes in steps:
        other = beta if actor == alpha else alpha
        before_actor, before_other = _snapshot(actor), _snapshot(other)
        _ok(actor, *args)
        after_actor, after_other = _snapshot(actor), _snapshot(other)

        assert after_other == before_other, f"{args} in {actor.name} changed {other.name}"
        changed = {k for k in before_actor.keys() | after_actor.keys()
                   if before_actor.get(k) != after_actor.get(k)}
        if not writes:
            assert changed == set(), f"{args} in {actor.name} changed {changed}"
            continue
        assert changed == {log_rel}, f"{args} in {actor.name} changed {changed}"
        old, new = before_actor.get(log_rel, b""), after_actor[log_rel]
        assert new.startswith(old) and len(new) > len(old), f"{args} did not append"


# -- AC3 -----------------------------------------------------------------------------------


def _case_sensitive(root: Path) -> bool:
    probe = root / "CaseProbe"
    probe.mkdir()
    try:
        return not (root / "caseprobe").exists()
    finally:
        probe.rmdir()


def test_addressing_resolves_stamped_siblings_and_refuses_the_rest(box):
    alpha, beta = box / "alpha", box / "Beta"
    gamma = _stamp(box / "gamma")

    # Case-insensitive resolution to the folder as it is named on disk.
    _ok(alpha, "joint-send", "--to", "BETA", "--need", "Resolve me by any case")
    (first,) = _log(alpha)
    assert first["to"] == "Beta"
    assert first["thread"].startswith("alpha-") and _HANDLE_RE.match(first["thread"])

    # Each refusal names the addressable projects and writes nothing.
    refusals = {
        "nobody": "no project named 'nobody'",
        "plain": "'plain' is not a stamped",
        "ALPHA": "cannot address itself",
    }
    if _case_sensitive(box):
        _stamp(box / "Delta")
        _stamp(box / "delta")
        refusals["DELTA"] = "differ only by case"
    for name, why in refusals.items():
        before = joint.log_path(alpha).read_bytes()
        out = _refused(alpha, "joint-send", "--to", name, "--need", "Anything at all")
        assert why in out and "addressable projects:" in out and "Beta" in out, out
        assert joint.log_path(alpha).read_bytes() == before

    # A chosen handle may not collide with a thread or with an item in the addressee's backlog.
    _ok(alpha, "joint-send", "taken-thread", "--to", "Beta", "--need", "First use of the handle")
    assert "already names a thread" in _refused(
        alpha, "joint-send", "taken-thread", "--to", "Beta", "--need", "Second use")
    _ok(beta, "backlog-add", "--handle", "beta-own-item", "Beta's own need")
    assert "already names a thread" in _refused(
        alpha, "joint-send", "beta-own-item", "--to", "Beta", "--need", "Collides with Beta's item")
    assert "kebab-case" in _refused(alpha, "joint-send", "Not_A_Handle", "--to", "Beta", "--need", "x")

    # Only the two parties may write into a thread, and a reply must name one of its messages.
    out = _refused(gamma, "joint-send", "taken-thread", "--kind", "tell", "--body", "I am not in this")
    assert "no joint thread 'taken-thread' that gamma is a party of" in out
    assert _log(gamma) == []
    assert "is no message of thread" in _refused(
        beta, "joint-send", "taken-thread", "--kind", "tell", "--reply-to", "alpha#99", "--body", "x")
    assert "is no message to Beta" in _refused(beta, "joint-ack", "taken-thread", "Beta#1")


# -- AC4 -----------------------------------------------------------------------------------


def test_a_bad_neighbour_log_is_reported_and_never_blocks(box):
    alpha, beta = box / "alpha", box / "Beta"
    gamma = _stamp(box / "gamma")
    _ok(alpha, "joint-send", "alpha-first-job", "--to", "Beta", "--need", "The first job")
    _ok(gamma, "joint-send", "gamma-other-job", "--to", "Beta", "--need", "Another job")

    # Damage alpha's log by hand: one line no reader can parse, one ack naming a lost message.
    now = datetime.now().astimezone().isoformat(timespec="microseconds")
    with joint.log_path(alpha).open("a", encoding="utf-8") as fh:
        fh.write("{this is not json\n")
        fh.write(json.dumps({"seq": 3, "at": now, "thread": "alpha-first-job",
                             "kind": "ack", "ref": "Beta#99"}) + "\n")

    listing = _ok(beta, "joint-list")
    assert "alpha/.devsteward/joint.jsonl: line 2: not valid JSON" in listing
    candidates = _section(listing, "Requests to take up")
    assert "alpha-first-job" in candidates and "gamma-other-job" in candidates

    shown = _ok(beta, "joint-show", "alpha-first-job")
    assert "Beta#99" in shown and "dangling" in shown
    assert "line 2: not valid JSON" in shown
