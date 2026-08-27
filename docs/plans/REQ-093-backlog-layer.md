# REQ-093 — a backlog of user needs above the REQ

Implementation plan for the stakeholder-requirement layer: capture, take-up at intake, and
an acceptance verdict that is advisory to the REQ and blocking to the item.

## Shape

One new profile-owned module plus small seams in existing ones. The content-aware backlog
stays out of `core/` entirely (Decision 5) — `core/` is the generic executor and must not
learn what a user need is.

```
devsteward/profiles/req/backlog.py   NEW — parse, splice, mint, events, derive
devsteward/config.py                 + backlog_file seam, backlog_path property
devsteward/profiles/req/reqfile.py   + backlog_refs property
devsteward/schema/req.schema.json    + backlog_refs (and the stamped copy)
devsteward/lint.py                   + check 8: backlog referential integrity
devsteward/cli.py                    + backlog-add/list/accept/deny/retire
devsteward/templates/docs/BACKLOG.md NEW — stamped scaffolding with the grammar documented
.claude/skills/intake/SKILL.md       + take-up step, criteria-before-translation rule
devsteward/handbook/_05-outlook.qmd  stage one is shipped, not outlook
tests/test_backlog.py                NEW — AC1..AC7
tests/test_req093_doctrine_surfaces.py NEW — AC8
tests/fixtures/drivesteward_backlog/ NEW — the real 16-item corpus (AC7)
```

## Data shapes

**The file** (`backlog_file`, default `docs/BACKLOG.md`) — a markdown table the engine
parses and splices, with all surrounding prose preserved byte-for-byte:

```markdown
| Handle | Need | Origin |
|---|---|---|
| rapid-verdict | In a few minutes … | operator |
```

`Origin` ∈ `operator | proposed`. There is no status column and no taken-up column.

**The event log** — `.devsteward/backlog.jsonl`, append-only, one JSON object per line:

```json
{"ts": "2026-08-27T10:00:00+00:00", "handle": "rapid-verdict",
 "event": "denied", "req": "REQ-019", "reason": "still needs two runs"}
```

`event` ∈ `accepted | denied | retired`. Take-up is **not** an event — it derives from
`backlog_refs:`, whose single writer is intake (Decision 6).

**Derived state**, computed per item from the REQ graph + the events, never stored:

| State | Rule |
|---|---|
| `open` | no REQ refs it, no verdict |
| `in-progress` | a referencing REQ is not terminal |
| `attempted` | every referencing REQ is terminal, no verdict |
| `accepted` | latest verdict `accepted` |
| `open (denied N×)` | latest verdict `denied` — still takeable |
| `retired` | latest verdict `retired` |

## Design decisions taken during build

**The sync seed is dropped; `backlog-add` creates the file instead.** The REQ as intook
said `steward sync` seeds a backlog into a project lacking one, on the REQ-086 precedent.
That precedent does not transfer: `_templates/req.md` is *referenced by a stamped skill*, so
its absence breaks `/intake`; a backlog's absence is a valid, meaningful state. Seeding via
`sync` would also silently give **devsteward itself** a backlog on the next sync, directly
contradicting the REQ's own "devsteward is such a project and stays one". So:

- `steward new` stamps `docs/BACKLOG.md` (a fresh project should see the option, and the
  stamped file documents the grammar);
- `steward backlog-add` creates the file from the same template when it is missing, and
  never overwrites an existing one — the capture verb is the right creator, since wanting to
  record a need is exactly the moment a project acquires a backlog;
- `steward sync` does not touch it. It is consumer *content*, not engine behaviour, so it
  never joins the tracked drift set (the same line REQ-036 Decision 1 draws for `CLAUDE.md`).

This is recorded as Decision 11 on the REQ and AC6 is restated against it.

## Order of work

1. `backlog.py` — parse / mint / splice / events / derive, with the corpus fixture driving
   the parser's tolerance for real prose.
2. `config.py` seam, `reqfile.backlog_refs`, both schema copies.
3. `lint.py` check 8, scoped to a present backlog file so absence stays green.
4. The five CLI verbs.
5. The stamped template.
6. `/intake` skill: the take-up step and the criteria-before-translation ordering rule
   (edit once — the repo skill and the template are one inode).
7. Handbook: stage one moves from outlook to shipped.
8. The DriveSteward retrofit, attended, fixable in place.

## Risks

- **Splicing a live file.** The parser must preserve every byte outside the table, including
  the notes prose DriveSteward keeps after it. Guarded by a byte-identical no-op rewrite
  assertion over the real corpus (AC7).
- **A second writer.** Only `backlog-add` writes the markdown; only the verdict verbs write
  the log; nothing writes status anywhere. Any future writer of a status field is the defect.
- **DriveSteward's tree is dirty** at plan time (an in-flight session's work on `docs/BACKLOG.md`
  among others). The retrofit must not sweep it — one session at a time (REQ-079). Confirm the
  tree is settled before touching that repo.
