"""Which projects live beside this one — the one discovery every cross-project reader shares.

The dashboard (REQ-097 Decision 7) and the joint-task verbs (REQ-101 Decision 3) both need to
know the owner's other projects without being told where they are. The answer is a directory
scan of the enclosing project's parent: every child holding a ``.devsteward/`` ledger is a
stamped project, the rest are listed for information. It lives here, outside the optional
``dashboard`` package, so a core verb can use it without the extra — and it lives *once*, so
the two readers can never disagree about what a project is.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import ProjectNotFound, find_root
from .core.ledger import LEDGER_DIRNAME


@dataclass(frozen=True)
class ProjectRef:
    """A child folder of the root: stamped (holds a ledger) or listed for information."""

    name: str
    root: Path
    stamped: bool


def resolve_root(explicit: Path | None = None) -> Path:
    """The directory whose children are the projects.

    ``--root`` when given; else the **parent of the enclosing project** (the walk-up the
    other verbs use), so running from inside any stamped project finds its siblings; else
    the current directory. Never a hardcoded path.
    """
    if explicit is not None:
        return Path(explicit).resolve()
    try:
        return find_root().parent
    except ProjectNotFound:
        return Path.cwd().resolve()


def scan_root(root: Path) -> list[ProjectRef]:
    """Every child directory of ``root``: stamped when it holds a ``.devsteward/`` ledger."""
    root = Path(root)
    out: list[ProjectRef] = []
    if not root.is_dir():
        return out
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        out.append(ProjectRef(child.name, child, (child / LEDGER_DIRNAME).is_dir()))
    return out
