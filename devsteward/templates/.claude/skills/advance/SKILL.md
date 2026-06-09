---
name: advance
description: Do exactly one checkpoint of the current requirement — Design, Build, or Land — orienting from the DevSteward ledger. Use when the user says "advance", "next checkpoint", "work the next step", or when invoked headless by `steward run`/`steward advance`. Stops at forks; runs acceptance tests at Land.
---

# /advance — one checkpoint of the requirement workflow

You do **exactly one** checkpoint and stop. The cycle per requirement is
**A · Design → B · Build → C · Land**. Your job is the cognitive work of the one checkpoint
in focus — but *who verifies it and who commits it* depends on **which mode you are in**.

## 0. Which mode are you in? (decide first)

`/advance` is one skill run two ways, with different contracts. The switch is the
`DEVSTEWARD_UNATTENDED` environment variable.

- **Batch (engine-driven)** — `DEVSTEWARD_UNATTENDED=1` is set. You were launched headless
  by `steward advance` / `steward run` via `claude -p`; **there is no human in the loop.**
  The engine owns the guarantees: it re-runs the acceptance tests itself, makes the single
  commit, and advances the ledger. You do the thinking, leave the working tree dirty for the
  engine, and **park** any fork (you cannot ask). Do **not** commit and do **not** branch.
- **Interactive (human-driven)** — `DEVSTEWARD_UNATTENDED` is unset. A person ran `/advance`
  in a live session. **There is no engine in the loop, and therefore no engine guarantees.**
  You verify your own work, you commit it, and at a fork you **ask**. The human reviewing
  the work is the guarantee.

Everything tagged *(batch)* or *(interactive)* below applies to that mode only.

## 1. Orient (always)

- Read `.devsteward/state.yaml` for the cursor (`cursor.step`, e.g. `REQ-007:build`) and
  step statuses. If invoked as `/advance REQ-NNN <phase>`, that is your target.
- Read the target REQ, `CLAUDE.md`, and anything the REQ's `depends_on` produced.
- Identify which phase you are in from the step id suffix.
- **Recovery (`--recover` in your command):** if the step command includes `--recover`,
  you are *resuming* a step that previously failed — its partial edits are already in the
  working tree (the failed attempt left them; the engine only commits on success). Read and
  assess what is there first: reconcile or fix the prior work, don't start clean or blindly
  redo it.

## 2. Do the one checkpoint

**A · Design** — turn the REQ into a concrete approach: data shapes, interfaces, the
files you'll touch, the tests you'll write. Capture it in `docs/plans/` if non-trivial.
Promote the REQ `status: draft → open`/`in-progress` if appropriate. No production code
yet.

**B · Build** — implement the design. Write the code **and** the acceptance tests named
in the REQ's `yaml acceptance` block, so they exist and can run at Land. Match the
surrounding code's style. English-only code; isolate any localized UI strings.

**C · Land** — make every acceptance test green and fill the REQ's `completed:` date and
`verified_by:`. **Do not touch `status:` and do not edit the `REQUIREMENTS_INDEX.md` row —
the engine owns the flip to `done`** and writes it (frontmatter + index, in lockstep) only
*after* the acceptance tests pass for real. Writing `done` yourself before verification is
the false-done hole: a failed land would leave a stray `done` in the working tree, which
makes the not-yet-landed REQ look finished. Ensure `steward lint` is green. Green must be
**real** either way:

- *(batch)* the engine re-runs the named tests independently, then flips the REQ + index to
  `done` inside the one checkpoint commit — do not fake green.
- *(interactive)* `steward checkpoint` (see Close) re-runs the tests and does the flip — you
  are attesting green to the human, so run them for real first.

## 3. At a fork (a decision you can't resolve from the REQ + repo)

- *(interactive)* ask via `AskUserQuestion`, then continue. Nothing re-checks this for you —
  you and the human own the answer.
- *(batch, `DEVSTEWARD_UNATTENDED=1`)* append a record to `.devsteward/state.yaml` under
  `decisions:` (`{id, step, question, status: open}`) and **stop**. Do not guess. The engine
  surfaces it and advances to the next independent step; `steward decision answer` unblocks it.

## 4. Close

End with the fixed report (below) **after** handling the commit per your mode:

- *(interactive)* branch first (no engine branch-guard runs in your client), then run
  **`steward checkpoint REQ-NNN <phase>`**. It is the engine's bookkeeping as one
  transaction: it re-runs the acceptance tests, flips the REQ + index to `done` (land only),
  makes the one authoritative commit (frontmatter + index + code together, co-author
  trailer), and advances the ledger so the cursor moves on. Do **not** commit separately and
  do **not** hand-edit `state.yaml` — `checkpoint` is the committer (committing first would
  double-commit; editing the ledger by hand is what let it drift out of sync with a committed
  `done`).
- *(batch)* do **not** commit and do **not** branch. Leave the working tree dirty; the engine
  verifies, flips the REQ + index to `done`, makes the one authoritative commit, and advances
  the ledger. Committing here would *double-commit* — the engine commits too.

```
Did:       <what this checkpoint produced>
Cursor:    <new ledger position>
Review:    <one line: what to look at>
Decisions: <parked forks, or "none">
Next:      <the next eligible step>
```
