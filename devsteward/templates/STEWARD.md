# STEWARD.md — the `steward` manual for agents

You are an agent driving this project's work through **DevSteward**. This file is your
**complete operating manual** for the `steward` command. Treat DevSteward as a black box: the
`steward` CLI and this document are the whole interface. **Do not read the DevSteward package
source** to figure out how to use it or how to recover from a state — everything you need is
here. Reading `cli.py` or the engine internals couples you to private structure and resurrects
dead, pre-pivot behaviour; if something seems missing from this manual, say so rather than
reverse-engineering the engine.

## The model in one breath

A **REQ** (`REQ-NNN.md` in the requirements dir) is a spec with a machine-readable acceptance
block. Where the documents live is per-project: `requirements_dir`, `index_file`, `plans_dir`,
`concepts_dir` and `backlog_file` in `.devsteward/config.yaml` — read them before writing
anything. Their defaults are `docs/requirements/`, `docs/plans/`, `docs/concepts/` and
`docs/BACKLOG.md`, but a project whose `docs/` is owned by a docs generator keeps them elsewhere.
The **ledger** (`.devsteward/`) is the cursor: where work is and what happened. You do the
thinking; **the engine verifies and commits** — it runs the acceptance tests itself and only
marks a step `done` when they pass. You never write `status: done` and you never hand-edit the
ledger. All work lands on **`dev`** (trunk-based, linear history): no feature branches, no
worktrees, no branch switching. `main` is production (release tags only); the one branch
operation is the human-gated `dev → main` PR.

Each active REQ derives **one fused `develop` step** (plan → code → acceptance tests in one
session). A REQ whose acceptance has an `artifact` or `manual` criterion also gets a
**`validate` step** (the System-Test phase) between `develop` and the land.

## Orienting — always start here

```sh
steward status      # the cursor, eligible/blocked steps, parked decisions — the ONE read of the ledger
steward lint        # schema-valid REQs, deps resolve, index↔REQ in sync, every AC has a test id
steward sync        # refresh the engine-owned stamped artifacts after an engine upgrade
```

`steward status` is the sanctioned way to see the ledger. Do not hand-read `.devsteward/state.yaml`.

**The engine-owned artifacts are not yours to edit.** This manual, the bundled skills under
`.claude/skills/`, and the REQ template at `<requirements_dir>/_templates/req.md` are *stamped*
from the engine and must track it. The engine upgrades independently of your copies, so
`steward status` reports any that have drifted and `steward sync` refreshes them (a *stale* or
*missing* artifact is refreshed to byte-match the installed engine; `--force` also refreshes a
locally *edited* one, backing yours up to `<name>.orig` first). Editing one of these files in
your project marks it **customized**, and `sync` then refuses to refresh it — stranding you on a
private fork of the manual while the engine moves on. If something here is wrong or missing, say
so; do not fix it locally.

## The normal forward path

```sh
/intake "<idea>"          # interview a raw idea into a schema-valid draft REQ (a skill)
steward activate REQ-NNN  # flip a draft (or dropped) REQ to open so it becomes eligible
/advance                  # do ONE develop checkpoint: plan + code + acceptance tests
steward checkpoint        # close it: the engine re-runs the tests and lands on green (one transaction)
```

- **`/advance`** (a skill) does exactly one fused develop checkpoint and stops. In a live
  session it asks you at forks. It leaves the working tree dirty for the engine — it does **not**
  commit. **The one grant is attended (REQ-089):** an interactive session whose work needs a
  round-trip through external infrastructure — pushing so CI builds an image, a deploy to a
  remote host, live data from a running system — may make plain `git` commits and push
  mid-phase, as often as the iteration needs. A **batch** (`DEVSTEWARD_UNATTENDED=1`) session
  never commits; the engine is the committer there. `steward checkpoint` is never a mid-phase
  verb — the one-checkpoint frame bounds the bookkeeping, not the round-trips.
- **`steward checkpoint [REQ-NNN develop]`** is the interactive close. It re-runs the named
  acceptance tests through the land-grade gate, checks a file in the plans dir names the REQ, and on
  green makes the one authoritative commit (frontmatter + index + code) and advances the ledger —
  all on `dev`. **On red nothing lands**: fix the cause and re-run `checkpoint`. The gate cannot
  be talked into green; certification is the engine's, never yours to assert.
- **`steward gate [REQ-NNN] [PHASE]`** shows you that verdict *without* closing anything
  (REQ-089). It runs the step's named acceptance tests exactly as the develop gate will and prints
  each failure, and it is strictly **read-only** — no commit, no ledger write, no staging, nothing
  added to the index. Use it to see where you stand mid-development. It is the *verify* gate only,
  so a green `gate` is not a promise that `checkpoint` will land: the land also runs the capture
  check and the artifact gates.

Plan-first is enforced: the land **refuses** unless a file in the plans dir names the REQ id.
Concept-first is enforced the same way for a REQ that declared `process.concept: true`: the land
also **refuses** unless a concept deliverable — `<concepts_dir>/REQ-NNN.md` **or** a non-empty
`<concepts_dir>/REQ-NNN/` bundle directory — exists and the REQ's `concept_refs:` names it (the flat
file or a path inside the directory). The bundle form is for a concept phase that keeps a committed
prototype as its deliverable, not only a throwaway spike.

**The concept phase is where you earn the ACs you can't yet write** (REQ-071): set
`process.concept: true` when the acceptance criteria **cannot be honestly written at intake** —
the attended session derives them from the analysis or prototype (the functional spec, where
solution knowledge legitimately enters). An **empirical** concept phase — one whose deliverable is
frozen live data or a committed prototype the session must gather from the real world —
legitimately **iterates**: it may commit, push, and deploy repeatedly on `dev` to produce its own
inputs. **`steward checkpoint` is the terminal act**, run once the deliverable is frozen; over an
already-clean tree it simply records the step (an effectively no-op commit). And the phase model
is decided at intake: when the target ACs depend on the concept deliverable, the post-freeze work
needs a declared home — `develop: split` (a post-freeze develop phase authors the target ACs) or
a **named downstream REQ** — and the upstream REQ must **never carry the downstream REQ's
acceptance bar**.

## The backlog — user needs above the REQ

A **backlog item** is a user need **in the user's words** — the stakeholder-level requirement a
REQ is *translated from*. It sits one level above the REQ and answers a different question: a REQ
asks *did we build what was specified*, an item asks *was what we specified worth building*.

```sh
steward backlog-add "<the need, in the owner's words>"   # the cheap way in: no interview, no id
steward backlog-list                                     # every item, its derived state, its attempts
steward backlog-accept HANDLE                            # the owner: this satisfies the need
steward backlog-deny HANDLE --reason "<why not>"         # the owner: it does not
steward backlog-hold HANDLE --reason "<what it waits on>"
steward backlog-retire HANDLE --reason "<why dropped>"
```

- **Run `steward backlog-list` at the start of every `/intake`.** If the project keeps a backlog,
  the intake probably starts from an item. A project with no backlog file simply reports so — that
  is a valid state, not a missing artifact, and `backlog-add` creates the file when one is wanted.
- **Take-up is recorded in the REQ's `backlog_refs:` frontmatter, and nowhere else.** That list is
  the **only** stored record. There is no status column in the backlog file and no "taken up by"
  column — `backlog-list` *derives* each item's state from `backlog_refs` across the corpus plus
  the append-only verdict log, so there is no second copy to fall out of step.
- **The item's acceptance is never the REQ's gate.** The owner's verdict is **advisory to the REQ
  and blocking to the item**: a `backlog-deny` does *not* fail the REQ — the REQ closes on its
  verification result — it leaves the item open, with the attempt on record, for another REQ to
  take up. So never turn an item's acceptance criterion into a `manual` AC: that would let the
  owner's opinion block a build that met its specification.
- **Author an item's acceptance criteria before translating it,** in the owner's language. Criteria
  written after the solution is known get quietly bent to fit it — which is the exact failure this
  layer exists to prevent, one level up.
- **A need that names a mechanism is not a need.** If an item says *how* rather than *what*, say so
  and ask what it is for. Record anything you proposed yourself with `--origin proposed`, and only
  when the owner chose it from alternatives.

## The batch lane (headless queues)

```sh
steward advance     # one develop checkpoint, headless
steward run         # march every eligible step headless; park on forks, stop on a hard failure / usage limit
```

In batch the engine drives `claude -p`, re-runs the tests itself, lands on green (repairing up to
twice on red, then parking), and advances. There is no human channel, so a fork is **parked**, not
asked. A REQ that needs a human (e.g. `develop: split`) is parked naming the attended need.

## The System-Test phase (`validate`)

If a REQ declares an `artifact` or `manual` acceptance criterion, the green develop gate only
**commits** the work on `dev` (it does not land yet) and a `REQ-NNN:validate` step follows.

```sh
steward validate REQ-NNN           # shape A: the whole step from a plain shell
steward validate-start REQ-NNN     # warm cycle: open the step (works inside a session)
steward validate-record REQ-NNN    # warm cycle: grade + verdict, from a plain shell
```

- A fresh System Tester session (it never sees your diff) brings the lab up and captures
  artifacts; the **engine** runs each `artifact` test itself and consumes only pass/fail.
- A `manual` criterion takes a **human sign-off**. Run `steward validate REQ-NNN` from a plain
  terminal (not from inside a Claude session) — it walks the human through the procedure and
  records the verdict.
- On green, the same mechanical land fires (flip + index + ledger, on `dev`). A green validate on
  an already-`done` REQ just appends a fresh evidence event.

**The warm cycle (REQ-081) — a red does not cost the session.** The two halves of the same
flow are separate verbs, so a validation can run inside an already-warm session: `steward
validate-start REQ-NNN` opens the step and prints the evidence dir (it spawns nothing, so it
is callable from inside a Claude session); the session does the guided work and captures; then
the human runs `steward validate-record REQ-NNN` from a **second plain shell** — the engine
grades the capture and takes the verdict through its own interactive prompt (a Claude session
can never host or relay it). On a red, run `steward rework`/`steward revalidate` and the repair
from that same shell while the validation session stays warm and **idle** (one session writes
at a time); once the step is PENDING again, the warm session re-runs `start` — scoped to the
red ACs (see red-only revalidation below).

**The engine hands each `artifact` grading test its evidence dir.** When the engine runs an
`artifact` AC's test command it sets **`DEVSTEWARD_EVIDENCE_DIR`** in that command's environment
to the current run's evidence dir (an absolute path), **overriding** any inherited value. This is
the supported way for a grading test to find the artifacts the System Tester captured — read it
from the environment; never rely on an `export` left by a capture step (a stale one is overridden,
per run, so it cannot leak into a later grade).

**Red-only revalidation.** `steward revalidate REQ-NNN` re-opens **only the ACs that were red**
in the last validation; the green one-offs (a passed `artifact` capture, a recorded `manual`
sign-off) are **carried forward** into the new run's evidence dir with provenance — not
re-performed. The System Tester's prompt names only the scoped ACs (`--ac …`). If every AC was
red (or there were no per-AC results), it degrades to a full re-run. A carried AC whose source
files are missing is a hard red, never a silent pass.

## Acceptance lanes — how the engine runs your tests (REQ-068)

The **engine** decides how each acceptance test runs — which lane, which flavor. You declare the
lane with the per-criterion `check:` field; you never decide it with a marker string or how you
typed the command. The four lanes:

| `check:` | scope / oracle | when it runs | in the develop gate? |
|----------|----------------|--------------|----------------------|
| `regression` | module, coupled | every gate (hermetic) | yes — named test + in the full suite |
| `live` | system, decoupled | every gate (**standing**) | yes — named test (a **standing** integration proof) |
| `artifact` | system, decoupled, durable | **once**, in `validate` | no — a one-time validation |
| `manual` | system, human | **once**, in `validate` | no — a one-time validation |

- **The develop gate routes by `check:`, deterministically.** It runs this REQ's `regression` +
  `live` lane tests as named tests, runs the hermetic full suite, and **deselects every
  `artifact`/`manual` node-id project-wide** from that suite — so a **one-time** validation of an
  already-done REQ never gates a later REQ's develop. You never hand-edit a `-m "not live"`
  marker; the engine derives the exclusion from frontmatter.
- **Fail-hard on a missing declared resource.** A `live` (or any named-lane) test that reports
  **skipped** in the develop gate is a **hard red** — the engine knows it must run, so a skip is
  not tolerated. (An *unknown* test that skips in the full suite is still tolerated.) A red
  withholds the land without destroying the work commit.
- **Your declared environment travels.** On green the land self-checks that the recorded commit
  reproduces its own green from a clean tree extract — and that check runs in your **declared
  environment**: the env-file (`verify.env_file` in `.devsteward/config.yaml`, default `.env`)
  is copied into the ephemeral extract when present, and `os.environ` is inherited. A green that
  legitimately reads a gitignored `.env` certifies with no shell exports. No env-file declared
  or present means the bare, hermetic check, unchanged. If certification is withheld anyway, the
  message names the **preserved** work commit; the cause is a source/test file the commit can't
  hold **or** a runtime environment the check lacked — fix it (never commit a secret), then
  `steward repeat REQ-NNN`.
- **One flavor.** Every pytest acceptance command runs as `python -m pytest` under one
  engine-resolved interpreter; a leading bare `pytest …` is normalized to
  `<interpreter> -m pytest …` (repo root importable). A test never runs in a different flavor
  depending on how you typed it.
- **Degrade is reclassification, not a verb.** When a newer live proof subsumes an older one, flip
  the older AC's `check:` from `live → artifact`: it leaves the standing develop gate, stays
  re-runnable via `steward revalidate`, and you record the superseding test/REQ in the AC text or
  Notes. There is no `steward degrade`.

## Authoring doctrine (REQ-071)

Two rules for writing acceptance criteria that cannot go green while the feature stays dead:

- **Wire through the live entrypoint.** A *system-scoped* acceptance criterion must exercise the
  feature through its **real running entrypoint** (the cadence / scheduler, the served surface) —
  a feature that is present and unit-tested but **unwired** *fails* the criterion. **Tests
  passing ≠ wired**: "the unit is correct" and "the system invokes the unit" are different claims.
- **Don't scope a known defect out.** A known defect is either fixed in the current REQ or homed
  in a **named follow-on REQ** — never silently deferred. Genuine non-goals may be listed
  out-of-scope; known *defects* may not.

## Recovery — getting out of every red or parked state

Pick the verb by **what is actually stuck**. None of these touch a `done` REQ (supersede instead;
`done` is never weakened) and none switch branches.

| State you see in `steward status` | What it means | The verb |
|---|---|---|
| A step is **FAILED** (a develop step errored or the gate stayed red) | The attempt left partial edits in the tree | `steward repeat REQ-NNN` |
| **D/H** — a develop step ineligible (e.g. no plan artifact, or split/attended need) | **Not a decision.** A mechanical go-fix-and-retry stop | fix the cause, then `steward repeat REQ-NNN` |
| A parked **decision** on a `develop` step (a genuine fork) | The session hit a choice it couldn't resolve — the autopilot raised the captain | `steward decide DEC-NNN` (guided, from a plain shell) |
| A **`manual`-AC** validate hold (state F): "awaits its human oracle" | Async QA — a human must sign off | `steward validate REQ-NNN` (**not** `decision-answer`) |
| A **red validation** (the lab found a defect, or the validation test is wrong) | A human question — no auto-repair loop | `steward rework` or `steward revalidate` (below) |
| A **`validate` step FAILED by a land-gate refusal** (a missing plan/concept doc, after a *green* validation) | The formality is missing; the sign-offs are already durable | `steward reland REQ-NNN` |
| A **`done` REQ still surfacing a parked `:validate` decision** | A diverged ledger — the land already happened; the cursor was rewound behind it | `steward validate REQ-NNN` (reconciles it from the event log; **never** hand-edit `state.yaml`) |

- **`steward repeat REQ-NNN`** — the re-run verb (REQ-054, renamed from `recover`). The common
  failure is transient (a flaky env, an account swap), so the honest action is to repeat the step:
  it flips the FAILED step back to eligible, then `steward run` / `steward checkpoint` re-attempts
  against the partial tree the failed attempt left. It succeeds regardless of which branch is
  checked out (single ledger). Use it for any FAILED step **and** for a D/H mechanical stop once
  you've fixed the cause (e.g. added the missing plan file).
- **`steward decide DEC-NNN`** — the guided resolution of a **genuine fork** parked from a
  develop step (REQ-074). From a plain shell (never inside a Claude session) it brings up a
  session that briefs you on the fork (question, context, options, the parked session's
  recommendation) and supports live interrogation; after it exits, the **engine** records your
  choice + rationale, unblocks the step, and delivers the decision into the resuming session's
  prompt. `steward decision-answer DEC-NNN "<answer>"` remains as the non-guided plumbing; both
  refuse on a legacy validation hold and redirect you to the right verb — heed that.
- **`steward rework REQ-NNN`** — the return edge when a **red validation is a real defect**: it
  sends the validate step back to develop (`develop → recover`, `validate → pending`) so you fix
  the cause and re-validate. Reads the red evidence dir as your repair context.
- **`steward revalidate REQ-NNN`** — the validate-layer mirror: when the develop work **stands**
  and an external lab/setup issue was fixed, re-run the validation only (`develop` stays `done`).
- **`steward reland REQ-NNN`** — the cheap edge when the *validation was green* and only the land
  formality failed (no plan file, no concept deliverable). The sign-offs are durable in the green
  validation event, so once you fix the formality `reland` re-certifies that same green and lands —
  no re-prompting, no re-run, no paid session. Narrow preconditions: `REQ-NNN:validate` is FAILED
  and its last events are a green validation followed by a `land_refused`. For a *red* validation
  use `revalidate`; for a develop step use `repeat`.

`steward decision-list` shows parked forks with their briefs (question, context, options,
recommendation). Validation and attended waits are **holds**, not decisions (REQ-074): they never
appear in that list — `steward status` shows each hold with the verb that resolves it.

## Command reference

Every verb the `steward` CLI ships, and **who runs it**. Not all of them are yours: some are the
operator's, one belongs to a skill you will not have, and one must never be run from inside a
session at all. They are all listed anyway — knowing that a verb exists and is not yours is
information; a gap in this table is not.

Arguments are shown in the middle column. Flags are not: `steward <verb> --help` is the
authoritative flag reference and cannot drift.

### Orienting

| Verb | What it does | Run by / when |
|---|---|---|
| `steward status` | The ledger cursor, eligible and blocked steps, parked decisions, and any stamped-artifact drift. The one sanctioned read of the ledger. | You — first thing in every session, and again after every state change. |
| `steward lint` | Schema-validates every REQ, resolves `depends_on`, checks the index ↔ frontmatter pair is in lockstep, requires a test id on every AC. | You — after any edit to a REQ or the index. It must be green before a close. |
| `steward sync` | Refreshes stale or missing engine-owned stamped artifacts (the bundled skills, this manual, `<requirements_dir>/_templates/req.md`) to byte-match the installed engine. `--force` also replaces a locally edited one, backing yours up to `<name>.orig`. | The operator, or you when asked — after an engine upgrade, or when `status` reports drift. |
| `steward sync-skills` | Back-compat alias of `sync`, kept so older stamped copies and runbooks that name it keep working. Identical behaviour. | Nobody, in new work — prefer `sync`. |

### The forward path

| Verb | What it does | Run by / when |
|---|---|---|
| `steward activate` | `activate REQ-NNN` — flips a `draft` (or `dropped`) REQ to `open` so its develop step becomes eligible, syncing the index row. Leaves the change uncommitted. | You — right after `/intake`, before the first `/advance`. |
| `steward gate` | `gate [REQ-NNN] [PHASE]` — previews a step's acceptance verdict and prints each failure. Strictly read-only: no commit, no ledger write, no staging. | You — mid-development, as often as you like. It changes nothing. |
| `steward checkpoint` | `checkpoint [REQ-NNN PHASE]` — the interactive close. Re-runs the acceptance tests through the land-grade gate, checks the plan artifact, makes the one authoritative commit (frontmatter + index + code) and advances the ledger. | You — once, as the **terminal** act of an attended step. Never mid-phase. |

### The batch lane

| Verb | What it does | Run by / when |
|---|---|---|
| `steward advance` | `advance [REQ-NNN]` — one develop checkpoint headless, then the fixed report. | The operator, from a plain shell. It spawns `claude -p`, so it refuses to run from inside a Claude session. |
| `steward run` | `run [REQ-NNN]` — marches every eligible step headless; parks on forks, stops on a hard failure or a usage limit. | The operator, from a plain shell — same nesting rule as `advance`. |

### The System-Test phase

| Verb | What it does | Run by / when |
|---|---|---|
| `steward validate` | `validate REQ-NNN` — the whole phase from one command: spawns the fresh System Tester, grades the captures, takes any human sign-off, lands on green. | The operator, from a plain terminal. It spawns a session, so it refuses inside one. |
| `steward validate-start` | `validate-start REQ-NNN` — warm cycle: opens the validate step and prints the evidence dir. Spawns nothing. | You — this is the half that *is* callable from inside a warm session. |
| `steward validate-record` | `validate-record REQ-NNN` — warm cycle: grades the capture and takes the human verdict through its own prompt. | The operator, from a **second plain shell**, while the validation session stays warm and idle. A session can never host or relay that prompt. |

### Recovery

| Verb | What it does | Run by / when |
|---|---|---|
| `steward repeat` | `repeat REQ-NNN` — re-arms a FAILED step so the next run re-attempts it, with the failed attempt's partial work left intact in the tree. | You or the operator — on any FAILED step, and after fixing a D/H mechanical stop. |
| `steward rework` | `rework REQ-NNN` — returns a red validation to develop (`develop → recover`, `validate → pending`) for a fix-and-revalidate cycle, carrying the green ACs forward. | The operator — when the red validation found a real defect. |
| `steward revalidate` | `revalidate REQ-NNN` — re-runs only the ACs that were red; green one-offs are carried forward with provenance. `develop` stays `done`. | The operator — when the develop work stands and an external lab or setup cause was fixed. |
| `steward reland` | `reland REQ-NNN` — replays the mechanical land after a land-gate *refusal*, re-certifying the durable green validation without re-prompting or re-running it. | The operator — only when `REQ-NNN:validate` is FAILED with a green validation followed by a `land_refused`. |
| `steward decide` | `decide DECISION_ID` — guided resolution of a parked fork: briefs you on the question, context, options and the parked session's recommendation, and supports live interrogation before the engine records your choice. | The operator, from a plain shell. It spawns a session, so never from inside one. |
| `steward decision-list` | Shows the forks parked while running unattended, each with its brief. Holds (a validation wait, an attended need) never appear here. | You or the operator — any time. |
| `steward decision-answer` | `decision-answer DECISION_ID ANSWER` — the non-guided plumbing: records an answer against a parked fork and unblocks its step. | The operator — when the answer is already settled and no guided session is wanted. |

### The backlog

| Verb | What it does | Run by / when |
|---|---|---|
| `steward backlog-add` | `backlog-add "<need>"` — records a user need in the owner's words. Creates the backlog file from the bundled template when the project has none. | The owner's words; you type them. Never invent a need — record one you proposed with `--origin proposed`, and only when the owner chose it. |
| `steward backlog-list` | Every item with its **derived** state and attempt record. Nothing is stored: state comes from `backlog_refs` plus the append-only verdict log. | You — at the start of every `/intake`. |
| `steward backlog-accept` | `backlog-accept HANDLE` — the owner's verdict that a delivered result satisfies the need. | The **owner**, any time after the REQ lands — the honest answer to "is this actually usable" often arrives only after living with it. |
| `steward backlog-deny` | `backlog-deny HANDLE --reason "<why>"` — the owner's verdict that it does not. The reason is mandatory. | The **owner**. It is advisory to the REQ and blocking to the item: it never fails the REQ. |
| `steward backlog-hold` | `backlog-hold HANDLE --reason "<what it waits on>"` — the need stands but is deliberately not being worked. Taking it up in a REQ lifts the hold. | The **owner**. |
| `steward backlog-retire` | `backlog-retire HANDLE --reason "<why>"` — the need is no longer wanted. Nothing is deleted; the item and its reason stay readable. | The **owner** — the only way an item leaves the backlog unsatisfied. |

### Project setup

| Verb | What it does | Run by / when |
|---|---|---|
| `steward new` | `new TARGET` — stamps the bundled scaffolding (the skills, this manual, the REQ template, the docs layout, a seed backlog) into a new project at TARGET. | The operator, from outside the project — once. There is no agent in a project that does not exist yet. |
| `steward init` | Initializes a ledger in the current directory without stamping any templates. | The operator — once, in an existing directory being brought under the engine. |
| `steward seed-ledger` | Marks every terminal REQ's phase-step(s) done, seeding a ledger for a corpus that was built before the engine arrived. | The `/onboard` skill, during a migration. That skill is operator-only and is never stamped into a consumer, so you will not have it. |
| `steward cache` | Reports how long ago this project's newest Claude session transcript was written and whether the prompt cache is still warm (exit 0 warm, 1 cold, 2 none). | A **second shell** — never from inside a session. Measuring the session's cache warmth from inside that session warms the very thing it reports on, so the reading is worthless. |

## Hard rules

- **Never** write `status: done` in a REQ, and **never** hand-edit `.devsteward/state.yaml` — the
  engine owns both. Faking green is the false-done hole the gate exists to close. If a `done` REQ
  still surfaces a parked `:validate` decision (a diverged ledger), the sanctioned exit is `steward
  validate REQ-NNN`, which reconciles it from the event log — not a hand-edit.
- **Never** create, switch, or merge a branch to do REQ work. Everything is on `dev`.
- **Never** run two engine sessions against one repo at the same time — interactive or headless,
  in any combination (REQ-079). The engine's commit stages the **whole dirty tree**: everything
  dirty when a step lands is treated as that step's work, by design (it is how a `steward repeat`
  resumes a failed attempt's files). A parallel session's edits would be swept into the other
  REQ's commit, its ledger writes race, and the results are undefined. One session at a time is
  doctrine, not something the engine locks or detects — finish (or park) one before starting the
  next.
- **Never** hand-edit an engine-owned stamped artifact — this manual, the bundled skills under
  `.claude/skills/`, or `<requirements_dir>/_templates/req.md`. They are stamped from the engine
  and must track it; editing one marks it **customized** and `steward sync` will then refuse to
  refresh it, stranding the project on a private fork while the engine moves on. If something here
  is wrong or missing, **say so** — that is the fix, not a local edit.
- **Never** read the DevSteward engine source to operate it. This manual is the contract; the
  `steward` CLI is the API.
- Move a REQ's frontmatter, its `REQUIREMENTS_INDEX.md` row, and the code that satisfies it in the
  **same commit** (the engine does this for you on a checkpoint).
