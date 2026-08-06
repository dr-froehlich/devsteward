---
name: advance
description: Do exactly one checkpoint of the current requirement — the fused Develop checkpoint — orienting from the DevSteward ledger. Use when the user says "advance", "next checkpoint", "work the next step", or when invoked headless by `steward run`/`steward advance`. Stops at forks; the engine runs acceptance tests and lands on green.
---

# /advance — one checkpoint of the requirement workflow

You do **exactly one** checkpoint and stop. After REQ-029 the cycle per requirement is a
single fused **Develop** checkpoint: plan-first, then the code, then the acceptance tests,
all in one session. On green the engine **lands the REQ mechanically** (status flip, index
sync, commit — all on `dev`) — you never write `status: done` and the land spends no
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

- Run **`steward status`** for the cursor (`cursor.step`, e.g. `REQ-007:develop`) and step
  statuses — never hand-read `.devsteward/state.yaml`. `steward status` is the one sanctioned
  read of the live ledger (there is a single ledger on `dev`). If invoked as
  `/advance REQ-NNN develop`, that is your target.
- **Choosing the target when none is named (interactive) (REQ-078).** Batch is always
  launched with an explicit `REQ-NNN develop` target — this whole bullet is *interactive-only*
  and does not touch the batch path. When a person runs `/advance` with **no** `REQ-NNN develop`
  argument:
  - **In-context, then ask (Decision 1).** If a REQ is fresh in the session context (e.g. one
    you just `/intake`-d this session), **ask** via `AskUserQuestion` whether to advance *that*
    REQ's develop step. On decline — or when nothing is in context — auto-select the next
    eligible step. The just-intook REQ is almost always what the operator means; asking removes
    the cursor-roulette that otherwise lands on an unrelated pending step.
  - **Skip validations when auto-selecting (Decision 2).** Auto-selection **skips any eligible
    `validate`/System-Test step** and advances the next **develop**-eligible step instead.
    `/advance` is the fused-develop skill; a validate step is `/system-test`'s job, run only via
    `steward validate REQ-NNN` in a plain shell — never adopted as an `/advance` target.
  - **No develop step eligible → surface and stop (Decision 3).** If nothing but validations is
    pending, **do not run one in-session** (the guided validate path refuses inside a live
    Claude/CLAUDECODE session by design). Surface the pending validation(s) with the exact
    `steward validate REQ-NNN` shell command and **stop** — the one honest terminal state
    (mirrors `steward run`'s caught-up report). `/advance` never runs a validation session.
- Read the target REQ, `CLAUDE.md`, and anything the REQ's `depends_on` produced.
- **Recovery (`--repeat` in your command):** if the step command includes `--repeat`,
  you are *resuming* a step that previously failed — its partial edits are already in the
  working tree (the failed attempt left them; the engine only commits on success). Read and
  assess what is there first: reconcile or fix the prior work, don't start clean.
  - **Rework (a `rework` event for your step):** if the ledger's latest event for this
    develop step is `rework`, a red System-Test validation was returned to you for a fix
    (`steward rework`, REQ-033). The event names the red validation's `evidence` dir — read
    it (the System Tester's `SYSTEM-TEST-FINDINGS.md`, the captured logs/artifacts) as your
    repair context: the lab found a real defect (or the validation test itself is wrong).
    Fix the cause on `dev` so the next validation passes; the findings travel
    through the ledger, never on the command line.
- **Repair (`--repair` in your command):** a previous develop attempt left the acceptance
  gate **red**. Your prompt carries the failure brief (the failed test ids + verifier
  detail). Assess the partial work already in the tree, diagnose the named failures, and fix
  the cause so the acceptance tests pass. This is a fresh session — there is no prior
  context beyond the brief and the tree.

## 2. Do the one Develop checkpoint

The fused **Develop** checkpoint, in order, in one session:

- **Concept first, if declared (REQ-039/067).** If the REQ set `process.concept: true`, this
  attended develop session *is* its concept phase: do the architecture / risk buy-down /
  spike work first and capture the conclusion (chosen design path, rejected alternatives,
  spike findings) in a **concept deliverable** — a flat `<concepts_dir>/REQ-NNN.md` or a
  `<concepts_dir>/REQ-NNN/` bundle directory — referenced from the REQ's `concept_refs:`.
  The land **refuses** unless that deliverable exists and `concept_refs:` names it. A
  design-only spike stays throwaway (capture the doc, discard the prototype code) — but an
  **empirical** concept deliverable, a committed frozen prototype (REQ-067) or frozen live
  data the session must gather from the real world, is a different workflow: **iterate
  until it is frozen**, on the general rule below. Then write the implementation plan
  *against* the approved concept. (REQs without the flag skip this.)
- **Iterate when the work needs the real world (REQ-089).** Some work cannot be produced or
  proven inside the session at all: it needs a **round-trip through external infrastructure**
  — pushing so CI builds an image, deploying to a remote host, gathering live data from a
  running system. That work legitimately **commits, pushes and deploys repeatedly on `dev`**
  while you iterate, because a push is the *precondition for the code existing anywhere it
  can be run*. This is a property of the work, not of a flag: an empirical `concept: true`
  phase is one instance, deploy-shaped develop work is another, and the next one will not be
  on any list. The rule is the principle — **the one-checkpoint frame bounds the
  *bookkeeping*, not the round-trips** — and it is keyed on **attended** (see §4 for who may
  commit and how). **`steward checkpoint` is the terminal act**, run once when the work is
  done; it is sanctioned over an already-clean tree and records the step over an effectively
  no-op commit.
- **A proof that needs a deploy belongs in *this* session (REQ-089).** If proving the REQ
  requires the code running on the real target, perform that proof here, attended, and fix
  what it finds **in place** — iterating as above. Do **not** defer it to the System-Test
  phase: the System Tester runs in a fresh session that never sees the diff and cannot fix
  anything (REQ-030), so a deploy proof routed there has **no repair loop** and every red
  bounces back as rework a whole session later. Keep a synthetic-fixture `regression`
  alongside to prove the mechanism disconfirmably in the gate.
- **Plan first.** Turn the REQ into a concrete approach and capture it in the project's
  **plans dir** — `plans_dir` in `.devsteward/config.yaml`, default `docs/plans/` (data
  shapes, interfaces, the files you'll touch, the tests you'll write). The plan artifact is
  **required**: the engine refuses to land a REQ when no file there names its id. Same for
  the concepts dir (`concepts_dir`) above; read the config before writing either. Promote the REQ `status: draft → open`/`in-progress` if appropriate.
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
    **`steward gate [REQ-NNN] [PHASE]`** shows you that verdict *without* closing anything
    (REQ-089): it runs the step's named acceptance tests exactly as the develop gate will and
    prints each failure, and it is strictly read-only — no commit, no event, no ledger write,
    no staging. It is the *verify* gate only, so a green `gate` is not a promise that
    `checkpoint` will land (the land also runs REQ-063's capture check and the artifact
    gates). Use it to see where you stand mid-development; use `checkpoint` to close.

## 3. At a fork (a decision you can't resolve from the REQ + repo)

- *(interactive)* ask via `AskUserQuestion`, then continue. Nothing re-checks this for you —
  you and the human own the answer. **Put all context inside the question** (2026-07-17
  marker test): text emitted after a tool result and followed by another tool call is never
  rendered, so an explanation written between the previous result and the question is lost —
  embed what the human must read in the `question` field / option descriptions / previews,
  or end the turn with the explanation as final text and ask in plain prose.
- *(batch, `DEVSTEWARD_UNATTENDED=1`)* park the fork **with a brief** (REQ-074) and **stop**.
  Do not guess. Append a record to `.devsteward/state.yaml` under `decisions:` —
  `{id, step, question, status: open}` plus the brief fields: `context` (what you tried and
  what hangs on the choice), `options` (each candidate with its consequence), and
  `recommendation` (your pick, with why). The operator resolves the fork in a guided
  `steward decide DEC-NNN` session and their choice is delivered into the resuming session's
  prompt — a bare question with no brief leaves them deciding blind. The engine surfaces the
  park and advances to the next independent step.
  Alternatively emit the park sentinel in your output: the line
  `[[DEVSTEWARD_PARK]] <question>` followed (before the next blank line) by context lines,
  `- <option>` lines, and a `recommendation: <text>` line — the engine parses the same brief.
- **Honor a delivered decision.** If your prompt carries "A fork parked on this step was
  decided by the operator", that fork is settled — build on the recorded choice; do not
  re-open it or re-park the same question.

## 4. Close

End with the fixed report (below) **after** handling the land per your mode:

- *(interactive)* run **`steward checkpoint REQ-NNN develop`** (with no arguments it targets
  the current cursor step) — all on `dev`. It is the
  engine's bookkeeping as one transaction: it re-runs the acceptance tests, checks the plan
  artifact exists, flips the REQ + index to `done`, makes the one authoritative code commit
  (frontmatter + index + code together, co-author trailer), advances the ledger, and commits
  the trailing ledger write as a follow-up on `dev` (the checkpoint event records `driver:
  interactive`). On red nothing lands — fix and re-run `steward checkpoint`; no `repeat` needed
  (that verb re-arms a *FAILED* batch step; a red interactive `checkpoint` left no failed step). Do **not** commit
  separately and do **not** hand-edit `state.yaml` — `checkpoint` is the committer (committing
  first would double-commit; editing the ledger by hand is what let it drift out of sync with
  a committed `done`).
- **Mid-phase commits — the attended grant (REQ-089).** *(interactive only)* When the work
  needs a **round-trip through external infrastructure** to be produced or proven — pushing
  so CI builds an image, a deploy to a remote host, live data from a running system (§2) —
  you **may commit and push mid-phase**, as often as the iteration needs. The mechanism is
  **plain `git` commits by the session**; `steward checkpoint` is *never* a mid-phase verb
  and stays the terminal act that closes the step. This is a **grant keyed on attended**, not
  an exception on a list: a human is present, owns the consequences, and can repair in place.
  It is not a licence to skip anything — you still never write `status:`, never edit the
  `REQUIREMENTS_INDEX.md` row, the engine still owns the flip, and the terminal `checkpoint`
  still re-runs the acceptance tests through the land-grade gate and refuses to land on red.
  Outside that trigger there is no reason to commit before the close, and `checkpoint` is the
  committer. (`steward gate` previews the verdict without committing anything — see §2.)
- *(batch)* do **not** commit (and never create a branch). Leave the working tree dirty; the
  engine verifies, lands the REQ (flip + index + commit, on `dev`), and advances the ledger.
  Committing here would *double-commit* — the engine commits too.
- **REQ with a System-Test phase (REQ-030):** if the REQ declares any `artifact` or
  `manual` acceptance criterion, the green develop gate **defers the land** — the close
  (either mode) only commits the work on `dev` (`develop_committed`); the flip and index
  sync fire after `REQ-NNN:validate` is green (`steward validate REQ-NNN`, or the batch
  loop). Say so under *Next:* in your report.

```
Did:       <what this checkpoint produced>
Cursor:    <new ledger position>
Review:    <one line: what to look at>
Decisions: <parked forks, or "none">
Next:      <the next eligible step>
```
