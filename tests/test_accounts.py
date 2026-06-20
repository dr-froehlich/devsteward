"""REQ-058 — the account provider delegates the per-step budget gate to ``clauder``.

The provider shells ``clauder gate --threshold T --json`` at every step boundary and maps
clauder's verdict (exit code + JSON) onto the ``precheck() -> (ok, reason)`` contract:
proceed/switch (0) → admit; wait (75) → sleep ``wait_seconds`` interruptibly then re-gate;
unsatisfiable (69) → stop. All account interaction routes through that single ``clauder gate``
chokepoint — no direct cswap call, no ``usage.json`` read — and it degrades to "proceed
without quota check" when ``clauder`` is not on PATH.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from devsteward.core import accounts


# -- fixtures ------------------------------------------------------------------


def _gate_run(scripted: list[tuple[int, dict]], *, calls: list | None = None):
    """A ``subprocess.run`` stand-in for ``clauder gate``: returns each scripted
    ``(returncode, json_body)`` in turn (the last one repeats), recording argv into ``calls``."""

    state = {"i": 0}

    def run(argv, **kwargs):
        if calls is not None:
            calls.append(argv)
        rc, body = scripted[min(state["i"], len(scripted) - 1)]
        state["i"] += 1
        return SimpleNamespace(returncode=rc, stdout=json.dumps(body), stderr="")

    return run


def _provider(monkeypatch, *, scripted, calls=None, **kwargs):
    monkeypatch.setattr(accounts.shutil, "which", lambda name: "/usr/bin/clauder")
    kwargs.setdefault("sleep", lambda _s: None)
    return accounts.ClauderAccountProvider(run=_gate_run(scripted, calls=calls), **kwargs)


# -- AC1: delegation + verdict mapping -----------------------------------------


def test_clauder_gate_delegation(monkeypatch):
    # proceed (exit 0) → admit; and the configured --threshold is passed through.
    calls: list = []
    p = _provider(
        monkeypatch,
        threshold=80,
        calls=calls,
        scripted=[(0, {"decision": "proceed", "account": 1, "reason": "proceed-active"})],
    )
    ok, reason = p.precheck()
    assert ok is True
    argv = calls[0]
    assert argv[:2] == ["/usr/bin/clauder", "gate"]
    assert "--threshold" in argv and "80" in argv and "--json" in argv
    assert "proceed" in reason

    # switch (exit 0) → admit (clauder already performed the switch).
    ok, reason = _provider(
        monkeypatch,
        scripted=[(0, {"decision": "switch", "account": 2, "reason": "switch-to-2"})],
    ).precheck()
    assert ok is True and "switch" in reason

    # wait (exit 75, wait_seconds=N) → sleep N interruptibly then re-gate; on the second gate
    # proceed admits. The slept duration is the verdict's wait_seconds.
    slept: list = []
    ok, reason = _provider(
        monkeypatch,
        sleep=slept.append,
        scripted=[(75, {"decision": "wait", "wait_seconds": 12, "reason": "soonest-reset"}),
                  (0, {"decision": "proceed", "reason": "proceed-active"})],
    ).precheck()
    assert ok is True and "proceed" in reason
    assert sum(slept) == 12  # it waited the verdict's duration before re-gating

    # wait, then a stop requested *during* the wait → ok=False (the run ends, not the gate).
    n = {"i": 0}

    def stop():
        n["i"] += 1
        return n["i"] > 1  # pass the first top-of-loop check, then trip during the wait

    ok, reason = _provider(
        monkeypatch,
        should_stop=stop,
        scripted=[(75, {"decision": "wait", "wait_seconds": 99, "reason": "soonest-reset"})],
    ).precheck()
    assert ok is False and "stop" in reason

    # unsatisfiable (exit 69) → ok=False with a clear reason (the pool can't carry the job).
    ok, reason = _provider(
        monkeypatch,
        scripted=[(69, {"decision": "unsatisfiable", "reason": "unsatisfiable-exceeds-pool"})],
    ).precheck()
    assert ok is False
    assert "unsatisfiable" in reason and "exceeds-pool" in reason


# -- AC2: single chokepoint + degradation --------------------------------------


def test_no_direct_cswap_and_degrades_without_clauder(monkeypatch):
    # The cswap machinery this REQ removed is gone — no second budget code path remains.
    for removed in ("CswapAccountProvider", "usage_snapshot", "AccountUsage"):
        assert not hasattr(accounts, removed), f"{removed} should be removed (REQ-058 D4)"

    # All account interaction routes through the single `clauder gate` invocation: the
    # provider issues no `cswap` subprocess and reads no usage.json.
    calls: list = []
    ok, _ = _provider(
        monkeypatch,
        calls=calls,
        scripted=[(0, {"decision": "proceed", "reason": "proceed-active"})],
    ).precheck()
    assert ok is True
    assert len(calls) == 1
    assert all(argv[0] == "/usr/bin/clauder" for argv in calls)
    assert not any("cswap" in part for argv in calls for part in argv)

    # clauder not on PATH → degrade to (True, "proceeding without quota check"), no raise.
    monkeypatch.setattr(accounts.shutil, "which", lambda name: None)
    provider = accounts.ClauderAccountProvider()
    assert not provider.available
    assert provider.claude_argv() == ["claude"]
    ok, reason = provider.precheck()
    assert ok is True and "proceeding without quota check" in reason


# -- the minimal single-account provider stays -----------------------------------


def test_single_account_provider():
    provider = accounts.SingleAccountProvider()
    assert provider.claude_argv() == ["claude"]
    assert provider.precheck()[0] is True
