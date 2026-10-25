"""REQ-004 + REQ-029 — the REQ profile derives one fused ``develop`` step per active REQ,
in dependency order."""

from __future__ import annotations

from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.profiles.req import ReqStepSource

from conftest import FakeRunner, write_req


def test_one_develop_step_per_active_req(tmp_path):
    write_req(tmp_path, "REQ-001", status="open")
    steps = ReqStepSource(tmp_path).steps()
    ids = [s.id for s in steps]
    assert ids == ["REQ-001:develop"]

    by_id = {s.id: s for s in steps}
    assert by_id["REQ-001:develop"].depends_on == ()
    # The develop step carries the acceptance test as its verification.
    assert by_id["REQ-001:develop"].verify == ("true",)
    assert by_id["REQ-001:develop"].req == "REQ-001"
    assert by_id["REQ-001:develop"].phase == "develop"


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
    # REQ-002:develop waits on REQ-001:develop.
    assert by_id["REQ-002:develop"].depends_on == ("REQ-001:develop",)


def test_done_dependency_is_dropped(tmp_path):
    write_req(tmp_path, "REQ-001", status="done")  # satisfied, no steps
    write_req(tmp_path, "REQ-002", status="open", depends_on=["REQ-001"])
    steps = ReqStepSource(tmp_path).steps()
    by_id = {s.id: s for s in steps}
    # The done dependency is dropped → REQ-002:develop is immediately unblocked.
    assert by_id["REQ-002:develop"].depends_on == ()


def test_lettered_id_step_derivation(tmp_path):
    """REQ-021 AC4 — a reopened (active) lettered REQ yields its develop step, and a
    dependent's depends_on edge resolves to the lettered develop step. Pins that source.py's
    opaque id handling (``f"{r.id}:{phase}"``, split on ``:``) tolerates the suffix."""
    write_req(tmp_path, "REQ-028p", status="open")  # reopened — lettered REQ is now active
    write_req(tmp_path, "REQ-027", status="open", depends_on=["REQ-028p"])
    steps = ReqStepSource(tmp_path).steps()
    by_id = {s.id: s for s in steps}
    # the lettered REQ derives its develop step, suffix carried verbatim.
    assert [s.id for s in steps if s.req == "REQ-028p"] == ["REQ-028p:develop"]
    # the dependent's develop edge resolves to the lettered develop step.
    assert by_id["REQ-027:develop"].depends_on == ("REQ-028p:develop",)


def test_eligibility_respects_cross_req_dependency(tmp_path, monkeypatch):
    from devsteward.core.executor import Executor
    from devsteward.core.accounts import SingleAccountProvider
    from devsteward.core.verify import CommandVerifier
    from conftest import FakeGitTopology, RecordingCommitter, ok_result

    write_req(tmp_path, "REQ-001", status="open")
    write_req(tmp_path, "REQ-002", status="open", depends_on=["REQ-001"])
    Ledger.init(tmp_path)
    ex = Executor(
        # REQ-091: a spawn names its model; an unconfigured headless spawn refuses.
        model="test-spawn-model",
        root=tmp_path, source=ReqStepSource(tmp_path),
        verifier=CommandVerifier(cwd=str(tmp_path)),
        accounts=SingleAccountProvider(),
        runner=FakeRunner(default=ok_result()),
        committer=RecordingCommitter(),
        git=FakeGitTopology(current="dev"),  # REQ-020: in-memory topology (no real checkout)
    )
    # Initially only REQ-001:develop is eligible (REQ-002 blocked on REQ-001:develop).
    assert [s.id for s in ex.eligible_steps()] == ["REQ-001:develop"]
    # Drive REQ-001; only then does REQ-002:develop unblock.
    ex.advance_once()
    assert ex.ledger.status_of("REQ-001:develop") is StepStatus.DONE
    assert "REQ-002:develop" in [s.id for s in ex.eligible_steps()]
