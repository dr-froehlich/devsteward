#!/usr/bin/env python3
"""Parse a legacy **prose-header** REQ corpus into the DevSteward hybrid schema (REQ-017).

Where :mod:`convert_reqs` normalizes a project that already carries YAML frontmatter (memzy's
dialect), this front-end handles the older shape that has none — a ``### REQ-NNN: Title``
header followed by a flat list of ``- **Field:**`` bullets, as used by **THermo** and
**ExamEngineer**::

    ### REQ-004: WhoAmI device identity

    - **Status:** DONE
    - **Added:** 2026-04-07
    - **Completed:** 2026-04-07
    - **Verified by:** idf.py build clean 2026-04-07
    - **Depends on:** –
    - **Description:**
      …
    - **Acceptance criteria:**
      - [x] …
    - **Notes:**
      …

This module owns the **parse** step and nothing else (REQ-017 Decision 3): once the headers
are frontmatter, every downstream rule — ``kind`` inference, the acceptance transcode,
``supersedes`` normalization, the index splice — is :mod:`convert_reqs`'s, imported and
reused, never duplicated. That keeps the memzy converter, which has already run on a live
corpus, byte-untouched.

Two properties matter as much as the parse:

* **Transactional** (Decision 6) — every file is parsed into memory *first*; if any one
  fails, the run raises and writes **nothing**. There is no half-converted corpus whose
  index disagrees with its files, and so no window in which ``steward lint`` is red.
* **Confidently parse or report** — the status vocabulary is a fixed table and an
  unrecognized token is an abort, never a guess. A REQ silently imported under a status
  nobody chose is the failure this forbids.
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

# Allow running as a standalone script from a devsteward checkout without installing it
# (Python puts scripts/ on sys.path[0], not the repo root, when invoked as a file).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convert_reqs import (  # noqa: E402  — the shared core (REQ-010); nothing is reimplemented
    _convert_acceptance,
    build_index,
    dump_frontmatter,
    normalize_frontmatter,
    parse_acceptance_checkboxes,
    splice_index,
)
from devsteward.profiles.req.index import read_statuses  # noqa: E402
from devsteward.profiles.req.reqfile import parse_req  # noqa: E402

# ``### REQ-NNN: Title`` — the id may carry a REQ-021 lettered suffix.
_HEADER_RE = re.compile(r"^###[ \t]+(REQ-\d{3}[a-z]?)[ \t]*:[ \t]*(.+?)[ \t]*$", re.MULTILINE)
# A top-level bold bullet. Whether it is a *field* is decided by its name, not its shape —
# the Description body carries look-alikes (``- **MAC address**: Replace …``).
_BULLET_RE = re.compile(r"^-[ \t]+\*\*(.+?)\*\*:?[ \t]*(.*)$")
_REQ_ID_RE = re.compile(r"REQ-\d{3}[a-z]?")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The eight field names the dialect uses, normalized (lowercased, ':' stripped, ' ' → '_').
_SCALAR_FIELDS = ("status", "added", "completed", "verified_by", "depends_on")
_BLOCK_FIELDS = ("description", "acceptance_criteria", "notes")
KNOWN_FIELDS = frozenset(_SCALAR_FIELDS + _BLOCK_FIELDS)

# Fields whose value must sit inline on the bullet; trailing prose means the file is not the
# dialect we think it is, so we report rather than silently join it into a scalar.
_INLINE_ONLY = frozenset({"status", "added", "completed", "depends_on"})

# A bare placeholder standing for "nothing here" — matched on the *whole* stripped value, so
# THermo's ``– (code-only smoke tests pass; …)`` is kept as real text rather than dropped.
_PLACEHOLDERS = frozenset({"", "-", "–", "—", "n/a", "none", "–", "tbd"})

# Decision 7: a fixed table. The keys are the source token upper-cased with separators
# normalized, so ``in progress`` / ``in-progress`` / ``IN_PROGRESS`` all land on one entry.
_STATUS_MAP = {
    "DRAFT": "draft",
    "OPEN": "open",
    "IN_PROGRESS": "in-progress",
    "BLOCKED": "blocked",
    "DONE": "done",
    "DROPPED": "dropped",
    "SUPERSEDED": "superseded",
}


# Statuses the engine considers active — the ones lint rule 5 holds to a runnable test id.
_ACTIVE = frozenset({"open", "in-progress", "blocked"})


class ProseParseError(Exception):
    """A file could not be confidently parsed. Carries the file name and the reason."""

    def __init__(self, name: str, reason: str):
        self.name, self.reason = name, reason
        super().__init__(f"{name}: {reason}")


@dataclass
class ConversionReport:
    """What one corpus conversion produced, plus everything the operator must be told."""

    reqs: list = field(default_factory=list)
    #: ``(id, index_title, header_title)`` — the header won, but you should look.
    title_conflicts: list[tuple[str, str, str]] = field(default_factory=list)
    #: ``(id, source_status)`` — imported as ``draft`` because nothing there is runnable.
    demotions: list[tuple[str, str]] = field(default_factory=list)


# --------------------------------------------------------------------------------- parsing


def _normalize_field_name(bold: str) -> str:
    return bold.strip().rstrip(":").strip().lower().replace(" ", "_")


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in _PLACEHOLDERS


def split_fields(text: str, *, name: str = "<text>") -> tuple[str, str, dict[str, str]]:
    """Split one prose REQ into ``(id, title, {field: segment})``.

    Segmentation happens **only** at a top-level bullet whose normalized bold text is one of
    :data:`KNOWN_FIELDS`; every other line — including the Description's own bold bullets —
    belongs to the segment it sits in and is preserved verbatim.
    """
    header = _HEADER_RE.search(text)
    if header is None:
        raise ProseParseError(name, "no '### REQ-NNN: Title' header found")
    rid, title = header.group(1), header.group(2).strip()

    segments: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text[header.end():].splitlines():
        bullet = _BULLET_RE.match(line)
        field = _normalize_field_name(bullet.group(1)) if bullet else None
        if field in KNOWN_FIELDS:
            if field in segments:
                raise ProseParseError(name, f"duplicate '{field}' field bullet")
            current = segments.setdefault(field, [])
            rest = bullet.group(2).strip()
            if rest:
                current.append(rest)
        elif current is None:
            if line.strip():
                raise ProseParseError(
                    name, f"content before the first field bullet: {line.strip()[:60]!r}"
                )
        else:
            current.append(line)

    if "status" not in segments:
        raise ProseParseError(name, "no '- **Status:**' field bullet found")
    for field in _INLINE_ONLY & segments.keys():
        if len([ln for ln in segments[field][1:] if ln.strip()]) > 0:
            raise ProseParseError(name, f"'{field}' carries prose beyond its bullet line")

    return rid, title, {k: "\n".join(v) for k, v in segments.items()}


def coerce_status(token: str, *, name: str) -> str:
    """Map a dialect status token onto the engine's vocabulary; abort on anything else."""
    key = token.strip().upper().replace("-", "_").replace(" ", "_")
    if key not in _STATUS_MAP:
        raise ProseParseError(name, f"unrecognized status token {token.strip()!r}")
    return _STATUS_MAP[key]


def coerce_date(value: str, *, field: str, name: str) -> str | None:
    if _is_placeholder(value):
        return None
    text = value.strip()
    if not _DATE_RE.match(text):
        raise ProseParseError(name, f"'{field}' is not a YYYY-MM-DD date: {text[:40]!r}")
    return text


def coerce_text(value: str) -> str | None:
    return None if _is_placeholder(value) else " ".join(value.split())


def coerce_deps(value: str, *, name: str) -> list[str]:
    if _is_placeholder(value):
        return []
    ids = _REQ_ID_RE.findall(value)
    if not ids:
        raise ProseParseError(name, f"'depends_on' names no REQ ids: {value.strip()[:40]!r}")
    return ids


def _block(segments: dict[str, str], field: str) -> str:
    return textwrap.dedent(segments.get(field, "")).strip("\n")


def build_body(rid: str, title: str, segments: dict[str, str]) -> str:
    """Restructure the parsed segments into ``##`` sections (Decision 4).

    The ``### REQ-NNN: Title`` header is **preserved** — the source is never silently
    shortened — and the acceptance checkboxes are emitted under a literal
    ``## Acceptance criteria`` heading so the core's transcoder anchors on them. No
    ``## Context`` / ``## Decisions`` is written: the dialect has no field that maps to
    either, and the converter does not invent sections it has no source for.
    """
    parts = [f"### {rid}: {title}"]
    for heading, field in (
        ("Requirement", "description"),
        ("Acceptance criteria", "acceptance_criteria"),
        ("Notes", "notes"),
    ):
        body = _block(segments, field)
        if body:
            parts.append(f"## {heading}\n\n{body}")
    return "\n\n".join(parts) + "\n"


def demote_unrunnable_active(status: str, acceptance_segment: str) -> str:
    """An **active** import with nothing runnable in it comes in as ``draft`` (Decision 10).

    ``steward lint`` rule 5 holds an active REQ (``open``/``in-progress``/``blocked``) to a
    test id and a ``check:`` on every criterion, so the engine never lands one blind. A prose
    corpus has neither — its criteria are checkboxes — so importing unfinished work under its
    source status would hand the project a permanently red lint it cannot honestly fix: the
    converter may not invent a test id (REQ-010 Decision 3) and may not re-adjudicate a
    verdict (Decision 2).

    ``draft`` is the honest landing spot. It is exempt from rule 5, produces no engine steps,
    and says exactly what is true — the work is not yet engine-ready. **No verdict is
    touched**: every criterion keeps its imported ``passed``/``pending``. The operator runs
    ``steward activate`` once real criteria are authored, and rule 5 fires again — precisely
    when a runnable test is needed. Terminal statuses are never demoted; they have nothing
    left to land.
    """
    if status not in _ACTIVE:
        return status
    criteria = parse_acceptance_checkboxes(acceptance_segment)
    return status if any(c["test"].strip() for c in criteria) else "draft"


def convert_prose_text(text: str, *, name: str = "<text>") -> str:
    """Convert one prose REQ file's text into the hybrid schema.

    Input that already carries frontmatter is returned **unchanged**, which is what makes a
    second run over converted output a true no-op (and keeps this front-end from fighting
    :mod:`convert_reqs` over a mixed corpus).
    """
    if text.lstrip().startswith("---"):
        return text

    rid, title, segments = split_fields(text, name=name)
    frontmatter = {
        "id": rid,
        "title": title,
        "status": demote_unrunnable_active(
            coerce_status(segments["status"], name=name),
            segments.get("acceptance_criteria", ""),
        ),
        "added": coerce_date(segments.get("added", ""), field="added", name=name),
        "completed": coerce_date(segments.get("completed", ""), field="completed", name=name),
        "verified_by": coerce_text(segments.get("verified_by", "")),
        "depends_on": coerce_deps(segments.get("depends_on", ""), name=name),
        "supersedes": None,
        "tags": [],
    }
    fm_out = dump_frontmatter(normalize_frontmatter(frontmatter))
    body_out = _convert_acceptance(build_body(rid, title, segments))
    return f"---\n{fm_out}\n---\n\n{body_out}"


# ---------------------------------------------------------------------------------- corpus


def _title_conflicts(index_path: Path, titles: dict[str, str]) -> list[tuple[str, str, str]]:
    """``(id, index_title, header_title)`` for every REQ whose two titles disagree.

    The header wins (Decision 5) — the REQ file is primary and the index is its generated
    mirror — but the conflict is *reported* so the operator can rescue a case where the index
    genuinely had the better wording.
    """
    if not index_path.exists():
        return []
    conflicts = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] in titles and cells[1] != titles[cells[0]]:
            conflicts.append((cells[0], cells[1], titles[cells[0]]))
    return conflicts


def convert_corpus_prose(src_dir: Path, dst_dir: Path) -> ConversionReport:
    """Convert every prose ``REQ-*.md`` in ``src_dir`` into ``dst_dir`` and write the index.

    Transactional (Decision 6): the whole corpus is parsed before anything is written, and a
    single :class:`ProseParseError` aborts the run with every file left byte-unchanged.
    """
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)

    converted: dict[str, str] = {}
    demotions: list[tuple[str, str]] = []
    problems: list[ProseParseError] = []
    for path in sorted(src_dir.glob("REQ-*.md")):
        if path.stem == "REQ-xxx" or path.name.endswith(".tmpl"):
            continue  # a template stub, not a REQ — the reqfile.load_reqs rule
        raw = path.read_text(encoding="utf-8")
        try:
            converted[path.name] = convert_prose_text(raw, name=path.name)
        except ProseParseError as exc:
            problems.append(exc)
            continue
        if not raw.lstrip().startswith("---"):
            rid, _, segments = split_fields(raw, name=path.name)
            source = coerce_status(segments["status"], name=path.name)
            if demote_unrunnable_active(source, segments.get("acceptance_criteria", "")) != source:
                demotions.append((rid, source))
    if problems:
        raise ProseParseError(
            f"{len(problems)} file(s)",
            "corpus not converted, nothing written:\n  "
            + "\n  ".join(str(p) for p in problems),
        )

    dst_dir.mkdir(parents=True, exist_ok=True)
    reqs = []
    for filename, text in converted.items():
        dest = dst_dir / filename
        dest.write_text(text, encoding="utf-8")
        reqs.append(parse_req(dest))

    index_path = dst_dir / "REQUIREMENTS_INDEX.md"
    conflicts = _title_conflicts(index_path, {r.id: r.title for r in reqs})
    index_path.write_text(
        splice_index(index_path.read_text(encoding="utf-8"), reqs)
        if index_path.exists()
        else build_index(reqs),
        encoding="utf-8",
    )
    return ConversionReport(reqs=reqs, title_conflicts=conflicts, demotions=demotions)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("src", type=Path, help="source requirements dir (prose dialect)")
    parser.add_argument("dst", type=Path, help="destination dir for the converted corpus")
    args = parser.parse_args(argv)
    try:
        report = convert_corpus_prose(args.src, args.dst)
    except ProseParseError as exc:
        print(f"aborted — {exc}", file=sys.stderr)
        return 1
    print(f"converted {len(report.reqs)} REQ(s) → {args.dst}")
    for rid, index_title, header_title in report.title_conflicts:
        print(
            f"  title conflict {rid}: index {index_title!r} -> header {header_title!r} (header wins)"
        )
    for rid, source in report.demotions:
        print(
            f"  {rid}: imported as draft (source {source!r}) — no runnable criteria; "
            f"`steward activate {rid}` once real acceptance criteria are authored"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
