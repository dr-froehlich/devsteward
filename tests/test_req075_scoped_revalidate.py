"""REQ-075 AC1 — red-only re-open is the engine default of `revalidate`.

`revalidate` reads the red validation's per-AC results and re-opens **only** the red (or
unrecorded) `artifact`/`manual` ACs, carrying the green ones forward. The revalidate event
records the scoped set; the next validation run names only those ACs in the System-Tester
session prompt. Degenerate cases — no per-AC results, or every AC red — collapse to today's
full re-run (no scope recorded).

Fixture-ledger only (Decision 5): the scope split is `lifecycle._scope_revalidation`, the
event write is `lifecycle.revalidate`, and the session-prompt naming is `validate._ac_flag`
threaded into the command — all exercised directly, no `claude` spawn.
"""

from __future__ import annotations

import pytest
from devsteward.config import Config
from devsteward.core.ledger import Ledger
from devsteward.core.model import Decision, StepStatus
from devsteward.lifecycle import revalidate
from devsteward.profiles.req.validate import _ac_flag, _pending_revalidate

from conftest import write_index
from test_system_test_phase import _REGRESSION, _write_req


def _seed_mixed_red(root, acs, results, *, signoffs=None, evidence="ev/src"):
    """An in-flight REQ-001 parked on a red validation whose per-AC results are `results`."""
    req_dir = root / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", acs, status="open")
    write_index(req_dir, [("REQ-001", "t", "OPEN", "–")])
    Ledger.init(root)
    led = Ledger(root)
    led.set_status("REQ-001:develop", StepStatus.DONE)
    led.save()
    led.append_event(
        "validation", step="REQ-001:validate", req="REQ-001", ok=False,
        driver="interactive", rerun=False, evidence=evidence,
        results=results, artifacts=[], signoffs=signoffs or [],
    )
    dec = Decision(
        id=led.next_decision_id(), step="REQ-001:validate",
        question="REQ-001 validation red", req="REQ-001",
    )
    led.park_decision(dec)
    return led


# -- red-only scoping -----------------------------------------------------------


def test_revalidate_reopens_only_red_acs(tmp_path):
    """A mixed red validation (AC2 green artifact, AC3 red artifact) → the revalidate event
    scopes to only AC3 and carries AC2 forward with provenance; the session prompt names
    only AC3."""
    acs = [
        _REGRESSION,
        {"id": "AC2", "test": "true", "check": "artifact"},
        {"id": "AC3", "test": "false", "check": "artifact"},
    ]
    results = [
        {"ac": "AC2", "check": "artifact", "ok": True, "detail": "green"},
        {"ac": "AC3", "check": "artifact", "ok": False, "detail": "boom"},
    ]
    led = _seed_mixed_red(tmp_path, acs, results, evidence=".devsteward/evidence/REQ-001/src")

    res = revalidate(Config(root=tmp_path), led, "REQ-001")

    assert res.scope == ["AC3"]                      # only the red AC re-opens
    carried_acs = [c["ac"] for c in res.carried]
    assert carried_acs == ["AC2"]                    # the green one-off is carried
    assert res.carried[0]["source_evidence"] == ".devsteward/evidence/REQ-001/src"
    assert res.carried[0]["source_event"] is not None

    fresh = Ledger(tmp_path)
    reval_ev = [e for e in fresh.events() if e["event"] == "revalidate"][-1]
    assert reval_ev["scope"] == ["AC3"]
    assert [c["ac"] for c in reval_ev["carried"]] == ["AC2"]

    # The next validation run names only the scoped AC in the session prompt.
    pending = _pending_revalidate(fresh, "REQ-001")
    assert pending is not None
    assert _ac_flag(pending) == " --ac AC3"


def test_unrecorded_ac_is_reopened(tmp_path):
    """An AC with no recorded result in the red validation is treated as red (re-opened),
    not silently carried — only ACs the validation recorded green are carried."""
    acs = [
        _REGRESSION,
        {"id": "AC2", "test": "true", "check": "artifact"},
        {"id": "AC3", "test": "false", "check": "artifact"},
    ]
    # AC3 has no per-AC row (only a synthetic gap row + AC2 green).
    results = [
        {"ac": "AC2", "check": "artifact", "ok": True, "detail": "green"},
        {"ac": "-", "check": "artifact", "ok": False, "detail": "no artifact captured"},
    ]
    led = _seed_mixed_red(tmp_path, acs, results)

    res = revalidate(Config(root=tmp_path), led, "REQ-001")
    assert res.scope == ["AC3"]                      # unrecorded AC3 re-opens
    assert [c["ac"] for c in res.carried] == ["AC2"]


# -- degenerate → today's full re-run ------------------------------------------


def test_all_red_is_full_rerun(tmp_path):
    """Every declared AC red → no green set → no scope recorded (today's full re-run): the
    revalidate event omits `scope`/`carried` and the run names no ACs."""
    acs = [
        _REGRESSION,
        {"id": "AC2", "test": "false", "check": "artifact"},
        {"id": "AC3", "test": "false", "check": "artifact"},
    ]
    results = [
        {"ac": "AC2", "check": "artifact", "ok": False, "detail": "boom"},
        {"ac": "AC3", "check": "artifact", "ok": False, "detail": "boom"},
    ]
    led = _seed_mixed_red(tmp_path, acs, results)

    res = revalidate(Config(root=tmp_path), led, "REQ-001")
    assert res.scope is None and res.carried is None

    fresh = Ledger(tmp_path)
    reval_ev = [e for e in fresh.events() if e["event"] == "revalidate"][-1]
    assert "scope" not in reval_ev and "carried" not in reval_ev
    assert _pending_revalidate(fresh, "REQ-001") is None   # full re-run: no scoping
    assert _ac_flag(None) == ""


def test_no_per_ac_results_is_full_rerun(tmp_path):
    """A red validation with no per-AC AC rows at all (only a synthetic gap row) → full
    re-run: nothing to carry, nothing to scope down to."""
    acs = [_REGRESSION, {"id": "AC2", "test": "false", "check": "artifact"}]
    results = [{"ac": "-", "check": "artifact", "ok": False, "detail": "session failed"}]
    led = _seed_mixed_red(tmp_path, acs, results)

    res = revalidate(Config(root=tmp_path), led, "REQ-001")
    assert res.scope is None and res.carried is None


def test_pending_revalidate_consumed_by_a_later_validation(tmp_path):
    """A scoped revalidate is *pending* only until a validation runs after it — a later
    validation event consumes the scope so a subsequent run is a full one again."""
    acs = [
        _REGRESSION,
        {"id": "AC2", "test": "true", "check": "artifact"},
        {"id": "AC3", "test": "false", "check": "artifact"},
    ]
    results = [
        {"ac": "AC2", "check": "artifact", "ok": True, "detail": "green"},
        {"ac": "AC3", "check": "artifact", "ok": False, "detail": "boom"},
    ]
    led = _seed_mixed_red(tmp_path, acs, results)
    revalidate(Config(root=tmp_path), led, "REQ-001")

    fresh = Ledger(tmp_path)
    assert _pending_revalidate(fresh, "REQ-001") is not None
    # A validation runs → consumes the scope.
    fresh.append_event(
        "validation", step="REQ-001:validate", req="REQ-001", ok=True,
        evidence="ev/new", results=[], artifacts=[], signoffs=[], carried=[],
    )
    assert _pending_revalidate(Ledger(tmp_path), "REQ-001") is None
