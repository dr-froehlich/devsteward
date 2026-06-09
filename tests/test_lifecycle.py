"""REQ-026 AC1–AC3 — the operator verbs `steward activate` and `steward recover`."""

from __future__ import annotations

import pytest
from devsteward.config import Config
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.lifecycle import LifecycleError, activate, recover
from devsteward.lint import lint
from devsteward.profiles.req.index import read_statuses
from devsteward.profiles.req.reqfile import parse_req

from conftest import write_index, write_req


def _cfg(tmp_path) -> Config:
    return Config(root=tmp_path, requirements_dir="reqs",
                  index_file="reqs/REQUIREMENTS_INDEX.md")


def test_activate_draft_to_open(tmp_path):
    """AC1: activate flips a draft REQ's frontmatter and index row to open, in sync, and
    `steward lint` stays green afterward."""
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="open")  # a north star so lint has a base
    write_req(req_dir, "REQ-007", status="draft")
    write_index(req_dir, [("REQ-001", "north", "OPEN", "–"),
                          ("REQ-007", "seven", "DRAFT", "–")])
    cfg = _cfg(tmp_path)

    res = activate(cfg, "REQ-007")

    assert res.changed and res.old_status == "draft" and res.new_status == "open"
    assert parse_req(req_dir / "REQ-007.md").status == "open"
    assert read_statuses(cfg.index_path)["REQ-007"] == "open"
    assert lint(cfg) == []  # index↔REQ invariant preserved


def test_activate_guards(tmp_path):
    """AC2: dropped→open works; done/superseded refuse with a supersede pointer; unknown id
    refuses; an already-active REQ is a no-op (changed=False, no raise)."""
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="open")
    write_req(req_dir, "REQ-002", status="dropped")
    write_req(req_dir, "REQ-003", status="done")
    write_req(req_dir, "REQ-004", status="superseded")
    write_index(req_dir, [("REQ-001", "one", "OPEN", "–"),
                          ("REQ-002", "two", "DROPPED", "–"),
                          ("REQ-003", "three", "DONE", "–"),
                          ("REQ-004", "four", "SUPERSEDED", "–")])
    cfg = _cfg(tmp_path)

    # dropped -> open is the one terminal that legitimately reverses.
    res = activate(cfg, "REQ-002")
    assert res.changed and res.new_status == "open"
    assert read_statuses(cfg.index_path)["REQ-002"] == "open"

    # done / superseded refuse, pointing at supersede.
    for rid in ("REQ-003", "REQ-004"):
        with pytest.raises(LifecycleError, match="supersed"):
            activate(cfg, rid)

    # unknown id refuses.
    with pytest.raises(LifecycleError):
        activate(cfg, "REQ-999")

    # already active -> no-op, no raise, no change.
    res = activate(cfg, "REQ-001")
    assert res.changed is False and res.old_status == "open"
    assert parse_req(req_dir / "REQ-001.md").status == "open"


def test_recover_flips_failed_step(project):
    """AC3: recover flips a REQ's FAILED ledger step to RECOVER and records an event; with
    no failed step it raises (the CLI maps that to a non-zero exit)."""
    led = Ledger(project)
    led.set_status("REQ-007:design", StepStatus.DONE)
    led.set_status("REQ-007:build", StepStatus.DONE)
    led.set_status("REQ-007:land", StepStatus.FAILED)
    led.save()

    res = recover(led, "REQ-007")

    assert res.steps == ["REQ-007:land"]
    reloaded = Ledger(project)
    assert reloaded.status_of("REQ-007:land") is StepStatus.RECOVER
    assert reloaded.status_of("REQ-007:build") is StepStatus.DONE  # untouched
    assert any(e["event"] == "step_recover" and e.get("req") == "REQ-007"
               for e in reloaded.events())

    # No failed step left -> refusal.
    with pytest.raises(LifecycleError, match="no failed step"):
        recover(reloaded, "REQ-007")
