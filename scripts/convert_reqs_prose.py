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
    _CHECKBOX_RE,
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

# The field names the dialect uses, normalized (lowercased, ':' stripped, ' ' → '_'). Eight
# in REQ-017's census; ``implementation_plan`` is the ninth, added by REQ-085 Decision 6 — a
# *known* field rendered as body prose, so it can never be mistaken for a body bullet nor
# swallowed into whatever segment happens to be open (which is what actually aborted THermo's
# REQ-026/REQ-027: the unknown bullet landed inside ``depends_on``). No ``plan_refs:`` schema
# field is invented for it — DevSteward's plans gate finds ``<plans_dir>/REQ-NNN*.md`` by
# convention, so the pointer is already redundant to the engine.
_SCALAR_FIELDS = ("status", "added", "completed", "verified_by", "depends_on")
_PROSE_LINE_FIELDS = ("implementation_plan",)
_BLOCK_FIELDS = ("description", "acceptance_criteria", "notes")
KNOWN_FIELDS = frozenset(_SCALAR_FIELDS + _PROSE_LINE_FIELDS + _BLOCK_FIELDS)

# Fields whose value must sit inline on the bullet; trailing prose means the file is not the
# dialect we think it is, so we report rather than silently join it into a scalar.
_INLINE_ONLY = frozenset({"status", "added", "completed", "depends_on", "implementation_plan"})

# REQ-085 Decision 7 — the two *stated* encodings of a supersession. Both live on the
# superseded REQ and name the superseding one, so the extracted edge is inverted before it
# lands: REQ-011's banner says "superseded by REQ-026", which is ``supersedes: REQ-011`` on
# **REQ-026**. This is not the converter inferring a relation (Decision 2 forbids that) — the
# relation is written down, unambiguously, and the schema has a field for exactly it.
_BANNER_SUPERSEDED_RE = re.compile(r"SUPERSEDED\s+by\s+\[?(REQ-\d{3}[a-z]?)", re.IGNORECASE)
_SUPERSEDES_QUALIFIER_RE = re.compile(r"\(\s*supersedes\s+it\s*\)", re.IGNORECASE)

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
    #: ``(id, field)`` — a repeated field bullet, merged in source order (REQ-085 Decision 5).
    merges: list[tuple[str, str]] = field(default_factory=list)
    #: ``(id, raw_line)`` — a ``Depends on:`` that carried prose beyond a bare id list. The
    #: ids were extracted and the raw line preserved in the body; check the extraction.
    dep_carries: list[tuple[str, str]] = field(default_factory=list)
    #: ``(superseding_id, superseded_id, encoding)`` — every ``supersedes:`` edge extracted.
    supersedes: list[tuple[str, str, str]] = field(default_factory=list)
    #: ``(id, first_line)`` — prose found after the checkbox list and rehomed under Notes,
    #: which the acceptance transcode would otherwise have destroyed.
    acceptance_tails: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ParsedProse:
    """One prose REQ, parsed but not yet rendered.

    Rendering is separated from parsing because ``supersedes:`` is a **corpus** relation: the
    banner on REQ-011 determines the frontmatter of REQ-026. A per-file convert cannot know
    it, so :func:`convert_corpus_prose` parses everything first, resolves the edges, and only
    then renders (REQ-085 Decision 7).
    """

    rid: str
    title: str
    segments: dict[str, str]
    #: The verbatim blockquote banner between the header and the first field bullet, if any.
    banner: str = ""
    #: Field names that appeared more than once and were merged in source order.
    merges: list[str] = field(default_factory=list)
    #: The raw ``Depends on:`` value when it carried prose beyond a bare id list, else "".
    dep_carry: str = ""


# --------------------------------------------------------------------------------- parsing


def _normalize_field_name(bold: str) -> str:
    return bold.strip().rstrip(":").strip().lower().replace(" ", "_")


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in _PLACEHOLDERS


def parse_sections(text: str, *, name: str = "<text>") -> ParsedProse:
    """Split one prose REQ into its header, banner and field segments.

    Segmentation happens **only** at a top-level bullet whose normalized bold text is one of
    :data:`KNOWN_FIELDS`; every other line — including the Description's own bold bullets —
    belongs to the segment it sits in and is preserved verbatim.

    Two REQ-085 tolerances, each an *enumerated rule* rather than a shrug (Decision 3):

    * **A blockquote banner** may sit between the header and the first field bullet — THermo's
      superseded REQs open with ``> **SUPERSEDED by [REQ-026](…)** …``. It is body prose and
      rides through verbatim. Leading content that is **not** a blockquote still aborts
      exactly as before: the tolerance is for one recognized shape, not for stray content.
    * **A repeated field bullet merges** in source order rather than aborting (Decision 5).
      Two ``- **Notes:**`` bullets are two notes, not a malformed file — losing either would
      break the non-destructive guarantee and aborting would block a retrofit over a
      maintainer's ordinary editing habit. The merge is reported so nobody finds it by diff.
    """
    header = _HEADER_RE.search(text)
    if header is None:
        raise ProseParseError(name, "no '### REQ-NNN: Title' header found")
    rid, title = header.group(1), header.group(2).strip()

    segments: dict[str, list[str]] = {}
    merges: list[str] = []
    banner_lines: list[str] = []
    current: list[str] | None = None
    for line in text[header.end():].splitlines():
        bullet = _BULLET_RE.match(line)
        field = _normalize_field_name(bullet.group(1)) if bullet else None
        if field in KNOWN_FIELDS:
            if field in segments:
                merges.append(field)
                segments[field].append("")  # a blank line between the merged parts
            current = segments.setdefault(field, [])
            rest = bullet.group(2).strip()
            if rest:
                current.append(rest)
        elif current is None:
            if line.strip() and not line.lstrip().startswith(">"):
                raise ProseParseError(
                    name, f"content before the first field bullet: {line.strip()[:60]!r}"
                )
            if banner_lines or line.strip():
                banner_lines.append(line.rstrip())
        else:
            current.append(line)

    if "status" not in segments:
        raise ProseParseError(name, "no '- **Status:**' field bullet found")
    for field in (_INLINE_ONLY & segments.keys()) - set(merges):
        if len([ln for ln in segments[field][1:] if ln.strip()]) > 0:
            raise ProseParseError(name, f"'{field}' carries prose beyond its bullet line")

    return ParsedProse(
        rid=rid,
        title=title,
        segments={k: "\n".join(v) for k, v in segments.items()},
        banner="\n".join(banner_lines).strip("\n"),
        merges=sorted(set(merges)),
    )


def split_fields(text: str, *, name: str = "<text>") -> tuple[str, str, dict[str, str]]:
    """``(id, title, {field: segment})`` — :func:`parse_sections`' original three-value shape."""
    parsed = parse_sections(text, name=name)
    return parsed.rid, parsed.title, parsed.segments


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


def dependency_prose(value: str) -> str:
    """The raw ``Depends on:`` line when it carries more than a bare id list, else ``""``.

    ``depends_on`` stopped being a comma list: THermo has ``REQ-011 (supersedes it)`` and
    ``REQ-026; exercises REQ-016, REQ-019, …``. The ids are unambiguous and mechanically
    extractable, but the qualifiers are human judgement the converter may not adjudicate
    (REQ-017 Decision 2, archivist) — and dropping them silently is the real damage, because
    *every* ``REQ-NNN`` token in the line becomes a dependency whether or not the sentence
    meant it that way. So: extract the ids as before, and hand the raw line back for verbatim
    preservation in the body (REQ-085 Decision 4), so nothing is silently shortened and the
    operator can check the extraction against what was actually written.
    """
    text = value.strip()
    if not text or _is_placeholder(text):
        return ""
    residue = _REQ_ID_RE.sub("", text)
    return "" if not residue.strip(" \t,;") else text


def extract_supersedes(parsed: ParsedProse) -> list[tuple[str, str, str]]:
    """``(superseding_id, superseded_id, encoding)`` for every supersession *stated* here.

    The two encodings point in **opposite** directions, which is exactly the sort of thing a
    converter gets silently backwards, so both are normalized to one oriented edge here:

    * the banner sits on the **superseded** REQ and names its successor — REQ-011's
      ``> **SUPERSEDED by [REQ-026](…)**`` yields ``REQ-026 supersedes REQ-011``;
    * the ``(supersedes it)`` qualifier sits on the **superseding** REQ and annotates the id
      it follows — REQ-026's ``- **Depends on:** REQ-011 (supersedes it)`` yields the same
      edge from the other side.

    Neither is the converter *inferring* a relation (REQ-017 Decision 2 forbids that): it is
    written down, unambiguously, and the schema has a field for it. Populating it rescues
    information the conversion would otherwise destroy — ``build_index`` regenerates every
    row, so the index's ``SUPERSEDED (by REQ-026)`` annotation is dropped; with
    ``supersedes:`` set the fact survives in frontmatter, where the linter resolves it.
    """
    edges: list[tuple[str, str, str]] = []
    if m := _BANNER_SUPERSEDED_RE.search(parsed.banner):
        edges.append((m.group(1), parsed.rid, "banner"))
    deps = parsed.segments.get("depends_on", "")
    if q := _SUPERSEDES_QUALIFIER_RE.search(deps):
        before = _REQ_ID_RE.findall(deps[: q.start()])
        if before:
            edges.append((parsed.rid, before[-1], "depends-on qualifier"))
    return edges


def _block(segments: dict[str, str], field: str) -> str:
    return textwrap.dedent(segments.get(field, "")).strip("\n")


def split_acceptance_tail(segment: str) -> tuple[str, str]:
    """Split an acceptance segment into ``(checkbox list, trailing prose)``.

    The core's transcoder replaces everything from the ``## Acceptance criteria`` heading to
    the next heading with the generated ``yaml acceptance`` block, so **any** prose sitting
    after the last checkbox is destroyed. That was invisible in REQ-017's 12-REQ census and is
    real in the live corpus: THermo's REQ-025 closed with a
    ``- **Implementation (2026-08-02):**`` block and its numbered sub-points appended under
    its criteria, and converting it lost the lot — a straight violation of the
    non-destructive guarantee.

    The tail is therefore split off here and rehomed by :func:`build_body` under ``## Notes``,
    the dialect's own home for post-hoc commentary. Nothing is invented and nothing is lost;
    the relocation is reported so it is not discovered by diff.
    """
    lines = segment.splitlines()
    last = -1
    for i, line in enumerate(lines):
        if _CHECKBOX_RE.match(line):
            last = i
        elif last == i - 1 and line.strip() and line[:1] in " \t":
            last = i  # an indented continuation of the criterion directly above
    if last < 0:
        return segment, ""
    tail = "\n".join(lines[last + 1:]).strip("\n")
    return "\n".join(lines[: last + 1]), tail


def build_body(
    rid: str,
    title: str,
    segments: dict[str, str],
    *,
    banner: str = "",
    dep_carry: str = "",
) -> str:
    """Restructure the parsed segments into ``##`` sections (REQ-017 Decision 4).

    The ``### REQ-NNN: Title`` header is **preserved** — the source is never silently
    shortened — and the acceptance checkboxes are emitted under a literal
    ``## Acceptance criteria`` heading so the core's transcoder anchors on them. No
    ``## Context`` / ``## Decisions`` is written: the dialect has no field that maps to
    either, and the converter does not invent sections it has no source for.

    Three things ride between the header and the first section, each verbatim and each only
    when the source had it (REQ-085): the blockquote ``banner``, the raw ``Depends on:`` line
    when it carried prose the ids alone do not capture, and the ``Implementation plan:``
    pointer. All three are *prose* — none becomes a frontmatter key.
    """
    parts = [f"### {rid}: {title}"]
    if banner:
        parts.append(banner)
    if dep_carry:
        parts.append(f"**Depends on:** {dep_carry}")
    if plan := segments.get("implementation_plan", "").strip():
        parts.append(f"**Implementation plan:** {plan}")

    # Prose trailing the checkbox list would be eaten by the acceptance transcode, so it is
    # rehomed under Notes in source order (see :func:`split_acceptance_tail`).
    criteria, tail = split_acceptance_tail(_block(segments, "acceptance_criteria"))
    notes = _block(segments, "notes")
    if tail:
        notes = f"{notes}\n\n{tail}".strip("\n") if notes else tail

    for heading, body in (
        ("Requirement", _block(segments, "description")),
        ("Acceptance criteria", criteria),
        ("Notes", notes),
    ):
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


def render_prose_req(parsed: ParsedProse, *, name: str = "<text>", supersedes: str | None = None) -> str:
    """Render a :class:`ParsedProse` as hybrid-schema text.

    ``supersedes`` is supplied by the caller because it is a **corpus** relation resolved
    across files (:func:`extract_supersedes`), not something this REQ's own text states about
    itself in the schema's direction.
    """
    segments = parsed.segments
    frontmatter = {
        "id": parsed.rid,
        "title": parsed.title,
        "status": demote_unrunnable_active(
            coerce_status(segments["status"], name=name),
            segments.get("acceptance_criteria", ""),
        ),
        "added": coerce_date(segments.get("added", ""), field="added", name=name),
        "completed": coerce_date(segments.get("completed", ""), field="completed", name=name),
        "verified_by": coerce_text(segments.get("verified_by", "")),
        "depends_on": coerce_deps(segments.get("depends_on", ""), name=name),
        "supersedes": supersedes,
        "tags": [],
    }
    fm_out = dump_frontmatter(normalize_frontmatter(frontmatter))
    body_out = _convert_acceptance(
        build_body(
            parsed.rid,
            parsed.title,
            segments,
            banner=parsed.banner,
            dep_carry=parsed.dep_carry,
        )
    )
    return f"---\n{fm_out}\n---\n\n{body_out}"


def parse_prose_req(text: str, *, name: str = "<text>") -> ParsedProse:
    """Parse one prose REQ, including the REQ-085 carries the renderer needs."""
    parsed = parse_sections(text, name=name)
    parsed.dep_carry = dependency_prose(parsed.segments.get("depends_on", ""))
    return parsed


def convert_prose_text(
    text: str, *, name: str = "<text>", supersedes: str | None = None
) -> str:
    """Convert one prose REQ file's text into the hybrid schema.

    Input that already carries frontmatter is returned **unchanged**, which is what makes a
    second run over converted output a true no-op (and keeps this front-end from fighting
    :mod:`convert_reqs` over a mixed corpus).
    """
    if text.lstrip().startswith("---"):
        return text
    return render_prose_req(parse_prose_req(text, name=name), name=name, supersedes=supersedes)


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


def resolve_supersedes(
    edges: list[tuple[str, str, str]]
) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    """Fold oriented edges into ``{superseding_id: superseded_id}``, aborting on disagreement.

    Two rules, both REQ-085 Decision 7, both refusing to guess:

    * the two encodings must **agree** — a banner and a ``(supersedes it)`` qualifier naming
      different REQs is a contradiction in the source that only a human can settle;
    * one REQ may name only **one** superseded REQ, because ``supersedes:`` holds one string
      — silently keeping whichever came first is precisely the quiet data loss this rescues.
    """
    by_superseding: dict[str, dict[str, list[str]]] = {}
    for superseding, superseded, encoding in edges:
        by_superseding.setdefault(superseding, {}).setdefault(superseded, []).append(encoding)

    resolved: dict[str, str] = {}
    for superseding, found in sorted(by_superseding.items()):
        if len(found) > 1:
            detail = "; ".join(
                f"{sid} (from {', '.join(encs)})" for sid, encs in sorted(found.items())
            )
            raise ProseParseError(
                f"{superseding}.md",
                f"conflicting 'supersedes' extractions — {detail}. The schema holds one; "
                f"reconcile the source before converting",
            )
        resolved[superseding] = next(iter(found))
    return resolved, sorted(edges)


def convert_corpus_prose(src_dir: Path, dst_dir: Path) -> ConversionReport:
    """Convert every prose ``REQ-*.md`` in ``src_dir`` into ``dst_dir`` and write the index.

    Transactional (REQ-017 Decision 6): the whole corpus is parsed before anything is written,
    and a single :class:`ProseParseError` aborts the run with every file left byte-unchanged.

    The parse is **two-pass** since REQ-085: ``supersedes:`` is a relation *between* files
    (REQ-011's banner determines REQ-026's frontmatter), so every file is parsed, the edges
    are resolved corpus-wide, and only then is anything rendered.
    """
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)

    parsed: dict[str, ParsedProse] = {}
    passthrough: dict[str, str] = {}
    demotions: list[tuple[str, str]] = []
    merges: list[tuple[str, str]] = []
    dep_carries: list[tuple[str, str]] = []
    acceptance_tails: list[tuple[str, str]] = []
    edges: list[tuple[str, str, str]] = []
    problems: list[ProseParseError] = []
    order: list[str] = []
    for path in sorted(src_dir.glob("REQ-*.md")):
        if path.stem == "REQ-xxx" or path.name.endswith(".tmpl"):
            continue  # a template stub, not a REQ — the reqfile.load_reqs rule
        order.append(path.name)
        raw = path.read_text(encoding="utf-8")
        if raw.lstrip().startswith("---"):
            passthrough[path.name] = raw  # already converted — a second run is a no-op
            continue
        try:
            one = parse_prose_req(raw, name=path.name)
            source = coerce_status(one.segments["status"], name=path.name)
            if demote_unrunnable_active(source, one.segments.get("acceptance_criteria", "")) != source:
                demotions.append((one.rid, source))
        except ProseParseError as exc:
            problems.append(exc)
            continue
        parsed[path.name] = one
        if tail := split_acceptance_tail(_block(one.segments, "acceptance_criteria"))[1]:
            acceptance_tails.append((one.rid, tail.splitlines()[0].strip()))
        merges.extend((one.rid, f) for f in one.merges)
        if one.dep_carry:
            dep_carries.append((one.rid, one.dep_carry))
        edges.extend(extract_supersedes(one))
    if problems:
        raise ProseParseError(
            f"{len(problems)} file(s)",
            "corpus not converted, nothing written:\n  "
            + "\n  ".join(str(p) for p in problems),
        )

    supersedes_map, extractions = resolve_supersedes(edges)
    converted = {
        filename: render_prose_req(
            one, name=filename, supersedes=supersedes_map.get(one.rid)
        )
        for filename, one in parsed.items()
    }
    converted.update(passthrough)

    dst_dir.mkdir(parents=True, exist_ok=True)
    reqs = []
    for filename in order:
        dest = dst_dir / filename
        dest.write_text(converted[filename], encoding="utf-8")
        reqs.append(parse_req(dest))

    index_path = dst_dir / "REQUIREMENTS_INDEX.md"
    conflicts = _title_conflicts(index_path, {r.id: r.title for r in reqs})
    index_path.write_text(
        splice_index(index_path.read_text(encoding="utf-8"), reqs)
        if index_path.exists()
        else build_index(reqs),
        encoding="utf-8",
    )
    return ConversionReport(
        reqs=reqs,
        title_conflicts=conflicts,
        demotions=demotions,
        merges=merges,
        dep_carries=dep_carries,
        supersedes=extractions,
        acceptance_tails=acceptance_tails,
    )


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
    for rid, field_name in report.merges:
        print(f"  {rid}: merged repeated '{field_name}' field bullets in source order")
    for rid, raw in report.dep_carries:
        print(
            f"  {rid}: 'Depends on' carried prose — ids extracted, raw line preserved in the "
            f"body: {raw!r}"
        )
    for superseding, superseded, encoding in report.supersedes:
        print(f"  {superseding}: supersedes {superseded} (from {encoding})")
    for rid, first_line in report.acceptance_tails:
        print(
            f"  {rid}: prose after the checkbox list moved into Notes (the acceptance "
            f"transcode would have destroyed it): {first_line[:70]!r}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
