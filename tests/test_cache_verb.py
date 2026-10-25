"""REQ-082 — ``steward cache``: session prompt-cache warmth read off the filesystem.

Every test points ``CLAUDE_PROJECTS_DIR`` (the Decision 5 seam) at a temp tree, so the suite
never reads the operator's real ``~/.claude`` and stays green in a clean checkout.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from devsteward import cache as cache_mod
from devsteward.cli import main


def _git_repo(root: Path) -> Path:
    """A real (empty) git repo — ``project_root`` shells out to ``git rev-parse``."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    return root


def _age(path: Path, minutes: float) -> None:
    """Backdate ``path``'s mtime to a known age — the verb's only clock."""
    when = time.time() - minutes * 60.0
    os.utime(path, (when, when))


def _transcript(session_dir: Path, name: str, *, minutes: float) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    p = session_dir / name
    p.write_text('{"type":"user"}\n', encoding="utf-8")
    _age(p, minutes)
    return p


def _session_dir(projects: Path, root: Path) -> Path:
    return projects / cache_mod.project_slug(root)


def _snapshot(root: Path) -> dict[str, tuple[bytes | None, int | None]]:
    """Contents *and* mtimes of every file under ``root`` — the read-only oracle."""
    snap: dict[str, tuple[bytes | None, int | None]] = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_file():
            snap[rel] = (p.read_bytes(), p.stat().st_mtime_ns)
        else:
            snap[rel] = (None, None)
    return snap


@pytest.fixture
def warm_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A git repo + a fake projects tree holding one transcript, wired through the seam."""
    repo = _git_repo(tmp_path / "repo")
    projects = tmp_path / "projects"
    session_dir = _session_dir(projects, repo)
    transcript = _transcript(session_dir, "abc123.jsonl", minutes=10)
    monkeypatch.setenv(cache_mod.PROJECTS_DIR_ENV, str(projects))
    monkeypatch.chdir(repo)
    return repo, projects, session_dir, transcript


# -- AC1: slug + discovery ----------------------------------------------------


def test_slug_discovery_encodes_absolute_path():
    """The slug is the absolute path with '/' → '-' (the real tree's encoding)."""
    assert cache_mod.project_slug(Path("/home/x/p")) == "-home-x-p"


def test_slug_discovery_resolves_git_toplevel_from_subdirectory(tmp_path: Path):
    """Claude Code slugs its launch dir (the repo root); steward may run from a subdir."""
    repo = _git_repo(tmp_path / "repo")
    sub = repo / "devsteward" / "core"
    sub.mkdir(parents=True)

    assert cache_mod.project_root(cwd=sub) == repo.resolve()


def test_slug_discovery_falls_back_to_cwd_outside_a_repo(tmp_path: Path):
    """Not a git repo → the invoking directory itself, never an exception (Decision 4)."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    assert cache_mod.project_root(cwd=plain) == plain.resolve()


def test_slug_discovery_selects_newest_jsonl_only(tmp_path: Path, monkeypatch):
    """The newest .jsonl in *this* project's dir wins — other projects, non-jsonl files and
    the memory/ subdir are not request clocks."""
    repo = _git_repo(tmp_path / "repo")
    projects = tmp_path / "projects"
    session_dir = _session_dir(projects, repo)

    _transcript(session_dir, "old.jsonl", minutes=120)
    newest = _transcript(session_dir, "new.jsonl", minutes=5)
    # Decoys: a newer non-transcript, a nested jsonl, and another project's newer session.
    _transcript(session_dir, "notes.md", minutes=1)
    _transcript(session_dir, "transcript.txt", minutes=1)
    _transcript(session_dir / "memory", "MEMORY.jsonl", minutes=1)
    _transcript(projects / "-some-other-project", "other.jsonl", minutes=1)

    monkeypatch.setenv(cache_mod.PROJECTS_DIR_ENV, str(projects))
    report = cache_mod.probe(cwd=repo)

    assert report.transcript == newest
    assert report.session_id == "new"
    assert report.session_dir == session_dir


def test_slug_discovery_projects_dir_honours_the_seam(tmp_path: Path, monkeypatch):
    """$CLAUDE_PROJECTS_DIR overrides ~/.claude/projects; unset falls back to the default."""
    monkeypatch.setenv(cache_mod.PROJECTS_DIR_ENV, str(tmp_path / "fake"))
    assert cache_mod.projects_dir() == tmp_path / "fake"

    monkeypatch.delenv(cache_mod.PROJECTS_DIR_ENV)
    assert cache_mod.projects_dir() == Path.home() / ".claude" / "projects"


# -- AC2: verdict + TTL -------------------------------------------------------


def test_verdict_ttl_default_threshold_is_sixty_minutes(warm_project):
    """A 10-minute-old transcript is WARM under the default 60-minute TTL."""
    assert cache_mod.DEFAULT_TTL_MINUTES == 60

    result = CliRunner().invoke(main, ["cache"])

    assert "WARM" in result.stdout, result.output
    assert "cold" not in result.stdout
    assert "ttl 60m" in result.stdout


def test_verdict_ttl_override_flips_the_verdict(warm_project):
    """--ttl 5 replaces the threshold: the same 10-minute transcript is now cold."""
    result = CliRunner().invoke(main, ["cache", "--ttl", "5"])

    assert "cold" in result.stdout, result.output
    assert "WARM" not in result.stdout
    assert "ttl 5m" in result.stdout


def test_verdict_ttl_reports_the_age_in_minutes(tmp_path: Path, monkeypatch):
    """The reported age is the one set on the transcript's mtime."""
    repo = _git_repo(tmp_path / "repo")
    projects = tmp_path / "projects"
    _transcript(_session_dir(projects, repo), "s.jsonl", minutes=42)
    monkeypatch.setenv(cache_mod.PROJECTS_DIR_ENV, str(projects))
    monkeypatch.chdir(repo)

    result = CliRunner().invoke(main, ["cache"])

    assert "42m ago" in result.stdout, result.output
    assert "s" in result.stdout  # the session id


def test_verdict_ttl_exactly_at_the_threshold_is_cold(tmp_path: Path, monkeypatch):
    """Warm is strictly *under* the TTL — at the threshold the cache is gone."""
    repo = _git_repo(tmp_path / "repo")
    projects = tmp_path / "projects"
    _transcript(_session_dir(projects, repo), "s.jsonl", minutes=60)
    monkeypatch.setenv(cache_mod.PROJECTS_DIR_ENV, str(projects))
    monkeypatch.chdir(repo)

    result = CliRunner().invoke(main, ["cache"])

    assert "cold" in result.stdout, result.output
    assert "WARM" not in result.stdout


def test_verdict_ttl_caveat_is_printed_under_both_verdicts(warm_project):
    """Decision 3: the age-based check cannot see invalidation, so it always says so."""
    warm = CliRunner().invoke(main, ["cache"])
    cold = CliRunner().invoke(main, ["cache", "--ttl", "5"])

    assert "WARM" in warm.stdout and "cold" in cold.stdout
    for result in (warm, cold):
        assert cache_mod.INVALIDATION_CAVEAT in result.output, result.output


# -- AC3: exit codes + read-only ----------------------------------------------


def test_exit_readonly_codes_carry_the_verdict(warm_project):
    """0 = warm, 1 = cold — the verdict is scriptable without parsing the line."""
    assert CliRunner().invoke(main, ["cache"]).exit_code == 0
    assert CliRunner().invoke(main, ["cache", "--ttl", "5"]).exit_code == 1


def test_exit_readonly_no_transcript_exits_two_naming_the_directory(tmp_path, monkeypatch):
    """Exit 2 (not 1 — that means cold) and the searched dir is named, so a wrong slug is
    visible rather than a silent wrong verdict."""
    repo = _git_repo(tmp_path / "repo")
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setenv(cache_mod.PROJECTS_DIR_ENV, str(projects))
    monkeypatch.chdir(repo)

    result = CliRunner().invoke(main, ["cache"])

    assert result.exit_code == 2, result.output
    assert str(_session_dir(projects, repo)) in result.stderr
    assert not result.stdout.strip()  # no verdict line to misread


def test_exit_readonly_invocation_writes_nothing(warm_project):
    """The verb stats and never writes: the projects tree (contents *and* mtimes) and the
    invoking repo's worktree + .devsteward/ are byte-identical across the call."""
    repo, projects, _, _ = warm_project
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    ledger = repo / ".devsteward"
    ledger.mkdir()
    (ledger / "state.yaml").write_text("cursor:\n  step: REQ-082:develop\n", encoding="utf-8")

    before_projects, before_repo = _snapshot(projects), _snapshot(repo)
    before_git = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True
    ).stdout

    assert CliRunner().invoke(main, ["cache"]).exit_code == 0

    assert _snapshot(projects) == before_projects
    assert _snapshot(repo) == before_repo
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True
        ).stdout
        == before_git
    )
