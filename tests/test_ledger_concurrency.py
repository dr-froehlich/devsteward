"""REQ-073 D1 — the ledger lost-update guard: a stale save can never silently rewind
newer committed state.

``Ledger.save()`` carries a monotonic ``seq``. A save from an instance whose loaded ``seq``
is older than the on-disk one means a concurrent process committed under us; the blind
whole-file dump is refused and replaced by a **journal replay** — this instance's own
targeted mutations are re-applied onto the reloaded newer state, so every unrelated newer
fact survives. A pending write with no journal entry (a broad, non-targeted dump — an engine
defect) fails loudly with both sides preserved. Legacy ``state.yaml`` files without a ``seq``
load unchanged and acquire one on their first save.

Everything here is a synthetic ledger in a temp dir — hermetic, no service/secret/network
(REQ-064 screen).
"""

from __future__ import annotations

import pytest
from ruamel.yaml import YAML

from devsteward.core.ledger import Ledger, StaleSaveError
from devsteward.core.model import Decision, DecisionStatus, StepStatus


# -- AC1 ------------------------------------------------------------------------


def test_stale_save_never_rewinds_newer_state(tmp_path):
    """Instance A loads; instance B (same dir) answers a decision, sets the step done, and
    advances the cursor, then saves; then A saves. Afterwards the decision is still answered,
    the step still done, the cursor still advanced — reconciled, never silently rewound."""
    Ledger.init(tmp_path)
    seed = Ledger(tmp_path)
    seed.park_decision(
        Decision(id=seed.next_decision_id(), step="REQ-001:validate",
                 question="sign off?", req="REQ-001")
    )

    # A and B both load the same (older) snapshot.
    a = Ledger(tmp_path)
    b = Ledger(tmp_path)

    # A is mid-work with its own targeted mutation (not yet saved).
    a.set_status("REQ-000:develop", StepStatus.DONE)

    # B lands: answers the decision, marks the step done, advances the cursor — and saves.
    b.answer_decision("DEC-001", "approved")
    b.set_status("REQ-001:validate", StepStatus.DONE)
    b.set_cursor("REQ-002:develop")
    b.save()

    # A's terminal save races in *after* B — a stale seq. It must not rewind B.
    a.save()

    disk = Ledger(tmp_path)
    assert disk.find_decision("DEC-001").status is DecisionStatus.ANSWERED
    assert disk.status_of("REQ-001:validate") is StepStatus.DONE
    assert disk.cursor_step == "REQ-002:develop"
    # A's own mutation survived the reconciliation too.
    assert disk.status_of("REQ-000:develop") is StepStatus.DONE


# -- AC2 ------------------------------------------------------------------------


def test_state_seq_is_monotonic_and_guards_save(tmp_path):
    """Every save bumps ``seq``; reload reads it back; and a save whose loaded ``seq`` is
    older than the on-disk one takes the guard path (here: a loud refusal on an empty
    journal) — never the blind whole-file write that would rewind the newer state."""
    Ledger.init(tmp_path)  # first save → seq 1
    led = Ledger(tmp_path)
    assert led._loaded_seq == 1

    led.set_status("X:develop", StepStatus.DONE)
    led.save()
    assert led._loaded_seq == 2  # a save bumps seq monotonically
    assert Ledger(tmp_path)._loaded_seq == 2  # reload reads the bumped seq off disk

    # Two instances on the same snapshot; B advances seq under A.
    a = Ledger(tmp_path)
    b = Ledger(tmp_path)
    b.set_status("Y:develop", StepStatus.DONE)
    b.save()
    assert Ledger(tmp_path)._loaded_seq == 3

    # A now holds a stale seq with no targeted mutation to replay — the guard refuses the
    # blind write rather than rewinding B's seq-3 state back to seq 2.
    with pytest.raises(StaleSaveError):
        a.save()
    disk = Ledger(tmp_path)
    assert disk._loaded_seq == 3  # B's save stands; nothing was rewound
    assert disk.status_of("Y:develop") is StepStatus.DONE


# -- AC2b -----------------------------------------------------------------------


def _bump_seq_under(root):
    """A concurrent process commits a targeted mutation, advancing the on-disk seq."""
    other = Ledger(root)
    other.set_status("CONCURRENT:develop", StepStatus.DONE)
    other.save()


def test_targeted_mutations_always_reconcile_and_refusal_is_actionable(tmp_path):
    """Every engine mutating path (set_status, set_cursor, park_decision, answer_decision)
    reconciles under a stale-seq conflict — regular operation never fails loudly. The refusal
    is reachable only by a broad, non-targeted write (a simulated engine defect), and its
    message is actionable: nothing was lost, both sides named, re-run / report, never a
    hand-edit of state.yaml."""
    Ledger.init(tmp_path)
    Ledger(tmp_path).park_decision(
        Decision(id="DEC-001", step="REQ-001:validate", question="?", req="REQ-001")
    )

    # set_status: load stale, a concurrent save bumps seq, then the targeted save reconciles.
    led = Ledger(tmp_path)
    _bump_seq_under(tmp_path)
    led.set_status("A:develop", StepStatus.DONE)
    led.save()  # reconciles, no raise
    assert Ledger(tmp_path).status_of("A:develop") is StepStatus.DONE
    assert Ledger(tmp_path).status_of("CONCURRENT:develop") is StepStatus.DONE

    # set_cursor.
    led = Ledger(tmp_path)
    _bump_seq_under(tmp_path)
    led.set_cursor("B:develop")
    led.save()
    assert Ledger(tmp_path).cursor_step == "B:develop"

    # park_decision (auto-saves): load stale, race a concurrent bump, then park.
    led = Ledger(tmp_path)
    _bump_seq_under(tmp_path)
    led.park_decision(Decision(id="DEC-002", step="REQ-002:build", question="?", req="REQ-002"))
    assert Ledger(tmp_path).find_decision("DEC-002") is not None

    # answer_decision (auto-saves): load stale, race a concurrent bump, then answer.
    led = Ledger(tmp_path)
    _bump_seq_under(tmp_path)
    led.answer_decision("DEC-002", "go")
    reconciled = Ledger(tmp_path)
    assert reconciled.find_decision("DEC-002").status is DecisionStatus.ANSWERED
    # None of the concurrent facts were rewound by any of the four reconciling saves.
    assert reconciled.find_decision("DEC-001") is not None
    assert reconciled.status_of("CONCURRENT:develop") is StepStatus.DONE

    # The refusal path: a broad write that bypassed the targeted API (an engine defect).
    led = Ledger(tmp_path)
    _bump_seq_under(tmp_path)
    led._state.setdefault("steps", {})["Z:develop"] = {"status": "done"}  # no journal entry
    with pytest.raises(StaleSaveError) as ei:
        led.save()
    message = (str(ei.value) + " " + (ei.value.recovery or "")).lower()
    assert "nothing was lost" in message
    assert "state.yaml" in message and "events.jsonl" in message
    assert "re-run" in message and "report" in message
    assert "hand-edit" in message


# -- AC3 ------------------------------------------------------------------------


def test_long_lived_process_preserves_interleaved_land(tmp_path):
    """The FlowSteward DEC-044 shape end-to-end: a long-lived validate-style parent loads the
    ledger at start (decision open, validate step parked) and blocks; a second invocation
    lands the step (decision answered, validate done, cursor advanced) and saves; then the
    parent's terminal save at record() fires with a stale snapshot. The land's facts survive,
    and state.yaml agrees with the append-only events.jsonl — no silent rewind."""
    Ledger.init(tmp_path)
    Ledger(tmp_path).park_decision(
        Decision(id="DEC-001", step="REQ-069:validate",
                 question="human sign-off?", req="REQ-069")
    )

    # The long-lived parent loads at start(): it sees the *stale* pre-land snapshot.
    parent = Ledger(tmp_path)
    assert parent.status_of("REQ-069:validate") is StepStatus.BLOCKED
    assert parent.find_decision("DEC-001").status is DecisionStatus.OPEN

    # ... the parent blocks for the whole session. Meanwhile a second invocation lands.
    lander = Ledger(tmp_path)
    lander.answer_decision("DEC-001", "approved")
    lander.set_status("REQ-069:validate", StepStatus.DONE)
    lander.set_cursor("REQ-070:develop")
    lander.save()

    # The parent's terminal save at record(): it records only its own targeted mutation. Its
    # in-memory snapshot is stale (validate blocked, DEC-001 open), but the journal replay
    # re-applies *only* its own write onto the lander's newer state — the stale snapshot is
    # never dumped wholesale.
    parent.set_status("REQ-069:validate", StepStatus.DONE)
    parent.save()

    disk = Ledger(tmp_path)
    assert disk.status_of("REQ-069:validate") is StepStatus.DONE
    assert disk.find_decision("DEC-001").status is DecisionStatus.ANSWERED  # not rewound to open
    assert disk.cursor_step == "REQ-070:develop"  # the lander's advance survived
    # state.yaml and events.jsonl agree: the answered decision is in both.
    assert any(
        e["event"] == "decision_answered" and e["decision"] == "DEC-001"
        for e in disk.events()
    )


# -- AC6 ------------------------------------------------------------------------


def test_legacy_state_without_seq_loads_and_upgrades(tmp_path):
    """A legacy state.yaml predating REQ-073 (no ``seq`` field) loads without error, behaves
    normally, and acquires a ``seq`` on its first save — no migration command needed."""
    Ledger.init(tmp_path)
    state_path = tmp_path / ".devsteward" / "state.yaml"

    # Strip `seq` to simulate a pre-REQ-073 ledger written by an older engine.
    yaml = YAML()
    with state_path.open("r", encoding="utf-8") as fh:
        data = yaml.load(fh)
    data.pop("seq", None)
    with state_path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh)

    led = Ledger(tmp_path)
    assert led._loaded_seq is None  # legacy: no seq on disk

    led.set_status("X:develop", StepStatus.DONE)
    led.save()  # a missing on-disk seq is never a conflict — it just upgrades
    assert led._loaded_seq == 1

    reloaded = Ledger(tmp_path)
    assert reloaded._loaded_seq == 1
    assert reloaded.status_of("X:develop") is StepStatus.DONE
