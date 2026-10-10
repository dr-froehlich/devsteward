"""Joint tasks between projects (REQ-101): one project asks, its sibling answers, both say done.

A project that needs another project to act opens a **thread** with an ``action``. From then
on the two parties exchange ``ask`` (a request for feedback, information or a decision),
``tell`` (information pushed to the other side, an answer included) and finally ``done`` —
the thread stays open until **both** have said ``done``. Four rules shape everything here.

**A project writes only into its own repo.** Every message a project sends, and every
acknowledgement it gives, is one line appended to *its own* ``.devsteward/joint.jsonl``; the
counterpart reads it there. Writing into another project's tree would be swept into whatever
session runs there (REQ-079 commits the whole tree) or roll its land back (REQ-077 Decision 3).
So each repo's history holds exactly what that project authored — split history, by the
owner's choice (Decision 2).

**The log is append-only.** A sent message is never edited; a correction is a new message.
No function here rewrites or removes a line, which is what lets a reference
``<author>#<seq>`` mean the same thing forever (Decision 4).

**Nothing stores state.** Whether a message was handled, whether a thread is closed, whether a
request was taken up — all derived on read: from the receiver's own ``ack``/reply lines, from
the two ``done`` lines, from the addressee's backlog and ``backlog_refs`` (REQ-093 Decision 6).
The thread handle *is* the backlog handle the receiver files the request under, so one string
names the job in both repos and no "filed as" message ever has to travel back (Decision 5).

**A neighbour's bad line never blocks a session.** The reader tolerates what it cannot parse in
a sibling's log — it reports the file and line and moves on (Decision 10). The file belongs to a
project the reading session does not own and cannot repair; REQ-100 showed what one bad row
does when the reader is strict.

Peers are the stamped siblings of this project (:mod:`devsteward.projects`, the dashboard's own
discovery); a project's name is its folder name, matched case-insensitively. Nothing here
commits, and nothing here starts a session (REQ-034 Decision 6).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ...config import Config, load_config
from ...core.ledger import LEDGER_DIRNAME
from ...projects import ProjectRef, scan_root
from . import backlog as bl

#: The project's own append-only log, committed under ``.devsteward/`` beside the ledger and
#: the backlog's verdict log — a separate file, owned by this profile (Decision 4).
LOG_FILE = "joint.jsonl"

ACTION = "action"
ASK = "ask"
TELL = "tell"
DONE = "done"
#: Not a message: the receiver's own mark that it handled one (Decision 6).
ACK = "ack"
MESSAGE_KINDS = (ACTION, ASK, TELL, DONE)
KINDS = MESSAGE_KINDS + (ACK,)

_HANDLE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REF_RE = re.compile(r"^(?P<author>[^#\s]+)#(?P<seq>[1-9][0-9]*)$")


class JointError(Exception):
    """A joint verb refused: nothing was written."""


@dataclass
class Entry:
    """One line of a project's log. ``author`` is not stored — it is whose log the line is in."""

    author: str
    seq: int
    at: str
    thread: str
    kind: str
    to: str | None = None
    need: str | None = None
    body: str = ""
    reply_to: str | None = None
    ref: str | None = None

    @property
    def ref_id(self) -> str:
        """The message's reference, stable forever because the log is append-only."""
        return f"{self.author}#{self.seq}"

    @property
    def instant(self) -> datetime:
        return datetime.fromisoformat(self.at)

    def as_json(self) -> dict:
        out: dict = {"seq": self.seq, "at": self.at, "thread": self.thread, "kind": self.kind}
        for key in ("to", "need", "body", "reply_to", "ref"):
            value = getattr(self, key)
            if value:
                out[key] = value
        return out


@dataclass
class Thread:
    """One joint task between exactly two projects, merged from both parties' logs."""

    handle: str
    opener: str
    addressee: str
    #: Both parties' lines carrying this handle, oldest first (the ``action`` included).
    entries: list[Entry] = field(default_factory=list)

    @property
    def parties(self) -> tuple[str, str]:
        return (self.opener, self.addressee)

    @property
    def action(self) -> Entry:
        return next(e for e in self.entries if e.kind == ACTION)

    @property
    def messages(self) -> list[Entry]:
        return [e for e in self.entries if e.kind != ACK]

    @property
    def done_by(self) -> list[str]:
        return [p for p in self.parties if any(e.kind == DONE and e.author == p for e in self.entries)]

    @property
    def closed(self) -> bool:
        """Kept up until both acknowledge the job is finished — one ``done`` is not enough."""
        return len(self.done_by) == 2

    def other(self, me: str) -> str:
        return self.addressee if me == self.opener else self.opener

    def message(self, ref: str) -> Entry | None:
        return next((m for m in self.messages if m.ref_id == ref), None)

    def handled(self, msg: Entry) -> bool:
        """The message's receiver acknowledged it or replied to it — read from *its* lines."""
        receiver = self.other(msg.author)
        return any(
            e.author == receiver
            and ((e.kind == ACK and e.ref == msg.ref_id) or e.reply_to == msg.ref_id)
            for e in self.entries
        )

    def waiting_for(self, me: str) -> list[Entry]:
        """The other party's messages ``me`` has neither acknowledged nor answered."""
        if self.closed:
            return []
        return [m for m in self.messages if m.author != me and not self.handled(m)]

    def dangling(self) -> list[tuple[Entry, str]]:
        """``(entry, reference)`` for every reply-to or ack naming no message of the thread.

        It happens when a sender discards an uncommitted line its peer already read (the
        retraction risk REQ-101 names) — shown, never raised.
        """
        known = {m.ref_id for m in self.messages}
        out = []
        for e in self.entries:
            for ref in (e.reply_to, e.ref):
                if ref and ref not in known:
                    out.append((e, ref))
        return out


@dataclass
class View:
    """Everything one project sees: the threads it is a party of, and what could not be read."""

    me: str
    threads: list[Thread]
    problems: list[str]

    def thread(self, handle: str) -> Thread:
        for t in self.threads:
            if t.handle == handle:
                return t
        known = ", ".join(t.handle for t in self.threads) or "none"
        raise JointError(
            f"no joint thread '{handle}' that {self.me} is a party of\n  its threads: {known}"
        )

    @property
    def open_threads(self) -> list[Thread]:
        return [t for t in self.threads if not t.closed]


# -- reading -------------------------------------------------------------------------


def log_path(root: Path) -> Path:
    return Path(root) / LEDGER_DIRNAME / LOG_FILE


def _entry(author: str, data) -> Entry | str:
    """Validate one decoded line into an :class:`Entry`, or say why it is unreadable."""
    if not isinstance(data, dict):
        return "not a JSON object"
    seq, at, thread, kind = data.get("seq"), data.get("at"), data.get("thread"), data.get("kind")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        return "no positive integer 'seq'"
    if not isinstance(at, str):
        return "no 'at' time"
    try:
        stamp = datetime.fromisoformat(at)
    except ValueError:
        return f"'at' is not an ISO 8601 time: {at!r}"
    if stamp.tzinfo is None:
        return f"'at' carries no offset: {at!r}"
    if not isinstance(thread, str) or not _HANDLE_RE.match(thread):
        return f"'thread' is not a kebab-case handle: {thread!r}"
    if kind not in KINDS:
        return f"'kind' is not one of {' | '.join(KINDS)}: {kind!r}"
    strings = {k: data.get(k) for k in ("to", "need", "body", "reply_to", "ref")}
    for key, value in strings.items():
        if value is not None and not isinstance(value, str):
            return f"'{key}' is not a string"
    if kind == ACTION and not (strings["to"] and strings["need"]):
        return "an action needs 'to' and 'need'"
    if kind == ACK and not strings["ref"]:
        return "an ack needs 'ref'"
    return Entry(author=author, seq=seq, at=at, thread=thread, kind=kind,
                 to=strings["to"], need=strings["need"], body=strings["body"] or "",
                 reply_to=strings["reply_to"], ref=strings["ref"])


def read_log(root: Path, author: str, *, shown_as: str | None = None) -> tuple[list[Entry], list[str]]:
    """Every readable line of ``root``'s log, and a problem line for each unreadable one.

    Tolerant on purpose (Decision 10): a bad line is reported by file and line number and
    skipped, so one damaged neighbour never hides anybody else's messages. Lines are cut on
    ``\\n`` only — JSON escapes every newline, but not ``U+2028``, which ``str.splitlines``
    would split on.
    """
    path = log_path(root)
    label = shown_as or str(path)
    if not path.exists():
        return [], []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], [f"{label}: unreadable: {exc}"]
    entries: list[Entry] = []
    problems: list[str] = []
    for idx, raw in enumerate(text.split("\n")):
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"{label}: line {idx + 1}: not valid JSON ({exc.msg})")
            continue
        entry = _entry(author, data)
        if isinstance(entry, str):
            problems.append(f"{label}: line {idx + 1}: {entry}")
        else:
            entries.append(entry)
    return entries, problems


def projects(cfg: Config) -> list[ProjectRef]:
    """The stamped siblings of ``cfg``'s project, itself included."""
    return [r for r in scan_root(cfg.root.parent) if r.stamped]


def _order(e: Entry):
    return (e.instant, e.author, e.seq)


def _corpus(cfg: Config) -> tuple[list[Thread], list[str]]:
    """Every thread among the stamped siblings, and every problem met reading their logs."""
    refs = projects(cfg)
    by_lower = {r.name.lower(): r.name for r in refs}
    logs: dict[str, list[Entry]] = {}
    problems: list[str] = []
    for r in refs:
        entries, probs = read_log(r.root, r.name, shown_as=f"{r.name}/{LEDGER_DIRNAME}/{LOG_FILE}")
        logs[r.name] = entries
        problems += probs
    threads: list[Thread] = []
    seen: dict[tuple[str, str], Thread] = {}
    actions = sorted((e for es in logs.values() for e in es if e.kind == ACTION), key=_order)
    for a in actions:
        addressee = by_lower.get(a.to.lower(), a.to)
        key = (a.thread, frozenset((a.author, addressee)))
        if key in seen:
            problems.append(f"{a.author}: {a.ref_id} opens '{a.thread}' a second time — ignored")
            continue
        t = Thread(handle=a.thread, opener=a.author, addressee=addressee)
        t.entries = sorted(
            (e for p in t.parties for e in logs.get(p, []) if e.thread == a.thread), key=_order
        )
        seen[key] = t
        threads.append(t)
    return threads, problems


def view(cfg: Config) -> View:
    """What ``cfg``'s project sees: the threads it opened or was addressed in."""
    me = cfg.root.name
    threads, problems = _corpus(cfg)
    return View(me=me, threads=[t for t in threads if me in t.parties], problems=problems)


def _backlog_handles(root: Path) -> set[str]:
    """The item handles in ``root``'s backlog; empty when it has none or cannot be read."""
    try:
        return {i.handle for i in bl.load(load_config(root).backlog_path)}
    except Exception:  # a neighbour's broken config or backlog must not block (Decision 10)
        return set()


def candidates(cfg: Config, v: View) -> list[Thread]:
    """Requests addressed to this project whose handle is not yet an item in its backlog."""
    filed = _backlog_handles(cfg.root)
    return [t for t in v.open_threads if t.addressee == v.me and t.handle not in filed]


def take_up(cfg: Config, thread: Thread) -> str:
    """The addressee's take-up of the request, as its own ``backlog-list`` derives it."""
    peer = next((r for r in projects(cfg) if r.name == thread.addressee), None)
    if peer is None:
        return f"{thread.addressee} is not a stamped project beside {cfg.root.name}"
    try:
        bits = bl.bits(load_config(peer.root))
    except Exception as exc:  # a neighbour's broken backlog is shown, never raised
        return f"{thread.addressee}'s backlog cannot be read: {exc}"
    status = {r.id: str(r.status) for r in bits.reqs}
    for st in bits.standings():
        if st.item.handle == thread.handle:
            label = bl.describe(st)
            if st.taken_up_by:
                reqs = ", ".join(f"{rid} ({status.get(rid, '?')})" for rid in st.taken_up_by)
                return f"{label} — taken up by {reqs}"
            return f"{label} — filed in {thread.addressee}'s backlog, no REQ yet"
    return f"not filed in {thread.addressee}'s backlog yet"


# -- writing -------------------------------------------------------------------------


def _addressable(cfg: Config) -> str:
    names = [r.name for r in projects(cfg) if r.root.resolve() != cfg.root.resolve()]
    return ", ".join(names) or "none"


def resolve_peer(cfg: Config, name: str) -> ProjectRef:
    """The stamped sibling ``name`` names, matched case-insensitively — or a refusal."""
    refs = scan_root(cfg.root.parent)
    hits = [r for r in refs if r.name.lower() == name.strip().lower()]
    known = f"\n  addressable projects: {_addressable(cfg)}"
    if not hits:
        raise JointError(f"no project named '{name}' beside {cfg.root.name}{known}")
    if len(hits) > 1:
        both = " and ".join(r.name for r in hits)
        raise JointError(f"'{name}' matches {both}, which differ only by case{known}")
    hit = hits[0]
    if hit.root.resolve() == cfg.root.resolve():
        raise JointError(f"{cfg.root.name} cannot address itself{known}")
    if not hit.stamped:
        raise JointError(f"'{hit.name}' is not a stamped DevSteward project{known}")
    return hit


def _prefix(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return "-".join(re.findall(r"[a-z0-9]+", folded)) or "project"


def _append(cfg: Config, entry: Entry) -> Entry:
    """Append one line to this project's own log. Never rewrites what is there (Decision 4)."""
    path = log_path(cfg.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing, _ = read_log(cfg.root, cfg.root.name)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = sum(1 for line in text.split("\n") if line.strip())
    entry.seq = max([lines, *(e.seq for e in existing)]) + 1
    entry.at = datetime.now().astimezone().isoformat(timespec="microseconds")
    lead = "\n" if text and not text.endswith("\n") else ""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(lead + json.dumps(entry.as_json(), ensure_ascii=False) + "\n")
    return entry


def open_thread(cfg: Config, to: str, need: str, *, handle: str | None = None,
                body: str = "") -> Entry:
    """``steward joint-send --to`` — open a thread with a request for action."""
    need = bl.one_line(need)
    if not need:
        raise JointError("a request needs its need, in one line")
    peer = resolve_peer(cfg, to)
    me = cfg.root.name
    threads, _ = _corpus(cfg)
    taken = {t.handle for t in threads if me in t.parties or peer.name in t.parties}
    taken |= _backlog_handles(peer.root)
    if handle is not None:
        if not _HANDLE_RE.match(handle):
            raise JointError(f"handle {handle!r} is not lowercase kebab-case")
        if handle in taken:
            raise JointError(
                f"handle '{handle}' already names a thread of {me} or {peer.name}, "
                f"or an item in {peer.name}'s backlog"
            )
    else:
        base = f"{_prefix(me)}-{bl.mint_handle(need)}"
        handle, n = base, 2
        while handle in taken:
            handle, n = f"{base}-{n}", n + 1
    entry = Entry(author=me, seq=0, at="", thread=handle, kind=ACTION, to=peer.name,
                  need=need, body=body.strip())
    return _append(cfg, entry)


def send(cfg: Config, handle: str, kind: str, *, body: str = "",
         reply_to: str | None = None) -> Entry:
    """``steward joint-send HANDLE --kind ask|tell|done`` — say something into a thread."""
    if kind not in (ASK, TELL, DONE):
        raise JointError(f"kind {kind!r} is not one of ask | tell | done")
    v = view(cfg)
    t = v.thread(handle)
    if t.closed:
        raise JointError(f"thread '{handle}' is closed: both {t.opener} and {t.addressee} said done")
    if reply_to is not None and t.message(reply_to) is None:
        known = ", ".join(m.ref_id for m in t.messages)
        raise JointError(f"'{reply_to}' is no message of thread '{handle}'\n  its messages: {known}")
    body = body.strip()
    if kind in (ASK, TELL) and not body:
        raise JointError(f"an {kind} needs a body — say what you ask or tell")
    entry = Entry(author=v.me, seq=0, at="", thread=handle, kind=kind, body=body,
                  reply_to=reply_to)
    return _append(cfg, entry)


def ack(cfg: Config, handle: str, ref: str) -> Entry | None:
    """``steward joint-ack`` — mark a message to this project handled; ``None`` if it already was."""
    v = view(cfg)
    t = v.thread(handle)
    if t.closed:
        raise JointError(f"thread '{handle}' is closed: both {t.opener} and {t.addressee} said done")
    msg = t.message(ref)
    if msg is None or msg.author == v.me:
        incoming = ", ".join(m.ref_id for m in t.messages if m.author != v.me) or "none"
        raise JointError(
            f"'{ref}' is no message to {v.me} in thread '{handle}'\n  messages to {v.me}: {incoming}"
        )
    if t.handled(msg):
        return None
    entry = Entry(author=v.me, seq=0, at="", thread=handle, kind=ACK, ref=ref)
    return _append(cfg, entry)
