"""The stakeholder-requirement layer (REQ-093): a backlog of user needs above the REQ.

A REQ is a *system* requirement — solution-shaped, with criteria that name runnable tests.
This module owns the level above it: the need in the user's own words, which a REQ is
*translated from* at intake. In ISO/IEC/IEEE 29148 terms the backlog is the StRS and a REQ
is the SyRS; the transformation between them is what ``/intake`` performs.

Three rules shape everything here.

**Nothing stores status.** The file holds an item's handle, its need and its provenance —
never a status column, never a "taken up by" column. Take-up derives from the REQ's
``backlog_refs:`` (whose single writer is intake, in the same commit as the REQ and its index
row) and the acceptance verdict derives from an append-only event log. A stored copy of
either would be a second record with no writer at land, which is the defect REQ-083
subtracted from the retired planning artifact.

**Verdicts are append-only.** The sequence of verdicts across REQs *is* the attempt record:
which REQ tried to satisfy a need, and why the owner did not accept it. Overwriting would
destroy the one artifact that stops the next REQ repeating the attempt.

**Acceptance is advisory to the REQ and blocking to the item.** Denying an item does not
fail the REQ that attempted it — verification and acceptance are independent verdicts — so
nothing in this module participates in the develop gate.

The module is deliberately profile-owned: :mod:`devsteward.core` is the generic executor and
must not learn what a user need is.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ...core.ledger import LEDGER_DIRNAME

#: The append-only verdict log, committed under ``.devsteward/`` beside the ledger — but a
#: *separate* file: these are content-aware events and the core's ``events.jsonl`` is the
#: content-agnostic executor's own log (REQ-093 Decision 5).
EVENTS_FILE = "backlog.jsonl"

#: Verdict kinds. Take-up is deliberately absent — it is derived, never recorded.
ACCEPTED = "accepted"
DENIED = "denied"
RETIRED = "retired"
#: ``held`` is not a retirement and not a denial: the need stands, the owner has ruled that
#: it is deliberately **not being worked**, and the ruling has a reason. Surfaced by
#: DriveSteward's live corpus (REQ-093), where an item was waiting "on a reason to be believed
#: rather than on a session" — a state neither `open` (which would read as available) nor
#: `retired` (which would read as withdrawn) can express without losing the owner's ruling.
HELD = "held"
VERDICTS = (ACCEPTED, DENIED, RETIRED, HELD)

#: Item provenance. ``operator`` = the owner's own words; ``proposed`` = a session proposed
#: it and the owner chose it from alternatives. The distinction is the guard against the
#: system writing its own requirements and then satisfying them (REQ-093 Decision 9).
OPERATOR = "operator"
PROPOSED = "proposed"
ORIGINS = (OPERATOR, PROPOSED)

_HANDLE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
#: An item's acceptance criteria live under ``### <handle>`` inside the acceptance section,
#: as a plain bullet list in the user's language. The engine never grades them — acceptance
#: is a human verdict (REQ-093 Decision 2) — it only surfaces them when the verdict is given
#: and refuses a section naming an item that does not exist.
_ACCEPTANCE_SECTION_RE = re.compile(r"^acceptance criteria$", re.IGNORECASE)
_BULLET_RE = re.compile(r"^[-*]\s+(.*\S)\s*$")
_COMMENT_OPEN = "<!--"
_COMMENT_CLOSE = "-->"
#: The table header that marks the item table. Matched case-insensitively on the three
#: column names so a consumer may capitalize as they like.
_HEADER_RE = re.compile(
    r"^\|\s*handle\s*\|\s*need\s*\|\s*origin\s*\|\s*$", re.IGNORECASE
)
_DIVIDER_RE = re.compile(r"^\|[\s:|-]+\|$")
_ROW_RE = re.compile(r"^\|(?P<handle>[^|]*)\|(?P<need>.*)\|(?P<origin>[^|]*)\|\s*$")

#: Words too generic to carry a minted handle's meaning on their own.
_STOPWORDS = frozenset(
    "a an the is are be to of for in on at by with and or that this it its there "
    "shall should must can could would when while user users i we".split()
)


def _live_lines(text: str):
    """Yield ``(index, stripped_line)`` for every line outside an HTML comment.

    A commented-out row or criteria block is documentation, not content — the stamped
    template ships a worked example that way, and reading it as live content would red a
    fresh project on its first lint. Indices are preserved so callers can still splice by
    line number.
    """
    in_comment = False
    for idx, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if in_comment:
            if _COMMENT_CLOSE in line:
                in_comment = False
            continue
        if _COMMENT_OPEN in line:
            before = line.split(_COMMENT_OPEN, 1)[0].strip()
            if _COMMENT_CLOSE not in line.split(_COMMENT_OPEN, 1)[1]:
                in_comment = True
            if not before:
                continue
            line = before
        yield idx, line


class BacklogError(Exception):
    """A backlog file or event log could not be read as the format requires."""


@dataclass
class Item:
    """One stakeholder requirement: a need in the user's words."""

    handle: str
    need: str
    origin: str = OPERATOR
    #: Zero-based index of this item's line within the source text's lines.
    line: int = -1


@dataclass
class Event:
    """One recorded verdict. Never rewritten; the sequence is the attempt record."""

    handle: str
    event: str
    ts: str = ""
    req: str | None = None
    reason: str | None = None
    note: str | None = None

    def as_json(self) -> dict:
        out: dict = {"ts": self.ts, "handle": self.handle, "event": self.event}
        for key in ("req", "reason", "note"):
            value = getattr(self, key)
            if value:
                out[key] = value
        return out


@dataclass
class Standing:
    """An item's derived position: state plus the record of what has been tried."""

    item: Item
    state: str
    #: REQ ids whose ``backlog_refs`` name this handle, in corpus order.
    taken_up_by: list[str] = field(default_factory=list)
    #: Every verdict recorded against this handle, oldest first.
    verdicts: list[Event] = field(default_factory=list)
    #: The item's own acceptance criteria, in the user's words (may be empty).
    criteria: list[str] = field(default_factory=list)

    @property
    def denials(self) -> list[Event]:
        return [e for e in self.verdicts if e.event == DENIED]


# -- the file ------------------------------------------------------------------


def parse(text: str) -> list[Item]:
    """Read every item from a backlog file's ``text``.

    Tolerant of real prose: any content before, between or after the table is ignored here
    and preserved verbatim by :func:`append_item`. A row whose handle cell is malformed is a
    hard error rather than a silent skip — a dropped item is exactly the failure this whole
    layer exists to prevent.
    """
    items: list[Item] = []
    seen: dict[str, int] = {}
    in_table = False
    for idx, stripped in _live_lines(text):
        if _HEADER_RE.match(stripped):
            in_table = True
            continue
        if not in_table:
            continue
        if not stripped.startswith("|"):
            in_table = False  # the table ended; later tables may still follow
            continue
        if _DIVIDER_RE.match(stripped):
            continue
        m = _ROW_RE.match(stripped)
        if not m:
            raise BacklogError(f"line {idx + 1}: not a well-formed item row: {stripped!r}")
        handle = m.group("handle").strip().strip("`")
        need = m.group("need").strip()
        origin = (m.group("origin").strip() or OPERATOR).lower()
        if not _HANDLE_RE.match(handle):
            raise BacklogError(
                f"line {idx + 1}: handle {handle!r} is not lowercase kebab-case"
            )
        if origin not in ORIGINS:
            raise BacklogError(
                f"line {idx + 1}: origin {origin!r} is not one of {' | '.join(ORIGINS)}"
            )
        if handle in seen:
            raise BacklogError(
                f"line {idx + 1}: handle {handle!r} is already used on line {seen[handle] + 1}"
            )
        seen[handle] = idx
        items.append(Item(handle=handle, need=need, origin=origin, line=idx))
    return items


def parse_criteria(text: str) -> dict[str, list[str]]:
    """Read the per-item acceptance criteria — the *user's* conditions of satisfaction.

    These are the stakeholder-level criteria (what Scrum calls acceptance criteria, written
    per item and owned by the person with the need), distinct from a REQ's verification
    criteria. They are authored at intake **before** the translation into a requirement:
    criteria written knowing the solution get bent to fit what was going to be built anyway.

    Shape — a top-level acceptance section, then one ``###`` heading per handle::

        ## Acceptance criteria

        ### rapid-verdict
        - In under five minutes I can see whether this drive is worth repairing.

    Scoped to that section on purpose: a project's ordinary prose headings must never be
    mistaken for item handles, or the linter would red on a heading that means nothing to
    this layer.
    """
    out: dict[str, list[str]] = {}
    in_section = False
    current: str | None = None
    for _, stripped in _live_lines(text):
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip().strip("`")
            if _ACCEPTANCE_SECTION_RE.match(title):
                in_section, current = True, None
                continue
            if level <= 2:  # any other top-level heading closes the section
                in_section, current = False, None
                continue
            current = title if in_section and _HANDLE_RE.match(title) else None
            if current is not None:
                out.setdefault(current, [])
            continue
        if current is None:
            continue
        if b := _BULLET_RE.match(stripped):
            out[current].append(b.group(1))
    return {h: c for h, c in out.items() if c}


def load(path: Path) -> list[Item]:
    """Parse the backlog at ``path``; an absent file is an empty backlog, never an error."""
    p = Path(path)
    if not p.exists():
        return []
    return parse(p.read_text(encoding="utf-8"))


def _cell(value: str) -> str:
    """Escape a value for a markdown table cell (a literal ``|`` would split the row)."""
    return value.replace("|", "\\|").strip()


def append_item(text: str, item: Item) -> str:
    """Return ``text`` with ``item`` appended as the table's last row.

    Every byte outside the inserted line is preserved — the prose a project keeps around and
    after its table is the reason the format is a spliced table rather than a generated file.
    """
    lines = text.splitlines(keepends=True)
    existing = parse(text)
    if existing:
        insert_at = existing[-1].line + 1
    else:
        insert_at = None
        for idx, line in enumerate(lines):
            if _HEADER_RE.match(line.strip()):
                insert_at = idx + 1
                # skip the divider row when present
                if insert_at < len(lines) and _DIVIDER_RE.match(lines[insert_at].strip()):
                    insert_at += 1
                break
        if insert_at is None:
            raise BacklogError(
                "no item table found — the file needs a `| Handle | Need | Origin |` header"
            )
    row = f"| {_cell(item.handle)} | {_cell(item.need)} | {_cell(item.origin)} |\n"
    # A file whose last line lacks a trailing newline would otherwise glue onto the new row.
    if insert_at > 0 and lines[insert_at - 1] and not lines[insert_at - 1].endswith("\n"):
        lines[insert_at - 1] += "\n"
    lines.insert(insert_at, row)
    return "".join(lines)


def mint_handle(need: str, taken: set[str] | None = None) -> str:
    """Derive a stable, readable handle from the need text, unique against ``taken``.

    Two or three meaning-carrying words, kebab-cased. A collision gets a numeric suffix
    rather than a longer slug, so the handle stays quotable in conversation.
    """
    taken = taken or set()
    folded = unicodedata.normalize("NFKD", need).encode("ascii", "ignore").decode()
    words = [w for w in re.findall(r"[a-z0-9]+", folded.lower()) if w not in _STOPWORDS]
    if not words:  # a need made entirely of stopwords still deserves a handle
        words = re.findall(r"[a-z0-9]+", folded.lower()) or ["item"]
    base = "-".join(words[:3]) or "item"
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


# -- the event log -------------------------------------------------------------


def events_path(root: Path) -> Path:
    return Path(root) / LEDGER_DIRNAME / EVENTS_FILE


def read_events(root: Path) -> list[Event]:
    """Every recorded verdict, oldest first. An absent log is no verdicts."""
    path = events_path(root)
    if not path.exists():
        return []
    out: list[Event] = []
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BacklogError(f"{path}: line {idx + 1} is not valid JSON: {exc}") from exc
        out.append(
            Event(
                handle=str(data.get("handle", "")),
                event=str(data.get("event", "")),
                ts=str(data.get("ts", "")),
                req=data.get("req"),
                reason=data.get("reason"),
                note=data.get("note"),
            )
        )
    return out


def append_event(root: Path, event: Event) -> Event:
    """Append one verdict. Never rewrites — a later verdict leaves the earlier one readable."""
    if event.event not in VERDICTS:
        raise BacklogError(f"{event.event!r} is not one of {' | '.join(VERDICTS)}")
    if event.event in (DENIED, RETIRED, HELD) and not (event.reason or "").strip():
        raise BacklogError(f"a {event.event} verdict requires a reason")
    event.ts = event.ts or datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = events_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event.as_json(), ensure_ascii=False) + "\n")
    return event


# -- derived state -------------------------------------------------------------

OPEN = "open"
IN_PROGRESS = "in-progress"
ATTEMPTED = "attempted"

#: REQ statuses that mean the REQ can no longer be working on anything.
_TERMINAL = {"done", "dropped", "superseded"}


def standings(
    items: list[Item],
    reqs: list,
    events: list[Event],
    criteria: dict[str, list[str]] | None = None,
) -> list[Standing]:
    """Join items with the REQ graph and the verdict log — the only place state comes from.

    ``reqs`` is a list of :class:`~devsteward.profiles.req.reqfile.ReqFile`; only ``id``,
    ``status`` and ``backlog_refs`` are read, so a caller may pass any equivalent.
    """
    by_handle: dict[str, list] = {}
    for r in reqs:
        for handle in getattr(r, "backlog_refs", []):
            by_handle.setdefault(handle, []).append(r)
    verdicts: dict[str, list[Event]] = {}
    for e in events:
        verdicts.setdefault(e.handle, []).append(e)

    out: list[Standing] = []
    for item in items:
        refs = by_handle.get(item.handle, [])
        mine = verdicts.get(item.handle, [])
        latest = mine[-1] if mine else None
        # Precedence matters. `accepted` and `retired` are settled outcomes and outrank
        # everything. `held` and `denied` are not outcomes — the need still stands — so a
        # live REQ working on the item outranks them both: taking an item up lifts a hold,
        # and is exactly the case Decision 3 describes for a denied item taken up again.
        if latest is not None and latest.event in (ACCEPTED, RETIRED):
            state = latest.event
        elif any(str(r.status).lower() not in _TERMINAL for r in refs):
            state = IN_PROGRESS
        elif latest is not None and latest.event == HELD:
            state = HELD
        elif latest is not None and latest.event == DENIED:
            state = OPEN  # denial does not close an item; it records an attempt
        elif refs:
            state = ATTEMPTED
        else:
            state = OPEN
        out.append(
            Standing(
                item=item,
                state=state,
                taken_up_by=[r.id for r in refs],
                verdicts=mine,
                criteria=(criteria or {}).get(item.handle, []),
            )
        )
    return out


def describe(standing: Standing) -> str:
    """The one-line state label, including the denial count that keeps an attempt visible."""
    n = len(standing.denials)
    if standing.state == OPEN and n:
        return f"open (denied {n}×)"
    return standing.state
