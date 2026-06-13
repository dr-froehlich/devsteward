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
    for cmd in ("new", "advance", "run", "lint", "status", "decision", "activate", "recover"):
        assert cmd in result.output


def test_decision_subcommands():
    result = CliRunner().invoke(main, ["decision", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "answer" in result.output


class _FakeExecutor:
    """A build_executor stand-in for option-threading tests — does no real work."""

    ledger = SimpleNamespace(cursor_step=None, open_decisions=lambda: [])

    def run(self, *, only=None, max_steps=None, on_event=None):
        return []

    def advance_once(self, *, only=None, unattended=True, on_event=None):
        return None

    def next_eligible(self, only=None):
        return None

    def only_ineligibility_reason(self, req_id):
        return f"{req_id} has no eligible step — it is not active."


def test_only_not_eligible_errors(monkeypatch):
    """REQ-026 AC7: `run`/`advance --only REQ-X` where X has no eligible step exits non-zero
    with a reason (not a benign "nothing eligible")."""
    monkeypatch.setattr(cli, "_load_or_die", lambda: SimpleNamespace())
    monkeypatch.setattr(cli, "build_executor", lambda cfg, **kw: _FakeExecutor())

    for command in ("run", "advance"):
        result = CliRunner().invoke(main, [command, "--only", "REQ-X", "--quiet"])
        assert result.exit_code != 0, result.output
        assert "REQ-X" in result.output and "no eligible step" in result.output


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


def test_validate_wires_announce_and_stop(monkeypatch):
    """REQ-025: `validate` must thread the visibility sink + graceful-stop controller into
    build_executor like run/advance — otherwise a cswap quota wait sleeps with no output and
    looks like a silent hang."""
    monkeypatch.setattr(cli, "_load_or_die", lambda: SimpleNamespace())
    captured: dict = {}

    def fake_build(cfg, **kwargs):
        captured.update(kwargs)
        # validate_runner=None bails right after build_executor; we only assert the wiring.
        return SimpleNamespace(validate_runner=None)

    monkeypatch.setattr(cli, "build_executor", fake_build)
    result = CliRunner().invoke(main, ["validate", "REQ-X"])
    assert result.exit_code != 0, result.output
    assert captured["stop"] is not None
    assert callable(captured["announce"])
