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
#: A run of whitespace holding at least one line boundary — every character
#: ``str.splitlines()`` splits on, because that is how the reader cuts the file into lines.
#: Left in a value, any of them splits its row or bullet in two (REQ-100).
_BREAK_RUN_RE = re.compile(r"\s*[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]\s*")

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

    A comment opens only on a line that *starts* with ``<!--`` (CommonMark's HTML-block
    start) and closes on the first line holding ``-->``. A marker anywhere else is text: the
    writer starts every row with ``|`` and every bullet with ``-``, so a need or criterion
    that merely mentions ``<!--`` can never hide itself or what follows it (REQ-100).
    """
    in_comment = False
    for idx, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if in_comment:
            if _COMMENT_CLOSE in line:
                in_comment = False
            continue
        if line.startswith(_COMMENT_OPEN):
            in_comment = _COMMENT_CLOSE not in line[len(_COMMENT_OPEN):]
            continue
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
        need = _uncell(m.group("need").strip())
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


def one_line(value: str) -> str:
    """``value`` as the backlog file stores it: one line (REQ-100 Decision 1).

    Each run of whitespace that holds a line boundary becomes a single space — an item is
    one table row and a criterion one bullet, so a need typed over several lines keeps every
    word and loses only its paragraph breaks.
    """
    return _BREAK_RUN_RE.sub(" ", value).strip()


def _cell(value: str) -> str:
    """Encode a value for a markdown table cell: folded to one line, every ``|`` escaped.

    :func:`_uncell` is its exact inverse — the writer puts one backslash before each ``|``
    and the reader takes exactly that one away, so a need survives any number of rewrites.
    """
    return one_line(value).replace("|", "\\|")


def _uncell(value: str) -> str:
    """Decode a need cell: the inverse of :func:`_cell`'s ``|`` escape."""
    return value.replace("\\|", "|")


def _read_back(text: str, item: Item, criteria: list[str] | None, backlog_file: str) -> None:
    """Refuse to write ``text`` unless it reads back with ``item`` exactly as stored.

    The check runs *before* the write (REQ-100 Decision 4): a gap in the encoding then costs
    one refused write and an intact file, never a file that nothing can read.
    """
    try:
        found = {i.handle: i for i in parse(text)}.get(item.handle)
        got_criteria = parse_criteria(text).get(item.handle, [])
    except BacklogError as exc:
        raise BacklogError(
            f"refused to write {backlog_file}: the result would not read back ({exc}); "
            "the file is unchanged"
        ) from exc
    if (
        found is None
        or (found.need, found.origin) != (item.need, item.origin)
        or (criteria is not None and got_criteria != criteria)
    ):
        raise BacklogError(
            f"refused to write {backlog_file}: item '{item.handle}' would not read back as "
            "written; the file is unchanged"
        )


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


# -- file-level operations shared by the CLI and the dashboard (REQ-097) -------------

# Every write below is the body of one ``steward backlog-*`` verb. The click command prints
# the result; the dashboard route redirects with it. Neither surface re-implements a write.


@dataclass
class Bits:
    """The derivation inputs of one project's backlog: items, REQ corpus, verdicts, criteria."""

    items: list[Item]
    reqs: list
    events: list[Event]
    criteria: dict[str, list[str]]

    def standings(self) -> list[Standing]:
        return standings(self.items, self.reqs, self.events, self.criteria)


def bits(cfg, reqs=None) -> Bits:
    """Load the parsed backlog, its verdict log and the REQ corpus — the three derivation
    inputs. ``reqs`` may hand in an already-parsed corpus (REQ-097)."""
    from .reqfile import load_reqs

    items = load(cfg.backlog_path)
    if reqs is None:
        reqs = load_reqs(cfg.req_dir) if cfg.req_dir.exists() else []
    criteria = (
        parse_criteria(cfg.backlog_path.read_text(encoding="utf-8"))
        if cfg.backlog_path.exists()
        else {}
    )
    return Bits(items=items, reqs=reqs, events=read_events(cfg.root), criteria=criteria)


def require_item(items: list[Item], handle: str, backlog_file: str) -> Item:
    """Resolve ``handle`` or raise :class:`BacklogError` naming what does exist."""
    for i in items:
        if i.handle == handle:
            return i
    if not items:
        raise BacklogError(
            f"no backlog at {backlog_file} — record a need with `steward backlog-add \"…\"` first"
        )
    known = ", ".join(i.handle for i in items)
    raise BacklogError(f"no backlog item '{handle}' in {backlog_file}\n  known: {known}")


def add(cfg, need: str, *, handle: str | None = None, origin: str = OPERATOR,
        template: str | None = None) -> tuple[str, bool]:
    """``steward backlog-add`` — append an item, creating the file from ``template`` when absent.

    Returns ``(handle, created)``. A handle is minted from the need when none is given; a
    given handle that collides is a :class:`BacklogError`.
    """
    path = cfg.backlog_path
    created = False
    if not path.exists():
        if template is None:
            raise BacklogError(f"no backlog at {cfg.backlog_file} and no template to create it from")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template, encoding="utf-8")
        created = True
    if origin not in ORIGINS:
        raise BacklogError(f"origin {origin!r} is not one of {' | '.join(ORIGINS)}")
    text = path.read_text(encoding="utf-8")
    existing = parse(text)
    taken = {i.handle for i in existing}
    if handle is None:
        handle = mint_handle(need, taken)
    elif handle in taken:
        raise BacklogError(f"handle '{handle}' is already used")
    elif not _HANDLE_RE.match(handle):
        raise BacklogError(f"handle {handle!r} is not lowercase kebab-case")
    new_text = append_item(text, Item(handle=handle, need=need, origin=origin))
    _read_back(new_text, Item(handle=handle, need=one_line(need), origin=origin), None,
               cfg.backlog_file)
    path.write_text(new_text, encoding="utf-8")
    return handle, created


def set_criteria(text: str, handle: str, bullets: list[str]) -> str:
    """Return ``text`` with ``handle``'s ``###`` block under the acceptance section replaced.

    Every byte outside that block is preserved. An empty ``bullets`` removes the block; a
    handle with no block yet gets one appended at the end of the acceptance section; a file
    with no acceptance section gets the section appended at its end.
    """
    lines = text.splitlines(keepends=True)
    live = list(_live_lines(text))
    section_start: int | None = None  # index of the line *after* the acceptance heading
    section_end = len(lines)  # index of the next level<=2 heading, or EOF
    block_start: int | None = None  # index of the `### handle` line
    block_end: int | None = None  # index of the line after the block
    for idx, stripped in live:
        if not stripped.startswith("#"):
            continue
        level = len(stripped) - len(stripped.lstrip("#"))
        title = stripped.lstrip("#").strip().strip("`")
        if section_start is None:
            if _ACCEPTANCE_SECTION_RE.match(title):
                section_start = idx + 1
            continue
        if level <= 2:
            section_end = idx
            break
        if block_start is None and title == handle:
            block_start = idx
            continue
        if block_start is not None and block_end is None:
            block_end = idx
    if block_start is not None and block_end is None:
        block_end = section_end

    body = [f"- {one_line(b)}\n" for b in bullets if b.strip()]
    block = [f"### {handle}\n", *body, "\n"] if body else []

    if block_start is not None:
        # Keep a blank line between the previous block and the next heading.
        return "".join(lines[:block_start] + block + lines[block_end:])
    if not body:
        return text
    if section_start is None:
        tail = "" if not lines or lines[-1].endswith("\n") else "\n"
        return text + tail + "\n## Acceptance criteria\n\n" + "".join(block)
    insert_at = section_end
    # Insert before the trailing blank lines that separate the section from the next heading.
    while insert_at > section_start and not lines[insert_at - 1].strip():
        insert_at -= 1
    prefix = lines[:insert_at]
    if prefix and not prefix[-1].endswith("\n"):
        prefix[-1] += "\n"
    if prefix and prefix[-1].strip():
        prefix.append("\n")
    return "".join(prefix + block + lines[insert_at:])


def edit(cfg, handle: str, *, need: str | None = None, origin: str | None = None,
         criteria: list[str] | None = None) -> Item:
    """``steward backlog-edit`` — rewrite one item's need, origin and/or acceptance criteria.

    Only the named parts change; the item's row is rewritten in place and its criteria block
    is spliced under the acceptance section. Every other byte of the file is preserved. The
    handle itself is never renamed (it is what ``backlog_refs`` and the verdict log key on).
    """
    path = cfg.backlog_path
    if not path.exists():
        raise BacklogError(f"no backlog at {cfg.backlog_file} (this project keeps none).")
    text = path.read_text(encoding="utf-8")
    item = require_item(parse(text), handle, cfg.backlog_file)
    if origin is not None and origin not in ORIGINS:
        raise BacklogError(f"origin {origin!r} is not one of {' | '.join(ORIGINS)}")
    if need is not None and not need.strip():
        raise BacklogError("an item's need cannot be empty")
    if need is not None or origin is not None:
        new_item = Item(
            handle=handle,
            need=one_line(need) if need is not None else item.need,
            origin=origin if origin is not None else item.origin,
        )
        lines = text.splitlines(keepends=True)
        lines[item.line] = (
            f"| {_cell(new_item.handle)} | {_cell(new_item.need)} | {_cell(new_item.origin)} |\n"
        )
        text = "".join(lines)
        item = new_item
    if criteria is not None:
        text = set_criteria(text, handle, criteria)
    stored = [one_line(c) for c in criteria if c.strip()] if criteria is not None else None
    _read_back(text, item, stored, cfg.backlog_file)
    path.write_text(text, encoding="utf-8")
    return item


def record_verdict(cfg, handle: str, verdict: str, *, reason: str | None = None,
                   note: str | None = None) -> tuple[Item, Event, list[str]]:
    """``steward backlog-accept|deny|hold|retire`` — append one verdict event.

    Returns ``(item, event, criteria)``: the item judged, the event as appended (its ``req``
    names the REQ that most recently attempted the need, so the attempt record reads as
    "REQ-019 tried and the owner said no, because …"), and the item's own criteria so the
    caller can show the owner what they are judging against.
    """
    b = bits(cfg)
    item = require_item(b.items, handle, cfg.backlog_file)
    attempted = [r.id for r in b.reqs if handle in r.backlog_refs]
    event = append_event(
        cfg.root,
        Event(handle=handle, event=verdict, req=attempted[-1] if attempted else None,
              reason=reason, note=note),
    )
    return item, event, b.criteria.get(handle, [])
