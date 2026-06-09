"""REQ-025 — the account provider is numeric, visible, and gate-and-rotate.

It reads cswap's cached ``usage.json`` for per-slot 5h/7d budget, gates on a fixed threshold,
stays on the current account until it saturates then rotates to the lowest-7d below-gate slot
(or pins with ``use``), waits interruptibly through a reset, announces every decision, and
degrades to "proceed on the current account" whenever cswap or its usage data is absent.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from devsteward.core import accounts


# -- fixtures ------------------------------------------------------------------


def _write_usage(data_dir: Path, slots: dict[int, tuple]) -> None:
    """``slots``: ``{slot: (pct_5h, pct_7d, countdown, clock)}`` → cache/usage.json."""
    cache = data_dir / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    data = {}
    for slot, (p5, p7, countdown, clock) in slots.items():
        data[str(slot)] = {
            "five_hour": {"pct": p5, "countdown": countdown, "clock": clock},
            "seven_day": {"pct": p7},
        }
    (cache / "usage.json").write_text(json.dumps({"data": data}))


def _write_sequence(data_dir: Path, active: int) -> None:
    (data_dir / "sequence.json").write_text(json.dumps({"activeAccountNumber": active}))


def _recording_run(calls: list, *, on_list=None):
    """A ``subprocess.run`` stand-in: records argv, lets ``on_list`` mutate the cache when
    ``cswap --list`` is invoked, and returns a zero exit."""

    def run(argv, **kwargs):
        calls.append(argv)
        if "--list" in argv and on_list is not None:
            on_list()
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return run


def _provider(monkeypatch, **kwargs):
    monkeypatch.setattr(accounts.shutil, "which", lambda name: "/usr/bin/cswap")
    kwargs.setdefault("sleep", lambda _s: None)
    return accounts.CswapAccountProvider(**kwargs)


# -- AC1 -----------------------------------------------------------------------


def test_usage_snapshot_parses_and_degrades(tmp_path):
    _write_usage(tmp_path, {0: (80, 40, "1h 30m", "14:00"), 1: (10, 5, "2d 4h", "")})
    snap = accounts.usage_snapshot(tmp_path, run=lambda *a, **k: None)
    assert set(snap) == {0, 1}
    assert snap[0].pct_5h == 80 and snap[0].pct_7d == 40
    assert snap[0].minutes_to_5h_reset == 90 and snap[0].clock_5h_reset == "14:00"
    assert snap[1].minutes_to_5h_reset == 2 * 1440 + 4 * 60

    # Missing file → degrade signal (empty dict), never an exception.
    assert accounts.usage_snapshot(tmp_path / "nope", run=lambda *a, **k: None) == {}

    # Malformed JSON → degrade signal too.
    (tmp_path / "cache" / "usage.json").write_text("{ not json")
    assert accounts.usage_snapshot(tmp_path, run=lambda *a, **k: None) == {}


# -- AC2 -----------------------------------------------------------------------


def test_gate_rotates_when_current_saturates(monkeypatch, tmp_path):
    # slot0 saturated; slot1 and slot2 below — slot1 has the lower 7d.
    _write_usage(tmp_path, {0: (80, 50, "1h", "14:00"), 1: (10, 5, "", ""), 2: (20, 30, "", "")})
    calls: list = []
    _write_sequence(tmp_path, active=0)
    p = _provider(monkeypatch, threshold=70, data_dir=tmp_path, run=_recording_run(calls))
    ok, reason = p.precheck()
    assert ok is True
    assert ["/usr/bin/cswap", "--switch-to", "1"] in calls  # lower-7d below-gate slot
    assert "#1" in reason

    # When the current account is already below the gate, stay put — no flapping.
    _write_sequence(tmp_path, active=1)
    calls.clear()
    ok, reason = _provider(
        monkeypatch, threshold=70, data_dir=tmp_path, run=_recording_run(calls)
    ).precheck()
    assert ok is True
    assert not any("--switch-to" in c for c in calls)
    assert "staying on #1" in reason


# -- AC3 -----------------------------------------------------------------------


def test_threshold_fixed_and_overridable(monkeypatch, tmp_path):
    # A fraction and the equivalent percent normalise to the same fixed percent.
    assert _provider(monkeypatch, threshold=0.70).threshold == 70.0
    assert _provider(monkeypatch, threshold=70).threshold == 70.0
    assert _provider(monkeypatch, threshold=90).threshold == 90.0

    _write_usage(tmp_path, {0: (65, 30, "1h", "14:00")})
    _write_sequence(tmp_path, active=0)

    # 65% is below a 70 gate → proceed.
    ok, _ = _provider(monkeypatch, threshold=0.70, data_dir=tmp_path,
                      run=lambda *a, **k: None).precheck()
    assert ok is True

    # …and at or above a tighter override it gates. The threshold is fixed: it never
    # tightens from observed cost (there is no cost-history input at all).
    n = {"i": 0}

    def stop():
        n["i"] += 1
        return n["i"] > 1  # let the first (top-of-loop) check pass, then stop the wait

    p = _provider(monkeypatch, threshold=60, data_dir=tmp_path, run=lambda *a, **k: None,
                  should_stop=stop)
    assert p.threshold == 60.0
    ok, reason = p.precheck()
    assert ok is False and "stop" in reason  # 65 ≥ 60 ⇒ saturated ⇒ waited, then stopped
    assert p.threshold == 60.0  # unchanged — no adaptive tightening


# -- AC4 -----------------------------------------------------------------------


def test_use_pins_and_waits_own_reset(monkeypatch, tmp_path):
    # Pinned slot 2 starts saturated; the active slot is 0.
    _write_usage(tmp_path, {0: (10, 5, "", ""), 1: (10, 5, "", ""), 2: (95, 60, "30m", "14:00")})
    _write_sequence(tmp_path, active=0)

    def free_slot_2():  # cswap --list refreshes the cache: slot 2 has now reset
        _write_usage(tmp_path, {0: (10, 5, "", ""), 1: (10, 5, "", ""), 2: (12, 60, "", "")})

    calls: list = []
    p = _provider(monkeypatch, use=2, threshold=70, data_dir=tmp_path,
                  run=_recording_run(calls, on_list=free_slot_2))
    ok, reason = p.precheck()
    assert ok is True
    # It switched to the pinned slot and waited for *its own* reset — never another slot.
    assert ["/usr/bin/cswap", "--switch-to", "2"] in calls
    assert not any(c[:2] == ["/usr/bin/cswap", "--switch-to"] and c[2] != "2" for c in calls)
    assert "pinned" in reason


# -- AC5 -----------------------------------------------------------------------


def test_quota_wait_is_interruptible(monkeypatch, tmp_path):
    # Both accounts saturated → the loop waits; a stop set during the wait returns promptly.
    _write_usage(tmp_path, {0: (90, 50, "2h", "14:00"), 1: (95, 60, "3h", "15:00")})
    _write_sequence(tmp_path, active=0)
    n = {"i": 0}

    def stop():
        n["i"] += 1
        return n["i"] > 1

    sink: list = []
    p = _provider(monkeypatch, threshold=70, data_dir=tmp_path, run=lambda *a, **k: None,
                  should_stop=stop, announce=sink.append)
    ok, reason = p.precheck()
    assert ok is False and "stop" in reason
    assert any("all saturated" in m for m in sink)  # it announced the wait before stopping


# -- AC6 -----------------------------------------------------------------------


def test_announces_utilization_and_switches(monkeypatch, tmp_path):
    _write_usage(tmp_path, {0: (80, 50, "1h", "14:00"), 1: (10, 5, "", "")})
    _write_sequence(tmp_path, active=0)
    sink: list = []
    p = _provider(monkeypatch, threshold=70, data_dir=tmp_path, run=_recording_run([]),
                  announce=sink.append)
    ok, _ = p.precheck()
    assert ok is True
    blob = "\n".join(sink)
    assert "#0: 5h 80%" in blob and "#1: 5h 10%" in blob  # active-slot utilization summary
    assert "switching to #1" in blob  # the switch is visible


# -- AC7 -----------------------------------------------------------------------


def test_degrades_without_cswap(monkeypatch, tmp_path):
    # cswap binary absent → proceed on the current account, gate skipped.
    monkeypatch.setattr(accounts.shutil, "which", lambda name: None)
    provider = accounts.CswapAccountProvider()
    assert not provider.available
    assert provider.claude_argv() == ["claude"]
    ok, reason = provider.precheck()
    assert ok is True and "without quota check" in reason

    # cswap present but no usage.json → still degrade to "proceed", never block or switch.
    calls: list = []
    p = _provider(monkeypatch, data_dir=tmp_path, run=_recording_run(calls))
    ok, reason = p.precheck()
    assert ok is True and "without quota check" in reason
    assert not any("--switch-to" in c for c in calls)


def test_single_account_provider():
    provider = accounts.SingleAccountProvider()
    assert provider.claude_argv() == ["claude"]
    assert provider.precheck()[0] is True
