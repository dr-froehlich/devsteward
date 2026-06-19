"""REQ-026 AC1–AC3 — the operator verbs `steward activate` and `steward repeat` (the
recovery verb renamed from `recover` by REQ-054). REQ-054 AC1/AC4 also live here."""

from __future__ import annotations

import pytest
from click.testing import CliRunner
from devsteward.cli import main as cli_main
from devsteward.config import Config
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.lifecycle import LifecycleError, activate, repeat, rework
from devsteward.lint import lint
from devsteward.profiles.req.index import read_statuses
from devsteward.profiles.req.reqfile import parse_req

from conftest import write_index, write_req
from test_transaction_boundary import _init_git, _scaffold  # proven git+config scaffold


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


def test_repeat_flips_failed_step(project):
    """REQ-026 AC3 / REQ-054 AC1: `repeat` (renamed from `recover`) flips a REQ's FAILED
    ledger step to RECOVER and records the `step_recover` event (the internal symbol and
    event name are unchanged — REQ-054 D4); with no failed step it raises (the CLI maps
    that to a non-zero exit)."""
    led = Ledger(project)
    led.set_status("REQ-007:design", StepStatus.DONE)
    led.set_status("REQ-007:build", StepStatus.DONE)
    led.set_status("REQ-007:land", StepStatus.FAILED)
    led.save()

    res = repeat(led, "REQ-007")

    assert res.steps == ["REQ-007:land"]
    reloaded = Ledger(project)
    assert reloaded.status_of("REQ-007:land") is StepStatus.RECOVER
    assert reloaded.status_of("REQ-007:build") is StepStatus.DONE  # untouched
    assert any(e["event"] == "step_recover" and e.get("req") == "REQ-007"
               for e in reloaded.events())

    # No failed step left -> refusal.
    with pytest.raises(LifecycleError, match="no failed step"):
        repeat(reloaded, "REQ-007")


def test_messages_name_repeat_not_recover(tmp_path, monkeypatch):
    """REQ-054 AC4: operator-facing messages name `steward repeat`, not `steward recover`.
    The `repeat` success line uses the new verb, and the `rework` refusal's cross-reference
    points at `steward repeat`; no operator-facing string still reads `steward recover`."""
    # An artifact AC gives the REQ a validate step, so `rework` reaches the cross-reference.
    _scaffold(tmp_path, acs=(("AC1", "true", "artifact"),))
    _init_git(tmp_path)
    monkeypatch.chdir(tmp_path)

    # (a) the `repeat` success line names the new verb (not `steward recover`).
    led = Ledger(tmp_path)
    led.set_status("REQ-001:develop", StepStatus.FAILED)
    led.save()
    out = CliRunner().invoke(cli_main, ["repeat", "REQ-001"], catch_exceptions=False)
    assert out.exit_code == 0, out.output
    assert "repeat" in out.output and "steward recover" not in out.output

    # (b) the `rework` refusal's cross-reference points at `steward repeat`, not `recover`.
    with pytest.raises(LifecycleError) as exc:
        rework(Config(root=tmp_path), Ledger(tmp_path), "REQ-001")
    msg = str(exc.value)
    assert "steward repeat REQ-001" in msg
    assert "steward recover" not in msg
