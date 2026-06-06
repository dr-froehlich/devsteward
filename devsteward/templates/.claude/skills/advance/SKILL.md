---
name: advance
description: Do exactly one checkpoint of the current requirement — Design, Build, or Land — orienting from the DevSteward ledger. Use when the user says "advance", "next checkpoint", "work the next step", or when invoked headless by `steward run`/`steward advance`. Stops at forks; runs acceptance tests at Land.
---

# /advance — one checkpoint of the requirement workflow

You do **exactly one** checkpoint and stop. The cycle per requirement is
**A · Design → B · Build → C · Land**. The engine, not you, owns verification and the
ledger cursor — your job is the cognitive work of the one checkpoint in focus.

## 1. Orient (always)

- Read `.devsteward/state.yaml` for the cursor (`cursor.step`, e.g. `REQ-007:build`) and
  step statuses. If invoked as `/advance REQ-NNN <phase>`, that is your target.
- Read the target REQ, `CLAUDE.md`, and anything the REQ's `depends_on` produced.
- Identify which phase you are in from the step id suffix.

## 2. Do the one checkpoint

**A · Design** — turn the REQ into a concrete approach: data shapes, interfaces, the
files you'll touch, the tests you'll write. Capture it in `docs/plans/` if non-trivial.
Promote the REQ `status: draft → open`/`in-progress` if appropriate. No production code
yet.

**B · Build** — implement the design. Write the code **and** the acceptance tests named
in the REQ's `yaml acceptance` block, so they exist and can run at Land. Match the
surrounding code's style. English-only code; isolate any localized UI strings.

**C · Land** — make every acceptance test green, update the REQ's `status: done`,
`completed:` date, and `verified_by:`, sync its `REQUIREMENTS_INDEX.md` row, and ensure
`steward lint` is green. The engine re-runs the named tests independently before it
marks the step done — do not fake green.

## 3. Stop at forks (park-and-surface)

If you hit a real decision you can't resolve from the REQ + repo:

- **Interactive:** ask via `AskUserQuestion`, then continue.
- **Unattended (`DEVSTEWARD_UNATTENDED=1`):** append a record to `.devsteward/state.yaml`
  under `decisions:` (`{id, step, question, status: open}`) and **stop**. Do not guess.
  The engine surfaces it and advances to the next independent step.

## 4. Close

Commit your work (same-commit discipline: frontmatter + index + code together), branch
first, co-author trailer. End with the fixed report:

```
Did:       <what this checkpoint produced>
Cursor:    <new ledger position>
Review:    <one line: what to look at>
Decisions: <parked forks, or "none">
Next:      <the next eligible step>
```
