"""REQ-075 AC2 — carry-forward with provenance.

On a scoped re-run the engine copies each carried green `artifact` AC's files from the
source evidence dir into the new run's evidence dir, honors a carried green `manual`
sign-off **without a new decision stop**, and records — per carried AC — the source
evidence path + originating validation event. A carried AC whose source files are missing
is a **hard red**, never a silent pass.

`_carry_forward` is unit-tested directly (copy / manual-carry / missing-source), and one
end-to-end scoped `_validate` confirms a carried manual AC takes no fresh sign-off and the
validation event carries the provenance.
"""

from __future__ import annotations

from types import SimpleNamespace

from devsteward.core.executor import RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.profiles.req.validate import ReqValidateRoutine, Signoff

from conftest import FakeGitTopology, write_index
from test_system_test_phase import (
    SystemTesterRunner,
    _REGRESSION,
    _executor,
    _write_plan,
    _write_req,
)


# -- unit: _carry_forward -------------------------------------------------------


def _routine(tmp_path):
    return ReqValidateRoutine(tmp_path / "docs" / "requirements")


def test_carry_forward_copies_artifacts_and_honors_manual(tmp_path):
    """Carried artifact files land in the new evidence dir; a carried manual sign-off becomes
    a green result row + signoff record (carried_from provenance) with no sign-off call; the
    provenance records source path + event per carried AC; ok stays True."""
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "capture.txt").write_text("observed\n")
    (src / "sub" / "log.txt").write_text("more\n")
    ex = SimpleNamespace(root=tmp_path)
    reval = {
        "carried": [
            {"ac": "AC2", "check": "artifact",
             "source_evidence": "src", "source_event": "T1"},
            {"ac": "AC3", "check": "manual",
             "source_evidence": "src", "source_event": "T1",
             "signoff": {"ac": "AC3", "approved": True, "reviewer": "Petra",
                         "scope": "bulk-move rehearsal", "date": "2026-07-05"}},
        ]
    }
    new = tmp_path / "new"
    new.mkdir()

    records, extra, signoffs, ok = _routine(tmp_path)._carry_forward(ex, reval, new)

    assert ok is True
    # Artifacts copied forward, structure preserved.
    assert (new / "capture.txt").read_text() == "observed\n"
    assert (new / "sub" / "log.txt").read_text() == "more\n"
    # Provenance per carried AC.
    assert {r["ac"]: (r["source_evidence"], r["source_event"]) for r in records} == {
        "AC2": ("src", "T1"), "AC3": ("src", "T1")
    }
    # Carried manual → a green result row + a signoff record marked carried_from.
    manual_row = next(r for r in extra if r["ac"] == "AC3")
    assert manual_row["ok"] is True and manual_row["check"] == "manual"
    assert signoffs == [{"ac": "AC3", "approved": True, "reviewer": "Petra",
                         "scope": "bulk-move rehearsal", "date": "2026-07-05",
                         "carried_from": "T1"}]


def test_carry_forward_missing_source_is_hard_red(tmp_path):
    """A carried artifact AC whose source dir has no files is a hard red (ok False, an
    explicit result row), never a silent pass."""
    ex = SimpleNamespace(root=tmp_path)
    reval = {"carried": [
        {"ac": "AC2", "check": "artifact", "source_evidence": "gone", "source_event": "T1"},
    ]}
    new = tmp_path / "new"
    new.mkdir()

    records, extra, signoffs, ok = _routine(tmp_path)._carry_forward(ex, reval, new)

    assert ok is False
    red = next(r for r in extra if r["ac"] == "AC2")
    assert red["ok"] is False and "hard red" in red["detail"]
    assert [c["ac"] for c in records] == ["AC2"]   # still recorded as attempted-carry


# -- integration: a scoped _validate carries a manual AC without re-signing -----


def _seed_source_evidence(root, rel, filename="capture.txt"):
    p = root / rel / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("source artifact\n")
    return rel


def test_scoped_validate_carries_manual_and_records_provenance(tmp_path):
    """A scoped re-run (AC4 red re-opens; AC2 artifact + AC3 manual carried green) grades
    green: the carried manual takes no fresh sign-off (the provider is never called for it),
    the copied artifact lands in the new evidence dir, and the new validation event records
    the carry provenance."""
    acs = [
        _REGRESSION,
        {"id": "AC2", "test": "true", "check": "artifact"},
        {"id": "AC3", "test": "manual: reviewer inspects", "check": "manual"},
        {"id": "AC4", "test": "true", "check": "artifact"},
    ]
    req_dir = tmp_path / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", acs, status="open")
    write_index(req_dir, [("REQ-001", "t", "OPEN", "–")])
    _write_plan(tmp_path, "REQ-001")
    Ledger.init(tmp_path)
    led = Ledger(tmp_path)
    led.set_status("REQ-001:develop", StepStatus.DONE)
    led.save()

    src_rel = _seed_source_evidence(tmp_path, ".devsteward/evidence/REQ-001/src")
    # The prior red validation: AC2 green artifact, AC3 green manual, AC4 red artifact.
    led.append_event(
        "revalidate", req="REQ-001", validate="REQ-001:validate",
        evidence=src_rel, brief="AC4 red", decision=None,
        scope=["AC4"],
        carried=[
            {"ac": "AC2", "check": "artifact", "source_evidence": src_rel, "source_event": "T1"},
            {"ac": "AC3", "check": "manual", "source_evidence": src_rel, "source_event": "T1",
             "signoff": {"ac": "AC3", "approved": True, "reviewer": "Petra", "scope": "",
                         "date": "2026-07-05"}},
        ],
    )
    led.set_status("REQ-001:validate", StepStatus.PENDING)
    led.save()

    ex = _executor(tmp_path, runner=SystemTesterRunner(tmp_path),
                   git=FakeGitTopology(current="dev"))
    step = ex.step_by_id("REQ-001:validate")

    calls = []

    def provider(ac):
        calls.append(ac.id)
        return Signoff(approved=True, reviewer="X")

    res = ex.validate_runner._validate(
        ex, ex.validate_runner._req("REQ-001"), step,
        unattended=False, on_event=None, signoff=provider,
        driver="interactive", in_flight=True,
    )

    assert res.outcome is RunOutcome.DONE, res.detail
    assert calls == []                              # carried manual → no fresh sign-off call

    fresh = Ledger(tmp_path)
    val = [e for e in fresh.events() if e["event"] == "validation"][-1]
    assert val["ok"] is True
    # The new validation event records the carry provenance.
    assert {c["ac"]: (c["source_evidence"], c["source_event"]) for c in val["carried"]} == {
        "AC2": (src_rel, "T1"), "AC3": (src_rel, "T1")
    }
    # The carried artifact landed in the new run's evidence dir; the carried manual sign-off
    # rode into the event's signoffs marked carried_from.
    new_dir = tmp_path / val["evidence"]
    assert (new_dir / "capture.txt").read_text() == "source artifact\n"
    assert any(s.get("carried_from") == "T1" for s in val["signoffs"])
