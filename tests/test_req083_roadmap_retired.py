"""REQ-083 AC1 — the roadmap artifact is retired from the shipped package.

The roadmap was a standing file nothing read: no engine verb ever opened it, so nothing
guarded it and it drifted into an unreadable intake chronicle. It is deleted, not
deprecated — which means the honest regression is a sweep over what we *ship*: a
reference reintroduced by a template edit is exactly how the artifact would creep back.

The sweep is scoped to ``devsteward/`` (code + templates). Converter test fixtures under
``tests/fixtures/`` legitimately mention ROADMAP — they are foreign input corpus, a
target project's own living docs, not our doctrine (REQ-083 decision 3) — and are out of
scope by construction, since the sweep never leaves the package tree.
"""

from __future__ import annotations

from pathlib import Path

import devsteward

PACKAGE = Path(devsteward.__file__).parent
TEMPLATES = PACKAGE / "templates"

# Binary/compiled artifacts carry no doctrine and are not source we edit.
_SKIP_DIRS = {"__pycache__", ".git"}
_SKIP_SUFFIXES = {".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico"}


def _package_files() -> list[Path]:
    return [
        p
        for p in PACKAGE.rglob("*")
        if p.is_file()
        and p.suffix.lower() not in _SKIP_SUFFIXES
        and not _SKIP_DIRS & set(p.relative_to(PACKAGE).parts)
    ]


def test_no_roadmap_reference_anywhere_in_the_package():
    """No file we ship names the roadmap — case-insensitive, templates included."""
    hits: list[str] = []
    for path in _package_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "roadmap" in line.lower():
                rel = path.relative_to(PACKAGE)
                hits.append(f"devsteward/{rel}:{lineno}: {line.strip()}")

    assert not hits, "roadmap references crept back into the package:\n" + "\n".join(hits)


def test_templates_ship_no_roadmap_file():
    """A `steward new` project never receives a ROADMAP.md."""
    assert not list(TEMPLATES.rglob("ROADMAP.md"))
    assert not list(TEMPLATES.rglob("ROADMAP.md.tmpl"))


def test_stamped_intake_emits_req_and_index_only():
    """Intake's emit is the REQ + its index row — the roadmap step is gone, and the
    index ↔ frontmatter pair it commits with is still named."""
    md = (TEMPLATES / ".claude" / "skills" / "intake" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    low = md.lower()

    assert "roadmap" not in low
    assert "REQUIREMENTS_INDEX.md" in md
    assert "one commit" in low and "frontmatter + index" in low
