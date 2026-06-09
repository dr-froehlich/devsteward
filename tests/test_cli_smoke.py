"""REQ-001 AC1 — the package imports and exposes the documented `steward` CLI."""

from __future__ import annotations

from types import SimpleNamespace

import devsteward
from click.testing import CliRunner
from devsteward import cli
from devsteward.cli import main


def test_version_string():
    assert devsteward.__version__


def test_cli_exposes_documented_commands():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for cmd in ("new", "advance", "run", "lint", "status", "decision"):
        assert cmd in result.output


def test_decision_subcommands():
    result = CliRunner().invoke(main, ["decision", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "answer" in result.output


class _FakeExecutor:
    """A build_executor stand-in for option-threading tests — does no real work."""

    ledger = SimpleNamespace(cursor_step=None, open_decisions=lambda: [])

    def run(self, *, max_steps=None, on_event=None):
        return []

    def advance_once(self, *, unattended=True, on_event=None):
        return None

    def next_eligible(self):
        return None


def test_run_account_and_model_options(monkeypatch):
    """REQ-025 AC10: run/advance accept --threshold/--model/--effort (+ --use) and thread
    them to the provider/runner via build_executor."""
    monkeypatch.setattr(cli, "_load_or_die", lambda: SimpleNamespace())

    for command in ("run", "advance"):
        captured: dict = {}

        def fake_build(cfg, **kwargs):
            captured.update(kwargs)
            return _FakeExecutor()

        monkeypatch.setattr(cli, "build_executor", fake_build)
        result = CliRunner().invoke(
            main,
            [command, "--use", "2", "--threshold", "80", "--model", "claude-x",
             "--effort", "low", "--quiet"],
        )
        assert result.exit_code == 0, result.output
        assert captured["use"] == 2
        assert captured["threshold"] == 80.0
        assert captured["model"] == "claude-x"
        assert captured["effort"] == "low"
        # The graceful-stop controller and visibility sink are wired in too.
        assert captured["stop"] is not None
        assert callable(captured["announce"])
