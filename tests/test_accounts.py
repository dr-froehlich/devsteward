"""REQ-008 + REQ-012 — the account provider speaks the claude-swap 0.11 switcher CLI:
it degrades without cswap, switches the active account with ``--switch-to`` (never wraps
``claude``), and keeps every cswap interaction non-fatal."""

from __future__ import annotations

from types import SimpleNamespace

from devsteward.core import accounts


def _fake_run(record, *, returncode=0):
    """A ``subprocess.run`` stand-in that records argv and returns a fixed exit code."""

    def run(argv, **kwargs):
        record.append(argv)
        return SimpleNamespace(returncode=returncode, stdout="", stderr="")

    return run


def test_degrades_without_cswap(monkeypatch):
    monkeypatch.setattr(accounts.shutil, "which", lambda name: None)
    provider = accounts.CswapAccountProvider()
    assert not provider.available
    assert provider.claude_argv() == ["claude"]
    ok, reason = provider.precheck()
    assert ok is True
    assert "without quota check" in reason


def test_use_switches_account(monkeypatch):
    """AC1: claude_argv() is plain ['claude'] (no 'exec'); precheck switches via --switch-to N."""
    monkeypatch.setattr(accounts.shutil, "which", lambda name: "/usr/bin/cswap")
    calls: list[list[str]] = []
    monkeypatch.setattr(accounts.subprocess, "run", _fake_run(calls))

    provider = accounts.CswapAccountProvider(use=2)
    argv = provider.claude_argv()
    assert argv == ["claude"]
    assert "exec" not in argv and "--use" not in argv

    ok, reason = provider.precheck()
    assert ok is True
    # The account was activated by switching, not by argv injection.
    assert ["/usr/bin/cswap", "--switch-to", "2"] in calls
    # …and the status gate uses the flag form, never a `status` positional.
    assert ["/usr/bin/cswap", "--status"] in calls


def test_precheck_status_non_fatal(monkeypatch):
    """AC2: --status degrades to ok=True on non-zero exit, missing binary, or timeout."""
    monkeypatch.setattr(accounts.shutil, "which", lambda name: "/usr/bin/cswap")

    # Non-zero exit from --status must not block.
    monkeypatch.setattr(accounts.subprocess, "run", _fake_run([], returncode=1))
    ok, _ = accounts.CswapAccountProvider().precheck()
    assert ok is True

    # A timeout degrades to "proceed".
    def raise_timeout(argv, **kwargs):
        raise accounts.subprocess.TimeoutExpired(cmd=argv, timeout=30)

    monkeypatch.setattr(accounts.subprocess, "run", raise_timeout)
    ok, _ = accounts.CswapAccountProvider().precheck()
    assert ok is True

    # An OS error (e.g. binary vanished mid-run) degrades to "proceed".
    def raise_oserror(argv, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(accounts.subprocess, "run", raise_oserror)
    ok, _ = accounts.CswapAccountProvider().precheck()
    assert ok is True

    # A missing binary degrades to "proceed" without ever shelling out.
    monkeypatch.setattr(accounts.shutil, "which", lambda name: None)
    ok, _ = accounts.CswapAccountProvider().precheck()
    assert ok is True


def test_failed_switch_does_not_block(monkeypatch):
    """A failed --switch-to runs on the active account rather than blocking the run."""
    monkeypatch.setattr(accounts.shutil, "which", lambda name: "/usr/bin/cswap")
    monkeypatch.setattr(accounts.subprocess, "run", _fake_run([], returncode=3))
    ok, reason = accounts.CswapAccountProvider(use=5).precheck()
    assert ok is True
    assert "switch-to 5" in reason


def test_single_account_provider():
    provider = accounts.SingleAccountProvider()
    assert provider.claude_argv() == ["claude"]
    assert provider.precheck()[0] is True
