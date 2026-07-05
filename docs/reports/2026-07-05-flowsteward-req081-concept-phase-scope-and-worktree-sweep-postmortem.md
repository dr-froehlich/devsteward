> **Provenance (2026-07-05, DevSteward intake):** copied verbatim from FlowSteward
> (`docs/postmortems/2026-07-05-req-081-concept-phase-scope-and-worktree-sweep.md`) per its own
> instruction — the implicated components are DevSteward's. Disposition decided with Peter at
> intake: recommendations **3 + 6** (iterative concept-phase workflow, phase-model guard at
> intake) are folded into **REQ-071** (amended this same commit); recommendation **4** is
> answered by observation (documented via REQ-071's STEWARD.md surface); recommendations
> **1 + 2** (REQ-scoped commit staging, run lock — the worktree-wide `git add -A` in
> `devsteward/core/git.py` / `core/executor.py`, no cross-process lock) are **deliberately
> unfiled** — Peter's call, this document is the record; recommendation **5**
> (deterministic privacy-ignore) is **out of scope** — consumer discipline, noted here only.

# Post-mortem — REQ-081: the concept phase doesn't fit the one-checkpoint model, and a concurrent engine run swept an interactive session's work

- **Date:** 2026-07-05
- **REQ:** REQ-081 — *Taxonomy mission T1 — read-only inventory & divergence across filesystem, IMAP, and Paperless*
- **Severity:** medium–high (process + engine) — no data loss and **no privacy breach**, but
  an interactive concept session was mis-framed by its own driving skill, its uncommitted work
  was swept into an unrelated commit by a concurrent engine run, and there is no sanctioned way
  to reconcile the resulting drift without engine-internal knowledge.
- **Author:** Peter (with Claude)
- **Components:** primarily the **DevSteward engine** and its **process documentation / skill
  scope** (`/advance`, `steward checkpoint`, the concept-phase model, the batch lane's autocommit
  and worktree concurrency). FlowSteward itself did nothing wrong — its tooling is green. Copy
  this into the engine repo (`/home/peter/projects/devsteward`) as that project's follow-up.

## One-line summary

REQ-081's develop phase is `concept: true`, and its concept deliverable is a **live, read-only
inventory of three production surfaces** (a fileserver over SSH, the synced IMAP store inside the
prod stack, and paperless-ngx over its API) plus a divergence report. Producing that deliverable is
inherently a **multi-commit, multi-deploy** effort — build tooling → commit → push → deploy to the
prod box → run the reader *inside the container* → capture → iterate — because the IMAP reader can
only run where the REQ-080-synced DB is (container-internal). But the `/advance` skill frames the
session as **"do exactly one checkpoint and stop; leave the tree dirty; the engine commits once and
lands on green."** That frame is wrong for this shape of work, there is no mid-phase commit/push
verb, and while the interactive session was still building, a **concurrent `steward validate` run
did a worktree-wide `git add` and swept the session's uncommitted files into a commit labelled for a
different REQ** (`ce1c9ef` "REQ-090:validate"). Same-commit discipline was silently violated and the
ledger drifted (`REQ-081:develop` still `pending` though its code is committed).

## What was supposed to happen

> An attended `/advance` on REQ-081 runs the concept phase: build the read-only tooling for all
> three surfaces, freeze the real cross-surface report as the concept deliverable, and close develop
> — which, because the REQ has `artifact`/`manual` ACs, only *commits* on `dev` and opens
> `REQ-081:validate`. The concept deliverable exists before the close.

## What actually happened

1. **The deliverable can't exist at "one checkpoint" time.** Two of three legs (filesystem,
   Paperless) were captured live and froze cleanly. The **third (IMAP) cannot run from the dev box
   at all** — the prod Postgres port is container-internal, and the just-written reader isn't in the
   deployed image. Getting that leg requires: commit the tooling → push `dev` → redeploy froehlix6 →
   `docker compose exec worker python -m flowsteward taxonomy imap`. That is several commits/pushes
   *before* anything is "mature" to checkpoint. The skill offers no verb for that; its whole contract
   is "leave it dirty, the engine commits once."

2. **A concurrent engine run swept the interactive session's files.** At 08:40:59 a background
   `steward validate` (REQ-090) committed `ce1c9ef` with a worktree-wide `git add`, pulling in **all**
   of this session's then-uncommitted REQ-081 files — the taxonomy package, tests, plan, README,
   `.gitignore`, `.env.example`, and the `REQ-081.md` `concept_refs` edit — under a commit message for
   **REQ-090:validate**. The two sessions shared one `dev` worktree with no lock.

3. **The result is unreconcilable from the black-box view.** `REQ-081:develop` is `pending
   (eligible)` yet its code is already committed. The sanctioned close, `steward checkpoint REQ-081
   develop`, would re-run the (green) gate and then try to make "the one authoritative commit" — but
   the tree is now **clean**, so that commit has nothing to stage. Whether the engine records
   `develop_committed` over an empty commit or errors is undocumented, and CLAUDE.md forbids reading
   the engine source to find out. There is no documented verb for "code landed outside the engine —
   record the step."

## Root causes

1. **Concept-phase scope is under-specified and the skill mis-seeds it.** `process.concept: true`
   with a *live-data* deliverable is a genuinely different workflow from a code-only develop step: it
   is iterative, it may deploy to production to gather its own inputs, and it produces its deliverable
   only after those round-trips. `/advance`'s "exactly one checkpoint, leave the tree dirty, the
   engine commits once" contract silently assumes a single local build. Nothing in the skill or
   STEWARD.md says "a concept phase may commit + push + deploy repeatedly; the checkpoint is the
   *terminal* act once the deliverable is frozen." The session was seeded to close, not to iterate.

2. **Engine autocommit is worktree-wide, not REQ-scoped.** A `git add -A`-style stage means the
   engine's commit for REQ-X will pick up **any** dirty file in the worktree, including a concurrent
   session's in-progress work for REQ-Y. The commit is not scoped to the REQ's declared/known paths,
   so same-commit discipline is only as good as "nobody else is editing."

3. **No concurrency guard on a shared worktree.** The batch lane and an interactive session ran
   against the same `dev` working tree simultaneously. The background lane "backing down" was assumed
   to be idle; it was mid-validate and committing. There is no lock, and no per-session worktree
   isolation, to prevent one run from committing another's files.

4. **No reconciliation path for "committed outside the engine."** The recovery table in STEWARD.md
   covers FAILED steps (`repeat`), red validations (`rework`/`revalidate`), and a diverged
   *validate* decision (`steward validate` reconciles from the event log). It does **not** cover a
   develop step whose code exists in a commit the engine didn't author.

5. **The intake mis-shaped the phase model — this is the deeper root cause (added 2026-07-05, 2nd
   session).** REQ-081 was authored `process.develop: fused` **with** `process.concept: true`. That
   pairing is a **contradiction the intake did not catch**: `concept` promises a two-phase
   *freeze-the-empirical-deliverable-then-build-against-it* shape, while `fused` collapses develop to
   a single checkpoint — so `concept: true` degraded into a **label with no phase gate** behind it.
   The REQ's own Context even names the trigger verbatim — *"the target-model decisions … cannot be
   interrogated out of anyone before the inventory exists"* — which in our doctrine
   ([[concept-phase-for-ui-empirical-unknowns]], [[prefer-detailed-req-over-split-review]]) is the
   textbook signal for `develop: split`, not `fused`. The consequence is exactly the seam confusion
   Peter hit: there was **no develop phase in which to iterate the analysis** ("run various flavors
   until all perspectives are extracted") and no point at which target-model ACs get authored against
   the frozen data. That work fell into the crack between a fused T1 and the downstream T2.
   Compounding it, **AC6 imported a T2-quality bar into a T1-scope REQ**: it asks the operator to
   certify the report is *"a sufficient basis to run the T2 curation session … residual usable"* —
   but 081's own Notes explicitly scope all modeling **out** to T2. So the acceptance bar and the
   declared scope disagree by construction. Empirically the raw report proves the point: **516 clean
   matches and 16 subtree templates are usable, but the near-miss residual is 94,752 records** (an
   O(n²) edit-distance sweep over ~10k terms with one loose global threshold and no blocking) and
   surface-unique is a flat 10,291-item list — i.e. raw material, categorically *not* the
   curation-ready artifact AC6's wording demands. A fused concept REQ carrying a downstream phase's
   acceptance bar is the trap; either shape is fine alone, the combination is the defect.

## Impact

- **Contained:** the personal data (the fs/IMAP/Paperless inventories and the derived report) was
  **never committed** — the REQ-081 `.gitignore` block landed in the same sweep, so the `*.jsonl` and
  `divergence-report.md` were already ignored. Privacy held. The tooling is green (AC1–AC3),
  `steward lint` OK. No work was lost.
- **Cost:** same-commit discipline broken (REQ-081 implementation mislabeled as REQ-090 validate);
  ledger drift (`REQ-081:develop` pending over committed code); an interactive session blocked on a
  reconciliation it cannot safely perform; operator (Peter) time spent standing down the background
  lane and diagnosing.

## What went right

- The privacy gitignore was authored **before** any commit could reach it, so the sweep could not
  capture personal data. This is the one guard that held, and it held by luck of ordering — worth
  making deterministic.
- The concurrent run *parked* its irreversible action (arming thirteen prod accounts + a real IMAP
  move) as a decision (DEC-048) instead of executing it, so standing it down cost nothing.

## Recommendations (for DevSteward)

1. **Scope the engine's commit to the REQ.** Stage only the REQ's known/declared paths (or a
   manifest), never a blanket `git add -A`. A concurrent session's files must be impossible to sweep.
2. **Isolate or lock per run.** Give each `steward` run (batch or interactive) its own git worktree,
   or take a worktree lock so two runs cannot commit the same tree concurrently.
3. **Make the concept phase a first-class iterative workflow.** Document (and, if needed, add verbs
   for) a concept phase that legitimately commits + pushes + deploys multiple times before the
   terminal checkpoint. Seed the `/advance`/concept session with *that* scope — "iterate until the
   deliverable is frozen; checkpoint is the last step" — not "one checkpoint and stop."
4. **Add a reconciliation verb for out-of-engine commits**, or document the exact behaviour of
   `steward checkpoint` over a clean tree, so a drifted develop step is recoverable without
   engine-internal knowledge.
5. **Make the privacy-ignore guarantee deterministic**, not order-dependent: a concept phase that
   captures personal data should declare its ignored output paths up front (in the REQ or config) so
   no commit can ever stage them regardless of timing.
6. **Guard the phase model at intake (the deepest fix).** `concept: true` + `develop: fused` should
   be a **lint error, or an intake question**: if a REQ is concept-gated because its target ACs are
   unknowable before the empirical deliverable exists, it must either (a) be `develop: split` — so a
   post-freeze develop phase iterates the analysis and authors the target-model ACs — or (b) push the
   modeling to a named downstream REQ **and not carry that REQ's acceptance bar** (no "sufficient
   basis for T2"-style manual AC on the upstream inventory step). REQ-081 did neither: fused, yet
   with a T2-quality AC6. The intake skill / lint should refuse or interrogate this combination.

## Current state (updated 2026-07-05, 2nd session — all legs in, develop closed)

- **All three legs captured and the report frozen.** IMAP leg run in-container on froehlix6 (clean
  exit, 1,331 folder records, all 13 accounts); analyzer joined fs + imap + paperless →
  `docs/concepts/REQ-081/{divergence-report.md, unified.jsonl, divergence.jsonl}` (all gitignored,
  privacy verified). Content: 516 matches, 94,752 near-miss, 10,291 surface-unique, 16 templates.
- **`REQ-081:develop` = done**, checkpointed `909059e6` (Peter). `REQ-081:validate` = `pending
  (eligible)`. Note: the checkpoint's worktree-wide `git add` **swept this postmortem** into the
  develop commit — root cause 2 recurred, reinforcing recommendation 1.
- `REQ-080:validate` = `blocked-on-decision` (DEC-048), untouched.
- **The engine mechanics closed the loophole this doc feared:** with the tree already clean (code
  swept into `ce1c9ef`), `steward checkpoint REQ-081 develop` recorded the step as done over an
  effectively no-op commit — so recommendation 4 ("document behaviour over a clean tree") is answered
  by observation: it does *not* error; it records done. Reconciliation was ultimately trivial.

## Decision taken (2026-07-05, 2nd session)

Rather than fail validation to retrofit a `develop: split` onto a green, honestly-scoped tooling REQ,
the modeling work moves **forward** to where it belongs: **REQ-081 is accepted as-is** (AC6 read at
the raw-basis level — the material for T2 is all present, T2 is not a blank page), and **T2 will be
authored `concept: true` + `develop: split`** — its concept phase *is* the analysis-flavor iteration
(collapse the 94k near-miss via blocking/bucketing, bucket surface-unique per realm, converge on
facets + per-subtree templates) yielding the shaped report + draft model; its develop phase authors
`taxonomy.yaml` + lint against ACs that are finally writable. This is the shape REQ-081's own rationale
called for (root cause 5) — applied where the modeling actually lives.
