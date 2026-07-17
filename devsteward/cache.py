"""``steward cache`` — is this project's Claude session still prompt-cache warm? (REQ-082)

The prompt cache is a rolling-TTL prefix cache: a session stays warm while consecutive
requests are less than one TTL apart. There is no API to query that state, and asking
*inside* the session is self-defeating — the question is itself a request that re-warms (or
cold-pays) the cache. But Claude Code appends every session event to a transcript under
``$CLAUDE_PROJECTS_DIR/<slug>/<session>.jsonl``, so the newest transcript's mtime is a
faithful "last request" clock, readable from a second shell with zero session impact.

Everything here is read-only and ledger-free: it stats, never opens a transcript, never
writes, and never touches ``.devsteward/`` — so the verb also works outside a steward project.
The check is age-based only (Decision 3): a model switch or a compaction invalidates the
prefix regardless of age, which is why every rendering carries :data:`INVALIDATION_CAVEAT`.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

#: The operator's assumed TTL, in minutes — a threshold they own, not a probed value. The
#: undetectable overage→5-minute drop is handled by passing ``--ttl 5`` (Decision 2).
DEFAULT_TTL_MINUTES = 60

#: Env seam for the projects root (Decision 5) — lets the suite run against a temp tree.
PROJECTS_DIR_ENV = "CLAUDE_PROJECTS_DIR"

INVALIDATION_CAVEAT = (
    "age-based check only — a model switch or a compaction invalidates the cache "
    "regardless of age"
)


def projects_dir() -> Path:
    """The Claude Code projects root: ``$CLAUDE_PROJECTS_DIR`` or ``~/.claude/projects``."""
    raw = os.environ.get(PROJECTS_DIR_ENV)
    return Path(raw).expanduser() if raw else Path.home() / ".claude" / "projects"


def project_root(cwd: Path | None = None) -> Path:
    """The directory Claude Code slugs by: the git toplevel, else ``cwd`` (Decision 4).

    Claude Code slugs its launch directory, which is normally the repo root, while
    ``steward`` may be invoked from a subdirectory. Any git failure (not a repo, no git on
    PATH) falls back to the invoking directory rather than raising — the verdict, not the
    lookup, is this verb's job.
    """
    start = Path(cwd) if cwd else Path.cwd()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start), capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return start.resolve()
    return Path(out).resolve() if out else start.resolve()


def project_slug(root: Path) -> str:
    """Claude Code's project-directory name: the absolute path with ``/`` → ``-``."""
    return str(Path(root).resolve()).replace("/", "-")


def newest_transcript(session_dir: Path) -> Path | None:
    """The most recently written transcript directly in ``session_dir`` (Decision 1).

    Non-recursive and ``*.jsonl``-only: the project directory also holds unrelated files and
    subdirectories (e.g. ``memory/``), none of which clock a request.
    """
    transcripts = [p for p in session_dir.glob("*.jsonl") if p.is_file()]
    if not transcripts:
        return None
    return max(transcripts, key=lambda p: p.stat().st_mtime)


@dataclass(frozen=True)
class CacheReport:
    """What the filesystem says about this project's newest session."""

    session_dir: Path
    transcript: Path | None
    age_minutes: float | None
    ttl_minutes: int

    @property
    def found(self) -> bool:
        return self.transcript is not None

    @property
    def session_id(self) -> str | None:
        return self.transcript.stem if self.transcript else None

    @property
    def warm(self) -> bool:
        """Warm strictly *under* the TTL — at or past the threshold is cold."""
        return self.age_minutes is not None and self.age_minutes < self.ttl_minutes

    @property
    def exit_code(self) -> int:
        """The verdict as a scriptable code (Decision 6): 0 warm, 1 cold, 2 no transcript."""
        if not self.found:
            return 2
        return 0 if self.warm else 1


def probe(ttl_minutes: int = DEFAULT_TTL_MINUTES, cwd: Path | None = None) -> CacheReport:
    """Report the newest session's age for the project ``cwd`` belongs to."""
    session_dir = projects_dir() / project_slug(project_root(cwd))
    transcript = newest_transcript(session_dir) if session_dir.is_dir() else None
    age_minutes = None
    if transcript is not None:
        age_minutes = (time.time() - transcript.stat().st_mtime) / 60.0
    return CacheReport(
        session_dir=session_dir,
        transcript=transcript,
        age_minutes=age_minutes,
        ttl_minutes=ttl_minutes,
    )
