"""REQ-007 — `steward new` stamps the scaffolding and the result lints."""

from __future__ import annotations

from click.testing import CliRunner

from devsteward.cli import main
from devsteward.config import load_config
from devsteward.lint import lint


def test_stamp_creates_project(tmp_path):
    target = tmp_path / "consumer"
    result = CliRunner().invoke(main, ["new", str(target)])
    assert result.exit_code == 0, result.output

    # .tmpl suffix stripped on stamp.
    assert (target / "CLAUDE.md").exists()
    assert not (target / "CLAUDE.md.tmpl").exists()
    assert (target / ".claude" / "settings.json").exists()
    assert (target / "docs" / "requirements" / "REQ-001.md").exists()
    assert (target / "docs" / "requirements" / "_templates" / "req.md").exists()
    assert (target / ".devsteward" / "config.yaml").exists()
    # Ledger initialized.
    assert (target / ".devsteward" / "state.yaml").exists()
    # All three skills stamped.
    for skill in ("intake", "advance", "bootstrap"):
        assert (target / ".claude" / "skills" / skill / "SKILL.md").exists()


def test_stamped_project_is_lintable(tmp_path):
    target = tmp_path / "consumer"
    CliRunner().invoke(main, ["new", str(target)])
    cfg = load_config(target)
    # The stamped REQ-001 still has {{placeholders}} but is schema-valid and indexed,
    # so lint reports no *schema* errors (placeholders are valid strings).
    problems = lint(cfg)
    schema_problems = [p for p in problems if "schema:" in p]
    assert schema_problems == [], schema_problems


def test_new_refuses_nonempty_dir(tmp_path):
    target = tmp_path / "consumer"
    target.mkdir()
    (target / "existing.txt").write_text("x", encoding="utf-8")
    result = CliRunner().invoke(main, ["new", str(target)])
    assert result.exit_code != 0
    assert "not empty" in result.output
