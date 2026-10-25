# REQ-103 — A joint-task message rings a running session

Plan for `REQ-103:develop`. Requirement: `docs/requirements/REQ-103.md` (7 decisions, one
`manual` AC, no concept phase). No engine code changes (Decision 6).

## The shape of the change

| Piece | Where | What |
|---|---|---|
| the manual | `devsteward/templates/STEWARD.md` (the root `STEWARD.md` is a symlink) | A new bullet group in *Joint tasks*: the thread is the record, ringing after `joint-send`, answering a bell, the seam, the approval rule, a lost bell. The *Where sessions look* bullet changes to match Decision 3. The `joint-send` row in the verb table gets the ring in its *who* column. |
| the handbook | `devsteward/handbook/_01-format.qmd`, *Joint tasks* | One short paragraph: the bell, the seam, the approval rule. The "works through it at orientation" sentence also names the bell. |
| `/advance` | `.claude/skills/advance/SKILL.md` (inode-shared with its template) | The joint step: ring after each `joint-send`, and react to a bell the same way. Pointer to STEWARD.md. Batch ignores bells. |
| `/intake` | `.claude/skills/intake/SKILL.md` (inode-shared with its template) | The take-up step: the `ask` back to the requester is followed by a ring. Pointer to STEWARD.md. |

## The bell, as written

- After every `steward joint-send`, list the sessions running on this machine (Claude Code:
  `ListAgents`). Send each **interactive** session whose name starts with the addressee's
  folder name in lower case the single line `steward joint-show <handle>` (Claude Code:
  `SendMessage`). None running → ring nobody. Once, no retry, no waiting. No bell after
  `joint-ack`.
- A session that receives that line, attended, runs it and works what waits for its project in
  the thread with the owner, as `/advance`'s joint step does. Batch ignores it.
- The harness names appear once, in parentheses, as the current form of "the session list" and
  "a direct message". The rule is stated without them, so a harness change dates the
  parenthesis and not the rule (REQ-103 Risks).

## Verification

AC1 is `manual`: the owner reads the four files in `steward validate REQ-103` and confirms
(a)–(e). No fixture is needed: the validation reads committed files only (REQ-069 duty is
empty here). No standing test, because nothing executable changes. The existing suite must stay
green, including `tests/test_skills.py` (skills ↔ templates inode identity) and
`tests/test_steward_manual.py` (no verb is added).

## Live proof (develop obligation)

1. After the develop commit: `steward joint-send sysadmin-open-0201 --kind tell` naming the
   commit, then ring `system-admin-*` (interactive). The owner watches system-admin's session read
   the entry through the bell.
2. If system-admin answers and rings back, this session reacts to that bell.
3. The `done`s follow with the owner on each side.
