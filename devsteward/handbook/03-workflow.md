# 03 · The REQ workflow

The shipped profile turns every active requirement into a single develop checkpoint and
sequences requirements by their dependencies.

## One develop step per requirement (REQ-029)

For each active REQ (`open` / `in-progress` / `blocked`) the REQ profile derives **one**
step:

| Step | What happens | Verified? |
|------|--------------|-----------|
| `REQ-NNN:develop` | Plan-first → implement → write & green the acceptance tests | **yes** |

`develop` is the single Claude session — the fused successor to the old `design → build →
land` triple (which paid three cold sessions where two verified nothing). It carries the
REQ's acceptance `test:` commands as its verification, so the engine re-runs them before
marking the requirement done.

On a **green** develop gate the engine performs the **mechanical land** itself — status
flip, index sync, the single commit, the `--no-ff` merge, ledger advance — with **no
Claude** (and it refuses unless a file in `docs/plans/` names the REQ). On a **red** gate it
spawns up to **two** fresh repair sessions (failure brief, default Sonnet), then parks. A
REQ that declared `develop: split` or `concept: true` is parked in batch, naming the
attended need, rather than driven headless. (See 02 · engine for the gate's teeth.)

## The V-model mapping: `check:` steers the phases

Each acceptance criterion's `check:` classification (see 01 · format) is a **routing
key** that maps it onto the V-model:

| `check:` | V-model side | Phase | Oracle |
|----------|--------------|-------|--------|
| `regression` | verification (left) | **Build** (inside `develop`) | coupled / mock, headless |
| `artifact` | validation (right) | **System-Test** | decoupled, durable (lab-produced; engine reads only the pass/fail signal) |
| `manual` | validation (right) | **System-Test** | human — a decision stop |

The phase names here are V-model *stages*, not step ids: the `develop` step does the
Build-side **verification** of every `regression` criterion (that is its gate). The
classification steers **phase existence**: a REQ with only `regression` criteria
runs no System-Test phase; any `artifact` *or* `manual` criterion makes the System-Test
(validation) phase apply. A human review *is* validation — system-level by definition —
which is why `manual` lives inside the System-Test phase rather than as a stray
module-level stop.

## The System-Test phase (REQ-030)

A REQ that declares at least one `artifact` or `manual` criterion gets exactly one extra
step, **`REQ-NNN:validate`**, between develop and the mechanical land; a REQ with only
`regression` criteria gets none. The step order is **develop → validate → land**: the
green develop gate then only *commits* the work on the feature branch (a
`develop_committed` event — no status flip, no merge), and the land fires when validation
is green — `done` keeps meaning *verified and validated*, and dependents wait on the
dep's final step.

The phase decouples the oracle. It runs as a **fresh System Tester session**
(`/system-test`, model per `claude.steps.validate`, default Opus-high) that never sees
the builder's diff: it orients from the REQ, brings the lab up, drives the validation
procedure, and captures artifacts into `.devsteward/evidence/REQ-NNN/<timestamp>/`. Then
the **engine** runs each `artifact` criterion's named `test:` command itself — the same
skip-is-red / zero-collected-is-red teeth as the develop gate — and consumes only that
pass/fail signal; the session's report carries zero gate weight.

Validation is a **recorded evidence event**, not a regression-suite member: the
`validation` event in `events.jsonl` carries per-AC results, each artifact's relative
path + sha256, and any sign-offs; `verified_by` gets the engine-composed dated summary
(the human supplies only the verdict + an optional one-line scope). A lab skip or a
missing artifact is a hard red, never a pass.

Mechanics around the gate:

- **`manual` criteria are a decision stop.** Unattended, the step parks naming the
  pending human oracle; attended, `steward validate REQ-NNN` presents the criterion and
  records the sign-off (date, reviewer, scope) as the evidence event.
- **A red validation parks immediately — no repair loop.** A red here means the develop
  was hollow or the lab is broken; both are human questions, so the engine never auto-loops
  on red (REQ-030 Decision 8).
- **`steward rework REQ-NNN` is the return edge (REQ-033).** When the red is a real defect
  to fix — the lab found one, or the validation test itself is wrong — `rework` is the
  recorded human verdict: it flips `REQ-NNN:develop` back to `RECOVER` and
  `REQ-NNN:validate` to `PENDING`, answers the parked decision, and records a `rework`
  event naming the red evidence dir (the `/advance` repair session reads it as context).
  The fix runs on the *same* still-open req branch and re-validates through the unchanged
  land topology — one explicit verb per fix-and-revalidate cycle is the bound (it amends
  Decision 8 without repealing it). It refuses on a `done` REQ (supersede instead — done is
  never weakened) and touches no git and no REQ file. (`steward recover` is for a step that
  actually *failed*; a red validation leaves no failed step.)
- **Lab availability is an eligibility dependency.** While any `process.lab` REQ is not
  `done` the validate step is simply ineligible — `steward status` names the lab REQ
  being waited on; no red event, no parked decision.
- **`steward validate REQ-NNN` is the single entry point.** On an in-flight REQ it
  executes the pending validate step (green → the mechanical land + merge proceed); on a
  `done` REQ it appends a fresh evidence event without disturbing the status. At the
  release gate (`dev → main` PR) a human decides which `artifact` REQs to re-run — there
  is deliberately no auto-staleness detection.

## Labs — owned fixtures with reality-derived provenance

A **lab** is the decoupled oracle an `artifact` criterion runs against: an owned,
versioned fixture with documented provenance, built by its own REQ — never a double
authored in the same step as the code it certifies. The pattern (set by the first lab,
FlowSteward's IMAP lab):

- **Labs live in the consumer repo.** The consumer owns the domain, the test accounts,
  and the credentials; and `process.lab` references are **registry-local**, so only a
  lab REQ in the same registry can gate that repo's validate steps. DevSteward documents
  the pattern; it does not ship domain fixtures.
- **Prefer real systems over doubles.** A lab that targets a real server (a dedicated
  test account, never production) over a live socket has the strongest provenance there
  is. Containerized doubles are a fallback, not the default.
- **Self-contained and dependency-free.** A lab tool shares no code with the package it
  validates (stdlib-only, invoked by path), so the oracle stays decoupled and any
  caller — including another repo's System Tester — can run it with its own interpreter.
- **Configuration is a hard failure, never a skip.** Credentials are injected via an
  env/path seam (no real paths or secrets committed); a lab that cannot come up exits
  non-zero. A skipping lab is the false-green hole labs exist to close.
- **The corpus is reality-derived and versioned.** Seed data is captured from real
  traffic and sanitized (provenance notes document source and transformations), with a
  manifest recording the golden expectation; version, manifest, and docs move together.

## Sequencing whole requirements

`REQ-B:develop` depends on `REQ-A:develop` for each `REQ-A` in `REQ-B.depends_on`. So a
requirement only starts once its prerequisites have fully landed, while **independent
requirements interleave freely**. A dependency that is already `done` is satisfied and
dropped; a dependency that is draft, dropped, or missing leaves the dependent correctly
blocked (and `steward lint` flags it).

## Branching model

DevSteward uses a two-line model. `main` is **production** — release tags are cut here and
consumers pin them. `dev` is the **integration** branch: the default working and merge
target. **Declaration lives on `dev`; only implementation branches** — intake (REQ
frontmatter, index row, roadmap), plans, and the ledger are committed directly on `dev` (a
requirement is a registry entry, not behavior; forking the shared registry races id
allocation and conflicts the index/roadmap), while **implementation** (code + acceptance
tests + the status-flip to `done`) goes on a feature branch and merges into `dev` by a plain
local merge (no PR). `dev` is promoted to `main` via a PR.

This is **engine-enforced**, not just convention: before any step runs, the executor checks
the current branch, and if it is the production branch it **refuses** — it invokes no
`claude`, commits nothing, leaves the step pending, and prints a guard message naming the
branch and the fix. Off the production branch it proceeds normally. The branch names are
configurable in `.devsteward/config.yaml`:

```yaml
git:
  production_branch: main          # repos using `master`/`release` set it here
  integration_branch: dev
  feature_branch: req-{num}-{slug} # name for an auto-managed implementation branch
```

The production guard has no opt-out — strictness is the point — and it never opens PRs
(`dev → main` stays a human PR).

**The executor manages the implementation feature branch** (it no longer merely refuses to
implement on the integration branch). When a `develop` step is eligible on the integration
branch it lazily **creates and switches** to `feature_branch` (`{num}` is the REQ id without
the `REQ-` prefix; `{slug}` a short slug of the title) and runs the step there; a partial
prior run's branch is **reused** (a *diverged* one is surfaced, not merged over). After a
**green develop** the mechanical land commits the trailing ledger write, switches back, and
merges `--no-ff` with the co-author trailer — leaving the integration branch clean at rest.
A failed or parked develop does **not** merge: the feature branch stays checked out for
inspection. Declaration (intake, plans, the ledger) is no longer a step — it is committed
directly on the integration branch — so the automation only ever branches the one
implementation phase.

## Two drivers, one bookkeeper

`/advance` is one skill run two ways. The **engine is the verifying bookkeeper in both** —
the REQ-028 gate, the mechanical land, and the merge are identical whoever drove the
cognition (the `checkpoint` event records which: `driver: interactive` or `headless`).
What differs is only the driver and what happens at a fork. The switch is the
`DEVSTEWARD_UNATTENDED` environment variable, which the engine sets when it shells out.

- **Interactive — `/advance` in a live session, closed by `steward checkpoint`.** The
  **default driving mode** for a single developer. A person runs the skill directly in
  Claude Code; at a fork it asks via `AskUserQuestion` and continues — the interview
  stays live. The session does the cognition and leaves the tree dirty; the close is
  **`steward checkpoint`**, which re-runs the named acceptance tests through the same
  land-grade gate as batch and, on green, performs the same mechanical bookkeeping —
  status flip, index sync, the one authoritative commit, ledger advance, the trailing
  ledger follow-up, and the `--no-ff` merge back into the integration branch. On red
  nothing lands: the red verify event and the `FAILED` step are the honest trail; fix and
  re-run (no `recover` needed). The gate cannot be talked into green — that property does
  not depend on who drove.
- **Batch lane — `steward advance` / `steward run`.** The overnight lane for queues of
  **well-specified, low-fork REQs**. Both drive `claude -p` headless
  (`DEVSTEWARD_UNATTENDED=1`); there is no human channel, so a fork is never asked — it is
  **parked** and surfaced. The engine re-runs the acceptance tests itself, lands the REQ
  mechanically on green (repairing up to twice on red, then parking), and advances the
  ledger. `steward advance` does one checkpoint; `steward run` marches every eligible
  step, parking on forks and stopping on a usage limit or hard failure so a human can look.

**One commit, one owner.** The engine commits in both modes — the skill never does. In
batch the executor makes the checkpoint commit; interactively `steward checkpoint` makes
it. (Earlier the skill committed its own work, which double-committed under the engine and
left the interactive ledger to a hand-edit; both holes are closed by the shared tail.)

## The fixed report

Every checkpoint ends the same way, so orientation is instant:

```
Did:       what this checkpoint produced
Cursor:    new ledger position
Review:    one line — what to look at
Decisions: parked forks, or "none"
Next:      the next eligible step
```

## A day in the life

```sh
steward status                       # where are we?
/intake "let users export to CSV"    # interview → draft REQ-014
steward lint                         # green?
/advance                             # interactive: plan + code + tests, asking at forks
steward checkpoint REQ-014           # engine verifies, lands, merges — one transaction
# or, the batch lane for a queue of well-specified REQs:
steward run                          # march everything eligible; park on forks
steward decision list                # anything parked?
steward decision answer DEC-001 "use RFC 4180 quoting"
steward run                          # resume
```
