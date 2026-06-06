"""REQ-008 — the account provider degrades without cswap and pins with --use."""

from __future__ import annotations

from devsteward.core import accounts


def test_degrades_without_cswap(monkeypatch):
    monkeypatch.setattr(accounts.shutil, "which", lambda name: None)
    provider = accounts.CswapAccountProvider()
    assert not provider.available
    assert provider.claude_argv() == ["claude"]
    ok, reason = provider.precheck()
    assert ok is True
    assert "without quota check" in reason


def test_use_pins_account(monkeypatch):
    monkeypatch.setattr(accounts.shutil, "which", lambda name: "/usr/bin/cswap")
    provider = accounts.CswapAccountProvider(use=2)
    argv = provider.claude_argv()
    assert argv[0] == "/usr/bin/cswap"
    assert "--use" in argv and argv[argv.index("--use") + 1] == "2"
    assert argv[-1] == "claude"


def test_single_account_provider():
    provider = accounts.SingleAccountProvider()
    assert provider.claude_argv() == ["claude"]
    assert provider.precheck()[0] is True
