"""REQ-001 AC1 — the package imports and exposes the documented `steward` CLI."""

from __future__ import annotations

import devsteward
from click.testing import CliRunner
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
