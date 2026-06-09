"""The canonical ``REQUIREMENTS_INDEX.md`` row contract — read and surgical write.

The index is a Markdown table whose first columns are ``| ID | Title | Status | … |``.
Status is displayed UPPERCASE (``DRAFT``/``OPEN``/``DONE``); the engine reads it
lowercased (to compare against a REQ's frontmatter ``status:``) and writes it uppercased.

This module owns the row regex so the contract lives in one place: the linter
(:mod:`devsteward.lint`) reads statuses through here, and ``steward activate``
(:mod:`devsteward.lifecycle`) flips a single row's status cell in lockstep with the REQ
frontmatter, keeping the index↔REQ same-commit invariant green (REQ-002, REQ-026 D1).
"""

from __future__ import annotations

import re
from pathlib import Path

# id | title | status | …  — status is a bare word (UPPERCASE in the file). The capture
# groups are: 1=id, 2=title, 3=status cell.
INDEX_ROW_RE = re.compile(
    r"^(\|\s*(REQ-\d{3}[a-z]?)\s*\|\s*(.*?)\s*\|\s*)([A-Za-z-]+)(\s*\|)", re.MULTILINE
)


def read_statuses(index_path: Path) -> dict[str, str]:
    """Map REQ id → status (lowercased) from the index table."""
    if not index_path.exists():
        return {}
    text = Path(index_path).read_text(encoding="utf-8")
    return {m.group(2): m.group(4).strip().lower() for m in INDEX_ROW_RE.finditer(text)}


def set_status(index_path: Path, req_id: str, status: str) -> str:
    """Rewrite ``req_id``'s status cell to ``status`` (UPPERCASE). Returns the old status
    (lowercased). Edits only that one cell so the rest of the table is preserved.

    Raises ``KeyError`` if the id has no row in the index.
    """
    path = Path(index_path)
    text = path.read_text(encoding="utf-8")
    old: list[str] = []

    def repl(m: re.Match) -> str:
        if m.group(2) != req_id:
            return m.group(0)
        old.append(m.group(4).strip().lower())
        return f"{m.group(1)}{status.upper()}{m.group(5)}"

    new_text = INDEX_ROW_RE.sub(repl, text)
    if not old:
        raise KeyError(f"{req_id} has no row in {path}")
    path.write_text(new_text, encoding="utf-8")
    return old[0]
