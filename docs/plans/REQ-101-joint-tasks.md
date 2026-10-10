# REQ-101 — Joint tasks between projects

Plan for `REQ-101:develop`. Requirement: `docs/requirements/REQ-101.md` (12 decisions,
4 regression ACs, no concept phase, no System-Test phase).

## The shape of the change

One new profile-owned module, four thin click verbs, one moved helper, two skill steps and
the manual. No ledger change, no schema change, no config seam, and no git: every joint
verb is an append to, or a read of, plain files.

| Piece | Where | What |
|---|---|---|
| discovery | `devsteward/projects.py` (new; moved from `dashboard/model.py`) | `ProjectRef`, `resolve_root`, `scan_root`. The dashboard model re-imports them, so `model.scan_root` keeps working for `app.py` and the tests. It is moved, not copied (Decision 3). |
| the protocol | `devsteward/profiles/req/joint.py` (new) | the log format, reading tolerantly, addressing, thread derivation, `send` / `ack` / `listing` / `show` |
| verbs | `devsteward/cli.py` | `joint-send`, `joint-ack`, `joint-list`, `joint-show`, each a thin printer around `joint.py` |
| skills | `.claude/skills/intake/SKILL.md`, `.claude/skills/advance/SKILL.md` (inode-shared with their templates) | the look-up steps (Decision 8) |
| manual | `devsteward/templates/STEWARD.md` (the root `STEWARD.md` is a symlink to it) | a "Joint tasks" section and four verb rows (Decision 12, REQ-094) |
| tests | `tests/test_req101_joint_tasks.py` | AC1–AC4 |

Why the protocol is profile-owned: it keys on backlog handles and reads the addressee's
`backlog_refs`. That is the REQ profile's content. The core stays content-agnostic, as with
`backlog.py` (REQ-093 Decision 5).

## Data shapes

`.devsteward/joint.jsonl`, one JSON object per line, only ever appended:

```json
{"seq": 1, "at": "2026-10-10T14:02:11.123456+02:00", "thread": "alpha-zone-target-late", "kind": "action",
 "to": "Beta", "need": "A target set on a zone's thermostat shows up to a minute late", "body": "…"}
{"seq": 2, "at": "…", "thread": "alpha-zone-target-late", "kind": "tell", "body": "…", "reply_to": "Beta#1"}
{"seq": 3, "at": "…", "thread": "alpha-zone-target-late", "kind": "ack", "ref": "Beta#2"}
```

- The author is not stored: it is the project whose log the line sits in, i.e. its folder name.
  A message's reference is `<author>#<seq>`.
- `at` is local time with its offset, at microsecond precision. Entries are merged by the
  parsed instant, then by author and seq, so two sends within one second still order stably.
- `to` is stored as the addressee's folder name exactly as found (`Beta`, even when the
  sender typed `beta`).
- `need` is folded with `backlog.one_line`, because the receiver files it with `backlog-add`
  verbatim (REQ-100).

In memory:

- `Entry(author, seq, at, thread, kind, to, need, body, reply_to, ref)`, with a `.ref_id`
  property. `kind` is one of `action ask tell done ack`.
- `Thread(handle, opener, addressee, entries)`. The opener is the author of the `action`, and
  `addressee` is its `to`. `entries` holds only those two parties' lines with this handle,
  merged in time order, so a third project's stray line never joins.
  - `.messages`: the non-ack entries. `.done_by`: the set of parties that sent `done`.
  - `.closed`: `done_by == {opener, addressee}`. `.other(me)`.
  - `.handled(msg)`: the message's receiver has an `ack` with `ref == msg.ref_id`, or a
    message with `reply_to == msg.ref_id`.
  - `.waiting_for(me)`: the other party's messages that `me` has not handled.
  - `.dangling()`: references (`reply_to` / `ref`) naming no message of the thread.
- `View(me, threads, problems)` is everything one project sees.
  - `problems` holds `"<path>: line N: <why>"` strings for unreadable lines in any log,
    reported and skipped (Decision 10). The reader never raises on a neighbour's bad line.

## Functions (`joint.py`)

- `log_path(root)` and `read_log(root, author) -> (entries, problems)`: tolerant. Each line
  must be a JSON object with an int `seq`, a str `at` that parses, a `thread` in the
  backlog-handle grammar and a `kind` in `KINDS`. An `action` also needs `to` and `need`, an
  `ack` needs `ref`. Anything else is a problem line, and the read moves on.
- `projects(cfg) -> list[ProjectRef]`: `scan_root(cfg.root.parent)`.
- `view(cfg) -> View`: reads every stamped sibling's log plus its own. It keeps the threads
  `me` is a party of (an `action` in its own log, or one elsewhere with `to` == me
  case-insensitively).
- `resolve_peer(cfg, name) -> ProjectRef`: case-insensitive match over the stamped siblings.
  `JointError` (listing the addressable names, nothing written) for an unknown name, an
  unstamped folder, itself, or two case-variant matches.
- `open_thread(cfg, to, need, *, handle=None, body="") -> Entry`. A minted handle is
  `<sender lowercased, folded to [a-z0-9-]>-<backlog.mint_handle(need)>`, re-minted with a
  numeric suffix on collision. A given handle must pass the grammar and not collide. Taken =
  thread handles visible to the sender ∪ those visible to the addressee ∪ handles in the
  addressee's backlog.
- `send(cfg, handle, kind, *, body="", reply_to=None) -> Entry` for `ask` / `tell` / `done`.
  `JointError` when:
  - no thread of mine has that handle;
  - the thread is closed;
  - `reply_to` names no message of the thread;
  - `ask` or `tell` has an empty body.

  The party check follows from `view` itself: a non-party has no such thread, and the
  message says so.
- `ack(cfg, handle, ref) -> Entry | None`. `ref` must be a message of the thread authored by
  the other party. Already handled → `None` (no write, the CLI says so). Closed → `JointError`.
- `_append(cfg, entry)`: `seq` = max(readable seqs, non-empty line count) + 1, `at` = now. It
  writes one line in append mode, so earlier bytes are never touched. That is AC2's prefix
  property.
- `take_up(peer_ref, handle)`: the addressee's standing for the handle, read through
  `backlog.bits(load_config(peer_root)).standings()`. It returns (state, taken-up REQ ids with
  their statuses) or a problem string when that backlog cannot be read.

## Verbs (`cli.py`)

```
steward joint-send --to PROJECT --need "…" [--handle H] [--body TEXT | --body-file F|-]   # opens a thread
steward joint-send HANDLE --kind ask|tell|done [--reply-to REF] [--body TEXT | --body-file F|-]
steward joint-ack HANDLE REF
steward joint-list
steward joint-show HANDLE
```

`--kind` defaults to `action`. `action` takes `--to` and `--need` and an optional HANDLE.
The other kinds take HANDLE and refuse `--to` / `--need`. `JointError` → `ClickException`
(non-zero exit).

`joint-list` prints three blocks and always exits 0:
- **waiting for me**: per open thread, each unhandled incoming message with its reference,
  kind and first line;
- **candidates**: incoming `action`s on open threads whose handle is not an item in my
  backlog;
- **open threads**: handle, other party, who opened it, who has sent `done`.

Problems come last. When nothing is open it prints one line.

`joint-show` prints:
- a header: handle, opener → addressee, open or closed, `done` by whom, and the addressee's
  take-up;
- then every entry in time order: messages with reference, kind, reply-to and
  handled/waiting, and acks as "X acknowledged REF";
- dangling references marked, never raised.

## Skills

- `/intake` §1 (Orient) gets a bullet: when the operator asks to take up another project's
  request, run `steward joint-list` and present its candidates. On the pick, run
  `steward backlog-add --handle <thread> --origin proposed "<need>"`, then
  `steward joint-ack <thread> <ref>`, and continue from §2d with that item. Questions for the
  requester go back as `steward joint-send <thread> --kind ask`.
- `/advance` §1 (Orient) gets a bullet: in interactive mode only, run `steward joint-list`.
  Work through what waits with the operator:
  - answer an `ask` with `--kind tell --reply-to`, putting a decision to the operator;
  - `joint-ack` a `tell` once read and acted on;
  - point an incoming `action` to `/intake`;
  - send `done` only when the operator agrees the job is finished.

  Skip it entirely under `DEVSTEWARD_UNATTENDED=1`.

## Tests (`tests/test_req101_joint_tasks.py`)

The fixture is a temp root holding `alpha` and `Beta` (stamped via `Ledger.init` plus a
config, with a backlog template in each) and an unstamped `plain/`. The verbs are driven
through `CliRunner` against `main` with the cwd set to the acting project: the real entrypoint.

- **AC1** `test_a_whole_thread_between_two_stamped_siblings`: the full scenario in the
  REQ's AC1 text. Take-up shows the REQ id after a `write_req(..., backlog_refs=[handle])`
  in Beta.
- **AC2** `test_every_verb_writes_only_its_own_log_and_only_by_appending`: the same thread,
  with a byte snapshot of every file in both projects before and after each call. Asserted:
  - the other project is identical;
  - the actor's only changed path is its `joint.jsonl`, and the old content is a prefix of
    the new;
  - `joint-list` / `joint-show` change nothing.
- **AC3** `test_addressing_resolves_stamped_siblings_and_refuses_the_rest`:
  - `--to BETA` resolves to `Beta`;
  - an unknown name, `plain`, `alpha` itself, and a case-variant pair (`Gamma` / `gamma`,
    created only on a case-sensitive filesystem) are refused, with the names listed and
    nothing written;
  - the minted handle's prefix and grammar hold;
  - a `--handle` that collides with a thread or with an item in Beta's backlog is refused;
  - a third stamped `gamma` sending into alpha's thread is refused, and so is a bogus
    `--reply-to`.
- **AC4** `test_a_bad_neighbour_log_is_reported_and_never_blocks`: alpha's log gets a
  malformed line and an `ack` naming `Beta#99`, and a third sibling has its own valid thread
  to Beta.
  - Beta's `joint-list` exits 0, names the bad file and line, and still lists alpha's valid
    request and the third sibling's.
  - `joint-show` marks `Beta#99` as dangling.

## Develop obligations outside the gate

- **STEWARD.md** in the same commit. `test_steward_manual.py::test_manual_covers_every_registered_verb`
  goes red until the four verbs are documented.
- **The live proof** (Decision 11): one real thread between two stamped projects, driven
  through attended `/intake` and `/advance` sessions on both sides. The pair is chosen with
  the owner after the verbs exist.

## The live proof: what happened (2026-10-10)

The pair was chosen at develop (REQ-101 Decision 11, as amended). devsteward ran in this develop
session. `joint-probe` was a throwaway project stamped beside it with `steward new`, initialised
with `git init` on `dev`, given a synthetic north star, and closed at REQ-001 with
`steward checkpoint`. Its sessions were attended sessions the owner opened there. It was erased
afterwards.

| # | Who | What happened | Verdict |
|---|---|---|---|
| 1 | devsteward | `joint-send --to joint-probe --need "Add a HELLO.md that greets DevSteward"` opened `devsteward-add-hello-md`. From inside the probe, `joint-list` showed it as waiting and as a request to take up, without being told where devsteward lives. | as designed |
| 2 | probe `/intake` | Asked to "take up the other project's request", it listed the candidate. It filed it with `backlog-add --handle devsteward-add-hello-md --origin proposed`, acknowledged `devsteward#1` and read the reasoning through `joint-show`. Then it applied §2d: the need names a mechanism. It offered the owner either taking it as is or asking devsteward, and asked for item criteria. | as designed; the strictness is §2d doing its job |
| 3 | probe `/intake` | On the owner's choice it sent `joint-probe#2`, one `ask` covering the purpose and the criteria, and paused. | as designed |
| 4 | devsteward | Answered with `devsteward#2`, a `tell` replying to `#2`. The `ask` stopped waiting on devsteward's side. | as designed |
| 5 | probe `/intake` | Told only "continue", **the paused session found the answer itself**. It filed the three criteria word for word, acknowledged `devsteward#2` 37 s after it was sent, and wrote REQ-002. | as designed; no skill change |
| 6 | probe `/advance` | Built HELLO.md and landed REQ-002 through its own checkpoint (`126d636`). **Unprompted**, it sent `joint-probe#4` (a `tell` with the commit SHAs) and `joint-probe#5` (`done`). | as designed; no skill change |
| 7 | devsteward | `joint-show` gave the take-up as "attempted — taken up by REQ-002 (done)". devsteward acknowledged `#4` and sent `done` replying to `#5`. Both projects' `joint-list` then said "no open joint threads", `joint-show` said *closed*, and a further send was refused. | as designed |

**Fixed in place.** The `/advance` look-up first sat after the "no develop step eligible →
surface and stop" rule, so a project with nothing to develop would never have read its
messages. Walking the probe script showed this before the first probe session ran. The look-up
now runs right after `steward status`.

**Observed, not changed.**
- The probe's last two lines (`#4`, `#5`) were written after its checkpoint commit, so its
  `joint.jsonl` was left uncommitted. This is Decision 9: the verbs do not commit, and the next
  commit carries the log. The peer reads the working tree, so nothing was delayed. The commit of
  such a trailing write is the same need as backlog item `backlog-commit-ui-changes`.
- A fresh stamp cannot land REQ-001 until `verify.python` names an interpreter that has pytest.
  That is REQ-099's subject, not this REQ's.

devsteward's own half of the thread was discarded before the REQ-101 checkpoint, at the owner's
choice: the thread is synthetic and its peer no longer exists. This table is the record.
