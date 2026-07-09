"""REQ-028 AC5 — `steward lint` reconciles the REQ marker against the ledger.

FlowSteward REQ-003a's frontmatter was hand-edited to ``status: done`` while the ledger's
terminal land record for it was ``failed``. Lint checked frontmatter↔index agreement but
never the ledger, so the false ``done`` was invisible. Now a ledger-*tracked* REQ marked
``done`` whose ``land`` step is not ``DONE`` (it is failed, or absent under a tracked REQ)
is a hard lint error — the ledger is the cursor of record and the marker must not outrun it.
A ``done`` REQ with no ledger footprint (pre-ledger or imported) stays outside its purview.
"""

from __future__ import annotations

import subprocess

from devsteward.config import Config
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.lint import lint
from devsteward.profiles.req.index import set_status as index_set_status
from devsteward.profiles.req.reqfile import set_frontmatter_status

from conftest import write_index, write_req


def _cfg(root):
    return Config(root=root, requirements_dir="reqs",
                  index_file="reqs/REQUIREMENTS_INDEX.md")


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout


def _commit_all(root, message="snapshot"):
    """Init (once) and commit the current working tree — so lint has a committed HEAD to read
    (REQ-077 rule 7b reads the *committed* marker, not the working tree)."""
    if not (root / ".git").is_dir():
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "lint@devsteward.test")
        _git(root, "config", "user.name", "DevSteward Lint Test")
        _git(root, "checkout", "-q", "-b", "dev")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


def test_lint_fails_on_done_contradicted_by_ledger(tmp_path):
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="open")
    write_req(req_dir, "REQ-002", status="done", depends_on=["REQ-001"])
    write_index(req_dir, [("REQ-001", "north", "OPEN", "–"),
                          ("REQ-002", "two", "DONE", "REQ-001")])

    # The engine drove REQ-002 but its land FAILED — a `done` marker the ledger contradicts.
    ledger = Ledger.init(tmp_path, profile="req")
    ledger.set_status("REQ-002:design", StepStatus.DONE)
    ledger.set_status("REQ-002:build", StepStatus.DONE)
    ledger.set_status("REQ-002:land", StepStatus.FAILED)
    ledger.save()

    problems = lint(_cfg(tmp_path))
    assert any("REQ-002" in p and "ledger" in p for p in problems), problems
    # REQ-001 (open) and the absence of a ledger footprint are not flagged for it.
    assert not any("REQ-001" in p and "ledger" in p for p in problems)

    # An absent land under a tracked REQ is the same contradiction.
    ledger2 = Ledger.init(tmp_path, profile="req")
    ledger2.set_status("REQ-002:design", StepStatus.DONE)
    ledger2.set_status("REQ-002:build", StepStatus.DONE)  # land never recorded
    ledger2.save()
    assert any("REQ-002" in p and "absent" in p for p in lint(_cfg(tmp_path)))

    # Agreement clears it: a green land matches the `done` marker.
    ledger2.set_status("REQ-002:land", StepStatus.DONE)
    ledger2.save()
    assert not any("contradicts the marker" in p for p in lint(_cfg(tmp_path)))


def test_lint_leaves_untracked_done_alone(tmp_path):
    """A `done` REQ the engine never drove (no ledger footprint) is outside the ledger's
    purview — flagging it would break a green dogfood lint over imported/pre-ledger dones."""
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="done")
    write_index(req_dir, [("REQ-001", "north", "DONE", "–")])
    Ledger.init(tmp_path, profile="req")  # empty steps overlay
    assert not any("ledger" in p for p in lint(_cfg(tmp_path)))


# -- REQ-077 rule 7b: the symmetric direction (ledger landed, committed marker lags) -----


def test_ledger_done_but_marker_draft_hard_errors(tmp_path):
    """AC4: the FlowSteward REQ-098/099 direction. The ledger records REQ-002's delivering
    (develop) step DONE, but the **committed** frontmatter/index still read draft/DRAFT — the
    flip was never committed. Lint hard-errors, naming the REQ; the pre-existing marker-ahead
    case (REQ-003, frontmatter done, ledger not) still fires. Both directions covered."""
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="done")
    write_req(req_dir, "REQ-002", status="draft", depends_on=["REQ-001"])
    write_req(req_dir, "REQ-003", status="done", depends_on=["REQ-001"])
    write_index(req_dir, [("REQ-001", "north", "DONE", "–"),
                          ("REQ-002", "two", "DRAFT", "REQ-001"),
                          ("REQ-003", "three", "DONE", "REQ-001")])
    _commit_all(tmp_path)  # HEAD carries REQ-002 as draft/DRAFT

    ledger = Ledger.init(tmp_path, profile="req")
    ledger.set_status("REQ-002:develop", StepStatus.DONE)  # ledger landed it, marker lags
    ledger.set_status("REQ-003:develop", StepStatus.FAILED)  # marker-ahead: done over a fail
    ledger.save()

    problems = lint(_cfg(tmp_path))
    # New direction: ledger-ahead-of-committed-marker for REQ-002.
    assert any("REQ-002" in p and "committed marker lags" in p for p in problems), problems
    # Old direction still fires for REQ-003.
    assert any("REQ-003" in p and "contradicts the marker" in p for p in problems), problems

    # Committing the flip clears the new-direction problem (HEAD now agrees with the ledger).
    set_frontmatter_status(req_dir / "REQ-002.md", "done")
    index_set_status(req_dir / "REQUIREMENTS_INDEX.md", "REQ-002", "done")
    _commit_all(tmp_path, "commit REQ-002 flip")
    assert not any("REQ-002" in p and "committed marker lags" in p for p in lint(_cfg(tmp_path)))


def test_reconcile_reads_committed_head_not_worktree(tmp_path):
    """AC5: the guard reads committed HEAD, not the working tree. With the flip written to the
    worktree (on-disk frontmatter/index look `done`) but HEAD still at draft and the ledger
    DONE, lint STILL flags — a written-but-uncommitted flip cannot mask the drift. A
    develop-done/validate-pending REQ (delivering step not yet done) is not flagged; a
    genuinely committed-consistent REQ lints clean."""
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="done")
    write_req(req_dir, "REQ-002", status="draft", depends_on=["REQ-001"])
    # REQ-003 has a validate phase (an artifact AC) still pending — develop-done is NOT
    # delivered yet, so its committed `open` marker is correct, not a drift.
    write_req(req_dir, "REQ-003", status="open", depends_on=["REQ-001"], check="artifact")
    write_index(req_dir, [("REQ-001", "north", "DONE", "–"),
                          ("REQ-002", "two", "DRAFT", "REQ-001"),
                          ("REQ-003", "three", "OPEN", "REQ-001")])
    _commit_all(tmp_path)  # HEAD: REQ-002 draft, REQ-003 open

    ledger = Ledger.init(tmp_path, profile="req")
    ledger.set_status("REQ-002:develop", StepStatus.DONE)      # landed, marker lags
    ledger.set_status("REQ-003:develop", StepStatus.DONE)      # develop done …
    ledger.set_status("REQ-003:validate", StepStatus.PENDING)  # … but validate still pending
    ledger.save()

    # Simulate the exact drift: the flip is written to the WORKTREE but never committed.
    set_frontmatter_status(req_dir / "REQ-002.md", "done")
    index_set_status(req_dir / "REQUIREMENTS_INDEX.md", "REQ-002", "done")

    problems = lint(_cfg(tmp_path))
    # Reads HEAD (draft), not the worktree (done) → still flags REQ-002.
    assert any("REQ-002" in p and "committed marker lags" in p for p in problems), problems
    # REQ-003's delivering step is validate (pending) → develop-done alone is not flagged.
    assert not any("REQ-003" in p and "committed marker lags" in p for p in problems), problems

    # Once the flip is committed, HEAD agrees and the REQ lints clean on this rule.
    _commit_all(tmp_path, "commit REQ-002 flip")
    assert not any("committed marker lags" in p for p in lint(_cfg(tmp_path)))
