"""REQ-004 — the REQ profile derives Design/Build/Land steps in dependency order."""

from __future__ import annotations

from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.profiles.req import ReqStepSource

from conftest import FakeRunner, write_req


def test_three_steps_per_active_req(tmp_path):
    write_req(tmp_path, "REQ-001", status="open")
    steps = ReqStepSource(tmp_path).steps()
    ids = [s.id for s in steps]
    assert ids == ["REQ-001:design", "REQ-001:build", "REQ-001:land"]

    by_id = {s.id: s for s in steps}
    assert by_id["REQ-001:design"].depends_on == ()
    assert by_id["REQ-001:build"].depends_on == ("REQ-001:design",)
    assert by_id["REQ-001:land"].depends_on == ("REQ-001:build",)
    # The land step carries the acceptance test as its verification.
    assert by_id["REQ-001:land"].verify == ("true",)
    assert by_id["REQ-001:land"].req == "REQ-001"


def test_terminal_and_draft_reqs_produce_no_steps(tmp_path):
    write_req(tmp_path, "REQ-001", status="done")
    write_req(tmp_path, "REQ-002", status="draft")
    write_req(tmp_path, "REQ-003", status="dropped")
    assert ReqStepSource(tmp_path).steps() == []


def test_cross_req_sequencing(tmp_path):
    write_req(tmp_path, "REQ-001", status="open")
    write_req(tmp_path, "REQ-002", status="open", depends_on=["REQ-001"])
    steps = ReqStepSource(tmp_path).steps()
    by_id = {s.id: s for s in steps}
    # REQ-002:design waits on REQ-001:land.
    assert by_id["REQ-002:design"].depends_on == ("REQ-001:land",)


def test_done_dependency_is_dropped(tmp_path):
    write_req(tmp_path, "REQ-001", status="done")  # satisfied, no steps
    write_req(tmp_path, "REQ-002", status="open", depends_on=["REQ-001"])
    steps = ReqStepSource(tmp_path).steps()
    by_id = {s.id: s for s in steps}
    # The done dependency is dropped → REQ-002:design is immediately unblocked.
    assert by_id["REQ-002:design"].depends_on == ()


def test_lettered_id_step_derivation(tmp_path):
    """REQ-021 AC4 — a reopened (active) lettered REQ yields its three phase steps, and a
    dependent's depends_on edge resolves to the lettered land step. Pins that source.py's
    opaque id handling (build ``f"{r.id}:{phase}"``, split on ``:``) tolerates the suffix."""
    write_req(tmp_path, "REQ-028p", status="open")  # reopened — lettered REQ is now active
    write_req(tmp_path, "REQ-027", status="open", depends_on=["REQ-028p"])
    steps = ReqStepSource(tmp_path).steps()
    by_id = {s.id: s for s in steps}
    # the lettered REQ derives all three phases, suffix carried verbatim.
    assert [s.id for s in steps if s.req == "REQ-028p"] == [
        "REQ-028p:design", "REQ-028p:build", "REQ-028p:land"
    ]
    # the dependent's design edge resolves to the lettered land step.
    assert by_id["REQ-027:design"].depends_on == ("REQ-028p:land",)


def test_eligibility_respects_cross_req_dependency(tmp_path, monkeypatch):
    from devsteward.core.executor import Executor
    from devsteward.core.accounts import SingleAccountProvider
    from devsteward.core.verify import CommandVerifier
    from conftest import FakeGitTopology, RecordingCommitter, ok_result

    write_req(tmp_path, "REQ-001", status="open")
    write_req(tmp_path, "REQ-002", status="open", depends_on=["REQ-001"])
    Ledger.init(tmp_path)
    ex = Executor(
        root=tmp_path, source=ReqStepSource(tmp_path),
        verifier=CommandVerifier(cwd=str(tmp_path)),
        accounts=SingleAccountProvider(),
        runner=FakeRunner(default=ok_result()),
        committer=RecordingCommitter(),
        git=FakeGitTopology(current="dev"),  # REQ-020: in-memory topology (no real checkout)
    )
    # Initially only REQ-001:design is eligible (REQ-002 blocked on REQ-001:land).
    assert [s.id for s in ex.eligible_steps()] == ["REQ-001:design"]
    # Drive REQ-001 fully; only then does REQ-002:design unblock.
    for _ in range(3):
        ex.advance_once()
    assert ex.ledger.status_of("REQ-001:land") is StepStatus.DONE
    assert "REQ-002:design" in [s.id for s in ex.eligible_steps()]
