---
name: advance
description: Do exactly one checkpoint of the current requirement — the fused Develop checkpoint — orienting from the DevSteward ledger. Use when the user says "advance", "next checkpoint", "work the next step", or when invoked headless by `steward run`/`steward advance`. Stops at forks; the engine runs acceptance tests and lands on green.
---

# /advance — one checkpoint of the requirement workflow

You do **exactly one** checkpoint and stop. After REQ-029 the cycle per requirement is a
single fused **Develop** checkpoint: plan-first, then the code, then the acceptance tests,
all in one session. On green the engine **lands the REQ mechanically** (status flip, index
sync, commit, `--no-ff` merge) — you never write `status: done` and the land spends no
Claude tokens. **The engine is the verifying bookkeeper in both modes** — the same gate,
the same land, whoever drives. Your job is the cognitive work of the one checkpoint; what
varies by mode is who invokes the bookkeeper and what happens at a fork.

## 0. Which mode are you in? (decide first)

`/advance` is one skill run two ways. The switch is the `DEVSTEWARD_UNATTENDED`
environment variable.

- **Batch (engine-driven)** — `DEVSTEWARD_UNATTENDED=1` is set. You were launched headless
  by `steward advance` / `steward run` via `claude -p`; **there is no human in the loop.**
  The executor re-runs the acceptance tests itself, lands the REQ on green, and advances
  the ledger. You do the thinking, leave the working tree dirty for the engine, and
  **park** any fork (you cannot ask). Do **not** commit and do **not** branch.
- **Interactive (human-driven)** — `DEVSTEWARD_UNATTENDED` is unset. A person ran `/advance`
  in a live session — the **default driving mode**. The engine's guarantees still apply:
  you close via **`steward checkpoint`**, which re-runs the acceptance tests through the
  same land-grade gate as batch and lands only on green (the gate cannot be talked into
  green — certification is the engine's, never yours to assert). At a fork you **ask** —
  the live interview is what this mode buys.

Everything tagged *(batch)* or *(interactive)* below applies to that mode only.

## 1. Orient (always)

- Read `.devsteward/state.yaml` for the cursor (`cursor.step`, e.g. `REQ-007:develop`) and
  step statuses. If invoked as `/advance REQ-NNN develop`, that is your target.
- Read the target REQ, `CLAUDE.md`, and anything the REQ's `depends_on` produced.
- **Recovery (`--recover` in your command):** if the step command includes `--recover`,
  you are *resuming* a step that previously failed — its partial edits are already in the
  working tree (the failed attempt left them; the engine only commits on success). Read and
  assess what is there first: reconcile or fix the prior work, don't start clean.
- **Repair (`--repair` in your command):** a previous develop attempt left the acceptance
  gate **red**. Your prompt carries the failure brief (the failed test ids + verifier
  detail). Assess the partial work already in the tree, diagnose the named failures, and fix
  the cause so the acceptance tests pass. This is a fresh session — there is no prior
  context beyond the brief and the tree.

## 2. Do the one Develop checkpoint

The fused **Develop** checkpoint, in order, in one session:

- **Plan first.** Turn the REQ into a concrete approach and capture it in `docs/plans/`
  (data shapes, interfaces, the files you'll touch, the tests you'll write). The plan
  artifact is **required**: the engine refuses to land a REQ when no file in `docs/plans/`
  names its id. Promote the REQ `status: draft → open`/`in-progress` if appropriate.
- **Build.** Implement the approach. Write the code **and** the acceptance tests named in
  the REQ's `yaml acceptance` block, so they exist and the engine can run them. Match the
  surrounding code's style. English-only code; isolate any localized UI strings.
- **Make it green.** Ensure the named acceptance tests and `steward lint` pass for real.
  **Do not touch `status:` and do not edit the `REQUIREMENTS_INDEX.md` row** — the engine
  owns the flip to `done` and writes it (frontmatter + index, in lockstep) only *after* the
  acceptance tests pass. Writing `done` yourself before verification is the false-done hole.
  - *(batch)* the engine re-runs the named tests independently, then lands the REQ inside
    the one checkpoint commit — do not fake green.
  - *(interactive)* `steward checkpoint` (see Close) re-runs the tests independently and
    refuses to land on red — run them for real first so the close is one clean pass.

## 3. At a fork (a decision you can't resolve from the REQ + repo)

- *(interactive)* ask via `AskUserQuestion`, then continue. Nothing re-checks this for you —
  you and the human own the answer.
- *(batch, `DEVSTEWARD_UNATTENDED=1`)* append a record to `.devsteward/state.yaml` under
  `decisions:` (`{id, step, question, status: open}`) and **stop**. Do not guess. The engine
  surfaces it and advances to the next independent step; `steward decision answer` unblocks it.

## 4. Close

End with the fixed report (below) **after** handling the land per your mode:

- *(interactive)* branch first (no engine branch-guard runs in your client), then run
  **`steward checkpoint REQ-NNN develop`** (with no arguments it targets the current
  cursor step). It is the engine's bookkeeping as one transaction: it re-runs the
  acceptance tests, checks the plan artifact exists, flips the REQ + index to `done`,
  makes the one authoritative commit (frontmatter + index + code together, co-author
  trailer), advances the ledger, commits the trailing ledger write as a follow-up, and
  merges the feature branch `--no-ff` into the integration branch (the checkpoint event
  records `driver: interactive`). On red nothing lands — fix and re-run; no `recover`
  needed. Do **not** commit separately and do **not** hand-edit `state.yaml` —
  `checkpoint` is the committer (committing first would double-commit; editing the
  ledger by hand is what let it drift out of sync with a committed `done`).
- *(batch)* do **not** commit and do **not** branch. Leave the working tree dirty; the engine
  verifies, lands the REQ (flip + index + commit + `--no-ff` merge), and advances the ledger.
  Committing here would *double-commit* — the engine commits too.

```
Did:       <what this checkpoint produced>
Cursor:    <new ledger position>
Review:    <one line: what to look at>
Decisions: <parked forks, or "none">
Next:      <the next eligible step>
```
