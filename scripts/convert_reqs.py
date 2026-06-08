#!/usr/bin/env python3
"""Normalize memzy's frontmatter REQ dialect into the DevSteward hybrid schema.

memzy already carries YAML frontmatter on every REQ — it crossed the frontmatter
threshold on its own — so this is a **dialect normalizer**, not a prose parser. It closes
the named gaps ``steward lint`` reports against memzy's corpus (REQ-010):

* ``kind`` — absent on every memzy REQ; injected (north star → ``spec``, else a light
  heuristic, default ``feature``).
* Acceptance — the ``## Acceptance criteria`` ``- [x]``/``- [ ]`` checkbox list becomes a
  single fenced ``yaml acceptance`` block the REQ profile's parser can read, **preserving
  each verdict** (``[x]`` → ``passed``, ``[ ]`` → ``pending``) and the text verbatim.
* ``supersedes`` — ``[]`` → ``null``; ``[REQ-NNN]`` → the string ``"REQ-NNN"``; the
  non-schema ``superseded_by`` key is dropped.
* Index — rewritten so every row matches the linter's ``_INDEX_ROW_RE`` with status in
  sync with its REQ.

The converter is an **archivist, not a judge** (REQ-010 Decision 2): it records memzy's own
verdict and never re-adjudicates it. A runnable ``test:`` is **best-effort** (Decision 3):
an embedded ``test_*`` name is copied when present, left empty otherwise — the verdict does
not depend on it. The conversion is **idempotent and non-destructive** (Decision 7): the
prose sections are spliced through byte-for-byte and a second run is a no-op.

The core functions live here in ``scripts/`` (Decision 6), not in the installable
``devsteward`` package — this is a run-once, memzy-specific migration tool, not public API.
The acceptance tests import them via the ``sys.path`` shim in ``tests/conftest.py``.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import io
import re
import sys
from pathlib import Path

from ruamel.yaml import YAML

# Allow running as a standalone script from a devsteward checkout without installing it
# (Python puts scripts/ on sys.path[0], not the repo root, when invoked as a file).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from devsteward.profiles.req.reqfile import ReqFile, parse_req  # noqa: E402

_yaml = YAML()
_yaml.preserve_quotes = False

# Frontmatter / acceptance locating patterns (mirrors reqfile's leniency).
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
_CHECKBOX_RE = re.compile(r"^\s*-\s\[([ xX])\]\s?(.*)$")
_HEADING_RE = re.compile(r"^##[ \t]", re.MULTILINE)
_ACCEPTANCE_HEADING_RE = re.compile(r"^##[ \t]+Acceptance criteria[^\n]*$", re.MULTILINE)
# First embedded test_* identifier in a criterion (in backticks or bare) — best effort.
_TEST_RE = re.compile(r"test_[A-Za-z0-9_]+")

# Canonical frontmatter field order (matches the schema + DevSteward's own REQ files).
_FIELD_ORDER = [
    "id", "title", "status", "kind", "added", "completed", "verified_by",
    "depends_on", "concept_refs", "scenario_refs", "supersedes", "tags",
]
# Values for these keys are always emitted double-quoted (they carry prose/punctuation).
_QUOTED_KEYS = {"title", "verified_by"}
# A scalar safe to emit as a bare YAML token (no quoting needed).
_SAFE_BARE_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


# --------------------------------------------------------------------------- frontmatter


def infer_kind(frontmatter: dict) -> str:
    """Pick a schema-valid ``kind`` for a memzy REQ that has none.

    The north star (REQ-001 / a ``north-star`` tag) is a ``spec``; a light tag/title
    heuristic catches the obvious refactor/fix/docs/chore cases; everything else defaults
    to ``feature``. Best-effort by design — a human can correct it after import.
    """
    existing = frontmatter.get("kind")
    if existing:
        return str(existing)
    if frontmatter.get("id") == "REQ-001":
        return "spec"
    hay = " ".join(
        [str(frontmatter.get("title", "")), " ".join(frontmatter.get("tags") or [])]
    ).lower()
    if "north-star" in hay or "north star" in hay:
        return "spec"
    for needle, kind in (
        ("refactor", "refactor"), ("docs", "docs"),
        ("bugfix", "fix"), ("hotfix", "fix"), ("chore", "chore"),
    ):
        if needle in hay:
            return kind
    return "feature"


def normalize_supersedes(value) -> str | None:
    """``[]`` → ``None``; ``[REQ-NNN]`` → ``"REQ-NNN"``; a string is kept; else ``None``."""
    if value is None:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    text = str(value).strip()
    return text or None


def _iso(value):
    """Coerce a YAML-typed ``date``/``datetime`` back to a ``YYYY-MM-DD`` string."""
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()[:10]
    return value


def _dq(value) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _scalar(key: str, value) -> str:
    value = _iso(value)
    if value is None:
        return "null"
    if key in _QUOTED_KEYS:
        return _dq(value)
    text = str(value)
    return text if _SAFE_BARE_RE.match(text) else _dq(text)


def _item(value) -> str:
    value = _iso(value)
    text = str(value)
    return text if _SAFE_BARE_RE.match(text) else _dq(text)


def _render(key: str, value) -> str:
    if isinstance(value, list):
        return "[]" if not value else "[" + ", ".join(_item(x) for x in value) + "]"
    return _scalar(key, value)


def normalize_frontmatter(frontmatter: dict) -> dict:
    """Return a new frontmatter dict in canonical form: ``kind`` injected, ``supersedes``
    normalized, ``superseded_by`` dropped, every other field carried unchanged."""
    fm = dict(frontmatter)
    fm.pop("superseded_by", None)
    fm["kind"] = infer_kind(fm)
    fm["supersedes"] = normalize_supersedes(fm.get("supersedes"))
    fm.setdefault("completed", None)
    fm.setdefault("verified_by", None)
    fm.setdefault("concept_refs", [])
    fm.setdefault("scenario_refs", [])
    fm.setdefault("tags", [])
    return fm


def dump_frontmatter(frontmatter: dict) -> str:
    """Serialize a (already-normalized) frontmatter dict as a stable YAML block.

    Deterministic field order + fixed quoting make this a fixed point: re-dumping a
    parsed dump yields identical bytes, which is what makes the converter idempotent.
    """
    lines: list[str] = []
    for key in _FIELD_ORDER:
        if key in frontmatter:
            lines.append(f"{key}: {_render(key, frontmatter[key])}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- acceptance


def parse_acceptance_checkboxes(section: str) -> list[dict]:
    """Parse a ``## Acceptance criteria`` checkbox list into criteria dicts.

    Each returned dict has ``text`` (continuation lines joined, whitespace collapsed,
    verbatim otherwise), ``status`` (``passed`` for ``[x]``, ``pending`` for ``[ ]``), and
    ``test`` (the first embedded ``test_*`` name, or ``""``). Non-list prose between groups
    (e.g. a "Pilot success definition" intro) flushes the current item and is ignored.
    """
    items: list[dict] = []
    parts: list[str] = []
    status: str | None = None

    def flush():
        nonlocal parts, status
        if status is not None:
            text = re.sub(r"\s+", " ", " ".join(parts)).strip()
            test = _TEST_RE.search(text)
            items.append(
                {"text": text, "status": status, "test": test.group(0) if test else ""}
            )
        parts, status = [], None

    for line in section.splitlines():
        m = _CHECKBOX_RE.match(line)
        if m:
            flush()
            status = "passed" if m.group(1).lower() == "x" else "pending"
            parts = [m.group(2).rstrip()]
        elif status is not None and line.strip() and line[:1] in " \t":
            parts.append(line.strip())  # continuation of the current criterion
        else:
            flush()  # blank line or non-indented prose ends the current criterion
    flush()
    return items


def transcode_acceptance_block(criteria: list[dict]) -> str:
    """Render parsed criteria as a fenced ``yaml acceptance`` block with AC1..ACn ids."""
    lines = ["```yaml acceptance"]
    for i, crit in enumerate(criteria, start=1):
        lines.append(f"- id: AC{i}")
        lines.append(f"  text: {_dq(crit['text'])}")
        lines.append(f"  test: {_dq(crit['test'])}")
        lines.append(f"  status: {crit['status']}")
    lines.append("```")
    return "\n".join(lines)


def _convert_acceptance(body: str) -> str:
    """Replace the ``## Acceptance criteria`` checkbox list with a ``yaml acceptance`` block.

    Only the acceptance section is rewritten; every other byte of the body is preserved.
    If the section holds no checkboxes (already converted, or absent), the body is returned
    untouched — that is what makes a second run a no-op.
    """
    m = _ACCEPTANCE_HEADING_RE.search(body)
    if not m:
        return body
    start = m.start()
    nxt = _HEADING_RE.search(body[m.end():])
    end = m.end() + nxt.start() if nxt else len(body)
    section = body[start:end]
    if "- [x]" not in section and "- [X]" not in section and "- [ ]" not in section:
        return body
    criteria = parse_acceptance_checkboxes(section)
    block = transcode_acceptance_block(criteria)
    rebuilt = "## Acceptance criteria\n\n" + block + ("\n\n" if nxt else "\n")
    return body[:start] + rebuilt + body[end:]


# --------------------------------------------------------------------------- file / corpus


def convert_req_text(text: str) -> str:
    """Convert one REQ file's text. Idempotent: ``convert(convert(x)) == convert(x)``."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("missing YAML frontmatter (expected a leading '---' block)")
    frontmatter = _yaml.load(io.StringIO(m.group(1))) or {}
    fm_out = dump_frontmatter(normalize_frontmatter(dict(frontmatter)))
    body_out = _convert_acceptance(m.group(2))
    return f"---\n{fm_out}\n---\n{body_out}"


def build_index(reqs: list[ReqFile]) -> str:
    """Emit a ``REQUIREMENTS_INDEX.md`` whose rows ``lint._index_rows`` matches, each in
    sync with its REQ's frontmatter status."""
    lines = [
        "# Requirements Index", "",
        "| ID | Title | Status | File | Depends on |",
        "|----|-------|--------|------|------------|",
    ]
    for r in sorted(reqs, key=lambda r: r.id):
        deps = ", ".join(r.depends_on) or "–"
        lines.append(f"| {r.id} | {r.title} | {r.status} | [{r.id}]({r.id}.md) | {deps} |")
    return "\n".join(lines) + "\n"


def convert_corpus(src_dir: Path, dst_dir: Path) -> list[ReqFile]:
    """Convert every ``REQ-*.md`` in ``src_dir`` into ``dst_dir`` and rewrite the index."""
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    converted: list[ReqFile] = []
    for path in sorted(src_dir.glob("REQ-*.md")):
        dest = dst_dir / path.name
        dest.write_text(convert_req_text(path.read_text(encoding="utf-8")), encoding="utf-8")
        converted.append(parse_req(dest))
    (dst_dir / "REQUIREMENTS_INDEX.md").write_text(build_index(converted), encoding="utf-8")
    return converted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("src", type=Path, help="source docs/requirements/ (memzy dialect)")
    parser.add_argument("dst", type=Path, help="destination dir for the normalized copy")
    args = parser.parse_args(argv)
    reqs = convert_corpus(args.src, args.dst)
    print(f"converted {len(reqs)} REQ(s) → {args.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
