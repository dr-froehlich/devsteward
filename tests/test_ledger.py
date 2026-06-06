"""REQ-003 AC1, REQ-005 AC2 — the ledger round-trips state, events, and decisions."""

from __future__ import annotations

from devsteward.core.ledger import Ledger
from devsteward.core.model import Decision, StepStatus


def test_init_creates_state_and_events(tmp_path):
    led = Ledger.init(tmp_path, profile="req")
    assert led.state_path.exists()
    assert led.events_path.exists()
    assert led.profile == "req"
    assert led.cursor_step is None
    assert any(e["event"] == "ledger_init" for e in led.events())


def test_status_transitions_persist(tmp_path):
    Ledger.init(tmp_path)
    led = Ledger(tmp_path)
    assert led.status_of("REQ-002:design") is StepStatus.PENDING  # default
    led.set_status("REQ-002:design", StepStatus.DONE)
    led.set_cursor("REQ-002:design")
    led.save()

    reloaded = Ledger(tmp_path)
    assert reloaded.status_of("REQ-002:design") is StepStatus.DONE
    assert reloaded.cursor_step == "REQ-002:design"


def test_append_event_is_jsonl(tmp_path):
    led = Ledger.init(tmp_path)
    led.append_event("checkpoint", step="REQ-002:land", commit="abc123")
    events = led.events()
    assert events[-1]["event"] == "checkpoint"
    assert events[-1]["commit"] == "abc123"
    assert "ts" in events[-1]


def test_park_decision_blocks_step(tmp_path):
    led = Ledger.init(tmp_path)
    dec = Decision(id=led.next_decision_id(), step="REQ-003:build",
                   question="Which serializer?", req="REQ-003")
    led.park_decision(dec)

    assert led.status_of("REQ-003:build") is StepStatus.BLOCKED
    assert [d.id for d in led.open_decisions()] == ["DEC-001"]
    assert any(e["event"] == "decision_parked" for e in led.events())


def test_answer_decision_unblocks(tmp_path):
    led = Ledger.init(tmp_path)
    dec = Decision(id=led.next_decision_id(), step="REQ-003:build", question="?")
    led.park_decision(dec)

    answered = led.answer_decision("DEC-001", "use JSON")
    assert answered is not None
    assert answered.answer == "use JSON"
    # Step returns to PENDING so a later run resumes it.
    assert led.status_of("REQ-003:build") is StepStatus.PENDING
    assert led.open_decisions() == []
