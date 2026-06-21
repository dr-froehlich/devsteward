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
    for cmd in ("new", "advance", "run", "lint", "status", "decision", "activate", "repeat"):
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

    def eligible_steps(self, only=None):
        return []

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
    """REQ-025 AC10: run/advance accept --threshold/--model/--effort and thread them to the
    provider/runner via build_executor. (The account pin is its own test below.)"""
    monkeypatch.setattr(cli, "_load_or_die", lambda: SimpleNamespace())

    for command in ("run", "advance"):
        captured: dict = {}

        def fake_build(cfg, **kwargs):
            captured.update(kwargs)
            return _FakeExecutor()

        monkeypatch.setattr(cli, "build_executor", fake_build)
        result = CliRunner().invoke(
            main,
            [command, "--threshold", "80", "--model", "claude-x",
             "--effort", "low", "--quiet"],
        )
        assert result.exit_code == 0, result.output
        assert captured["threshold"] == 80.0
        assert captured["model"] == "claude-x"
        assert captured["effort"] == "low"
        # The graceful-stop controller and visibility sink are wired in too.
        assert captured["stop"] is not None
        assert callable(captured["announce"])


def test_run_advance_thread_pin(monkeypatch):
    """REQ-061 AC3: `advance`/`run --pin N` thread N through build_executor (which carries it
    onto ClauderAccountProvider); and the removed `--use` flag is no longer accepted."""
    monkeypatch.setattr(cli, "_load_or_die", lambda: SimpleNamespace())

    for command in ("run", "advance"):
        captured: dict = {}

        def fake_build(cfg, **kwargs):
            captured.update(kwargs)
            return _FakeExecutor()

        monkeypatch.setattr(cli, "build_executor", fake_build)
        result = CliRunner().invoke(main, [command, "--pin", "2", "--quiet"])
        assert result.exit_code == 0, result.output
        assert captured["pin"] == 2

        # The old `--use` flag was hard-renamed (Decision 2) — it is now an unknown option.
        rejected = CliRunner().invoke(main, [command, "--use", "2", "--quiet"])
        assert rejected.exit_code != 0
        assert "--use" in rejected.output or "no such option" in rejected.output.lower()


def test_positional_target_scopes_like_only(monkeypatch):
    """REQ-042 AC1: `advance REQ-X` / `run REQ-X` are accepted (no 'unexpected extra
    argument') and thread `only="REQ-X"` into the executor exactly like `--only REQ-X`."""
    monkeypatch.setattr(cli, "_load_or_die", lambda: SimpleNamespace())

    for command in ("advance", "run"):
        seen: list[str | None] = []

        class _Cap(_FakeExecutor):
            def advance_once(self, *, only=None, unattended=True, on_event=None):
                seen.append(only)
                return None

            def run(self, *, only=None, max_steps=None, on_event=None):
                seen.append(only)
                return []

        monkeypatch.setattr(cli, "build_executor", lambda cfg, **kw: _Cap())
        positional = CliRunner().invoke(main, [command, "REQ-X", "--quiet"])
        # The positional is accepted — click does not reject it as an extra argument.
        assert "unexpected extra argument" not in positional.output
        flagged = CliRunner().invoke(main, [command, "--only", "REQ-X", "--quiet"])
        assert "unexpected extra argument" not in flagged.output
        # Both spellings resolve to the same `only` target threaded into the executor.
        assert seen == ["REQ-X", "REQ-X"]


def test_positional_ineligible_errors(monkeypatch):
    """REQ-042 AC2: naming a REQ with no eligible step exits non-zero with the same
    activate-first/why message `--only` produces (and never auto-activates a draft)."""
    monkeypatch.setattr(cli, "_load_or_die", lambda: SimpleNamespace())
    monkeypatch.setattr(cli, "build_executor", lambda cfg, **kw: _FakeExecutor())

    for command in ("advance", "run"):
        result = CliRunner().invoke(main, [command, "REQ-X", "--quiet"])
        assert result.exit_code != 0, result.output
        assert "REQ-X" in result.output and "no eligible step" in result.output
        # The message points at explicit activation; nothing was activated for us.
        assert "activate" not in result.output or "activate it first" in result.output


def test_positional_and_only_conflict(monkeypatch):
    """REQ-042 AC3: a positional REQ_ID and `--only` together are mutually exclusive."""
    monkeypatch.setattr(cli, "_load_or_die", lambda: SimpleNamespace())
    monkeypatch.setattr(cli, "build_executor", lambda cfg, **kw: _FakeExecutor())

    for command in ("advance", "run"):
        result = CliRunner().invoke(main, [command, "REQ-X", "--only", "REQ-Y", "--quiet"])
        assert result.exit_code != 0, result.output
        assert "not both" in result.output


def test_multi_eligible_prints_steer_hint(monkeypatch):
    """REQ-042 AC4: plain `advance`/`run` with >1 eligible REQ still picks the lowest id,
    but now lists the eligible ids and the `steward <command> REQ-NNN` steer syntax."""
    monkeypatch.setattr(cli, "_load_or_die", lambda: SimpleNamespace())
    low = SimpleNamespace(req="REQ-007", id="REQ-007:develop")
    high = SimpleNamespace(req="REQ-019", id="REQ-019:develop")

    class _Multi(_FakeExecutor):
        def eligible_steps(self, only=None):
            return [low, high]

        def next_eligible(self, only=None):
            return low

    monkeypatch.setattr(cli, "build_executor", lambda cfg, **kw: _Multi())

    for command in ("advance", "run"):
        result = CliRunner().invoke(main, [command, "--quiet"])
        assert result.exit_code == 0, result.output
        assert "REQ-007" in result.output and "REQ-019" in result.output
        # The lowest id is the one chosen, and the steer syntax is taught.
        assert "Advancing REQ-007" in result.output
        assert f"steward {command} REQ-NNN" in result.output


def test_status_failed_step_names_repeat(tmp_path, monkeypatch):
    """REQ-056 AC4 — the forward path is named and the decision surface holds only real forks:
    `steward status` annotates a FAILED step with `steward repeat REQ` as its forward verb, and
    after a repair-exhausted / land-refused failure (which parks no decision) the step does not
    appear in `steward decision list`."""
    from devsteward.core.ledger import Ledger
    from devsteward.core.model import StepStatus
    from test_transaction_boundary import _init_git, _scaffold

    _scaffold(tmp_path)  # REQ-001 (regression AC) + ledger + single-account config
    _init_git(tmp_path)
    monkeypatch.chdir(tmp_path)

    # A D-/H-failed develop step is recorded FAILED with no decision parked (the new behaviour).
    led = Ledger(tmp_path)
    led.set_status("REQ-001:develop", StepStatus.FAILED)
    led.save()

    status = CliRunner().invoke(main, ["status"])
    assert status.exit_code == 0, status.output
    assert "REQ-001:develop" in status.output and "failed" in status.output
    assert "steward repeat REQ-001" in status.output  # the forward verb is named

    decisions = CliRunner().invoke(main, ["decision", "list"])
    assert decisions.exit_code == 0, decisions.output
    assert "No parked decisions." in decisions.output  # the failure parked none


def test_status_all_done_terminal_state(tmp_path, monkeypatch):
    """REQ-060 AC1 — a caught-up project reports an honest terminal state: with its only REQ
    `done` and the cursor pinned to that now-done step, `steward status` prints the
    all-caught-up line pointing at `/intake` and does NOT print a `cursor:` line naming the
    done/non-derivable step."""
    from devsteward.core.ledger import Ledger
    from devsteward.core.model import StepStatus
    from test_transaction_boundary import _index, _init_git, _write_req

    req_dir = tmp_path / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", [("AC1", "true", "regression")], status="done")
    _index(req_dir, ("REQ-001", "DONE"))
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "0001-plan.md").write_text("# Plan 0001\n\nCovers REQ-001.\n", encoding="utf-8")
    (tmp_path / ".devsteward").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".devsteward" / "config.yaml").write_text(
        "accounts:\n  provider: single\n", encoding="utf-8"
    )
    Ledger.init(tmp_path, profile="req")
    _init_git(tmp_path)
    monkeypatch.chdir(tmp_path)

    # the real-world stale cursor: pinned to the now-done final step, never cleared
    led = Ledger(tmp_path)
    led.set_status("REQ-001:develop", StepStatus.DONE)
    led.set_cursor("REQ-001:develop")
    led.save()

    status = CliRunner().invoke(main, ["status"])
    assert status.exit_code == 0, status.output
    # honest terminal: the forward path is named ...
    assert "/intake" in status.output
    # ... and the stale cursor naming the done step is NOT surfaced
    assert "cursor:" not in status.output
    assert "REQ-001:develop" not in status.output


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
