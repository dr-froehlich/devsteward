# Roadmap

The dependency DAG over DevSteward's own requirements. The engine derives step
eligibility from `depends_on`; this is the human-readable view of the same graph.

## Now

- REQ-001 — north star (the compass)

## Done (the baseline vertical slice)

REQ-002 … REQ-009 — the format + linter, the executor core, the REQ profile,
park-and-surface, the verification gate, `steward new`, the account provider, and the
three bundled skills. Built and dogfooded in Phase 0/1.

## Repair (dogfooding surfaced these — the engine never drove a real claude)

- REQ-013 — **reality harness**: opt-in end-to-end gate that drives a real `claude -p`
  (**done**; first green 2026-06-08 — the standing trust gate)
- REQ-014 — headless `claude -p` runs with a permission mode so a real session can edit
  (**done**; the fix that turned the gate green on a single account)
- REQ-012 — real cswap 0.11 switcher CLI (draft; restores multi-account rotation)
- verify-teeth — forbid marker-trust on design/build, or require a runnable AC (planned)
- conceptual fork — make `advance`/`run` batch-only; separate interactive `/advance`
  (**REQ-018**: `steward checkpoint` closes the ledger after an interactive checkpoint)
- branching regime — declaration (intake/roadmap/plans/ledger) lives on `dev`; only
  implementation branches (**REQ-019**: extends the REQ-011 guard to refuse `build`/`land`
  on the integration branch — REQ-011's missing half)

## Repositioning (plan 0011 — the 2026-06-10 strategic assessment)

Interactive-first, one verified `develop` session, mechanical landings, independent
validation. Driven **interactively** (not by `steward run`) in this order — see
[plan 0011](../plans/0011-process-repositioning.md) and the
[assessment report](../reports/2026-06-10-strategic-assessment-process-and-token-economics.md):

1. REQ-027 — acceptance taxonomy + intake rewrite (amended: intake also records the
   fused-vs-split develop decision)
2. REQ-029 — **phase-model rework** (fleshed out 2026-06-10): one fused `develop` step;
   land becomes engine code on green (zero Claude tokens) and requires a `docs/plans/`
   file naming the REQ; bounded repair session (budget 2, Sonnet, fresh context +
   failure brief) on red; per-step model/effort config; split/concept REQs park in
   batch; old ledgers reinterpreted, never rewritten; e2e proof run is a `manual` AC
3. REQ-018 — **revised** (fleshed out 2026-06-10): `steward checkpoint` verifies with
   the REQ-028 gate and shares REQ-029's mechanical bookkeeping — the engine certifies
   in both modes. REQ-029 already shipped the command + tail + `/advance` close; this
   REQ adds the full topology close-out (trailing ledger commit + `--no-ff` merge via
   the REQ-020 routine), `driver: interactive|headless` provenance on the checkpoint
   event, the interactive-first handbook flip, dedicated tests, and a human-reviewed
   proof run (`manual` AC). Red records the failure but lands nothing; the dirty tree
   is the expected input (the engine is the committer). Lands before REQ-030 — the
   validate gate later reshapes both drivers through the shared `mechanical_land`
4. REQ-030 — **System-Test phase** (fleshed out 2026-06-10): conditional on
   `artifact|manual` ACs; one `validate` step between develop and the mechanical land
   (validation **gates** the land); fresh System Tester session preps the lab and
   captures artifacts, the **engine** runs the artifact test commands and consumes only
   the pass/fail signal; evidence = committed `.devsteward/evidence/` artifacts +
   hashed `events.jsonl` event + `verified_by`; `manual` = decision stop (replaces the
   D12 hand-flip); `process.lab` blocks eligibility like a dependency; red validation
   parks, no repair loop; `steward validate REQ-NNN` is the single entry point
   (first run + re-run); e2e proof is a `manual` AC
5. REQ-031 — **first lab, IMAP** (**done** 2026-06-11): the lab lives in its home repo
   (FlowSteward REQ-008, real mail server, reality-derived corpus); handbook documents
   the consumer-owned-lab pattern; first real evidence event + FlowSteward re-drive
   signed off
6. re-earn batch mode: one overnight `steward run` under the new model on FlowSteward,
   then postmortem — **gated on REQ-032**

## Next

- REQ-059 — **interrupted run self-heals a stranded RUNNING step** (draft): the 2026-06-20
  runtime stalemate. A `SIGINT` during a cswap quota-wait left `REQ-040:develop` stranded in
  `RUNNING` (the requeue only fires on an up-front `precheck` fail or a clean `USAGE_LIMIT`
  return, never on an interrupt of the blocking wait), and nothing reconciles it — the REQ
  wedged with no verb to recover, only a hand-edit of `state.yaml`. `only_ineligibility_reason`
  then misreported it as *"blocked on an unfinished dependency"* via an unconditional else. Fix:
  a **startup sweep** at `run`/`advance` requeues any `RUNNING` step (→ `PENDING`, or `RECOVER`
  to preserve the `--repeat` signal) and records an `interrupted` event, so the wedge self-heals
  on re-run — no new verb; plus the diagnosis branches on actual statuses and only claims a
  dependency block when a `depends_on` is genuinely not `done`. Regression-only; fused. With
  REQ-025, REQ-026, REQ-053.
- REQ-060 — **a caught-up project reports an honest terminal state** (draft): the clauder
  observation. The persisted cursor is *"last step touched, never reset"*, so when every REQ is
  done `steward status` prints `cursor: REQ-005:develop` (a done step it won't derive) above
  *"no active steps"*, and `checkpoint` refuses with an *"is it active?"* question instead of
  naming **done** — a cognitive dead-end with no "you're caught up, `/intake` the next" signal.
  Fix is display-only (cursor semantics untouched): show the cursor only while it names a
  derivable step, print a positive terminal line otherwise, and have `checkpoint` name *done* +
  supersede. Sibling of REQ-059, unrelated mechanism. Regression-only; fused. With REQ-018,
  REQ-047, REQ-056.
- REQ-061 — **re-wire the account pin** (draft, feature): REQ-058 delegated the budget gate to
  clauder and dropped the slot-pin (D5: *"revisit if slot-pinning is still wanted"*) on the bet
  that combined-budget selection supersedes it. It is wanted — the combined gate optimises the
  shared 5h pool but is blind to the accounts' 7d windows, which reset at different times; an
  about-to-reset account's unused 7d budget evaporates unless drained first. The `--use N` seam
  is still half-built: the flag parses and threads `use` to `build_accounts`, which silently
  drops it. clauder REQ-006 (**done**) added `clauder gate --pin N` (judge admission on N alone,
  no fallback); this REQ reconnects the dead seam, **hard-renaming** `--use` → `--pin` so the
  word agrees with clauder (whose `--use` is burn-percent). Operator supplies the index; no
  auto-selection (that re-opens REQ-058 D5 and the `clauder usage` 7d-reading REQ-058 deleted).
  Regression-only (argv assertion + CLI rename threading); fused, no lab. With REQ-058; clauder
  REQ-006 is an external PATH prerequisite, not an edge.
- REQ-044 — **`steward supersede`** (draft): codifies the 2026-06-16 REQ-034 hand-recovery.
  REQ-037's `try_merge_no_ff` aborts a feature→`dev` merge on a code conflict and tells the
  operator to *"resolve by hand: `git merge --no-ff`"* — which bakes in "an aborted merge
  means unlanded work." False for a **superseded** branch: REQ-034's branch held a stale
  parallel implementation already delivered on `dev` via REQ-037/041/043, so following that
  guidance would have spliced obsolete code back in and regressed `dev`. Adds a human-only
  `steward supersede REQ-NNN` verb (append `branch_superseded` to the integration-branch
  ledger capturing the abandoned unique-commit shas, delete the unmerged branch, clean tree —
  never merge), and makes the abort recovery instruction **name** it as the alternative to
  the hand-merge. Engine never auto-supersedes (the branch had *divergent*, not empty-delta,
  code — "obsolete vs unlanded" is a human judgment). Regression-only, real-git ACs; fused.
  With REQ-037, REQ-043.
- REQ-037 — **ledger on dev only + atomic topology** (draft): the root fix for the live
  crash where `steward validate` died on a `git merge --no-ff` conflict in `.devsteward/`
  and left the repo split (HEAD on `dev`, fix stranded on the feature branch, no verb to
  recover). The ledger rides the feature branch and the feature→`dev` merge collides two
  append-only histories the moment `dev` advanced since the cut (guaranteed in a
  deferred-validate world). Plan 0021 moved only the *park* path to `dev` and assumed "the
  green path is fine"; the crash disproves that. Moves **all** ledger writes to `dev` (the
  ledger has the declaration's nature — serial, single-writer, registry), so a feature
  branch carries pure code and the merge cannot conflict on `.devsteward/`; and wraps every
  merge/reconcile/switch to be **atomic + recoverable** (fetch-first, abort-and-surface,
  park when unattended) instead of crashing. Real-git ACs (the plan 0021 hollow-fake
  lesson). **Unblocks honestly re-validating REQ-034.** With REQ-020, REQ-032, REQ-034.
- REQ-038 — **cross-host validation deploy channel** (draft): Finding 90, the spun-out gap
  from REQ-034's live AC6 (FlowSteward REQ-024's homelab cutover). A `manual` AC whose
  surface is on another host has no sanctioned way to receive the build before land — the
  artifact lives only on the local feature branch, and the clean channel (`git pull` of a
  published ref) is a land-phase action that comes *after* validation. Resolves it with
  **artifact-export (option A)**: validate emits a clean RC (`git archive`, tracked files
  only) shipped cross-host as a thin one-commit repo; no ref hits `origin`. A live fix
  returns as a true `git diff` **patch** through the evidence dir and lands via the rework
  loop — full fidelity, deploy host never commits. Candidate frozen at the green verdict.
  Depends on REQ-037 (pure-code branch + atomic merges). With REQ-030, REQ-033, REQ-034.
- REQ-036 — **steward sync-skills** (draft): the spun-out fourth finding of REQ-034's live AC6
  (Finding 50). A consumer's stamped `.claude/skills/` is frozen at `steward new` time while the
  engine is upgraded independently, so they drift with no refresh path and no signal — and a
  stale stamped skill silently runs old behavior against a current engine (FlowSteward's
  pre-REQ-034 system-test skill made `--guided` a no-op). Adds a provenance manifest
  (`.devsteward/skills.lock`) so drift is tellable apart from intentional customization
  (in-sync / stale / customized), a non-blocking `steward status` signal, and a
  `steward sync-skills` verb that refreshes stale bundled skills (and won't clobber a
  customized one without `--force`). Bundled skills only; fused; consumer-repo reality (no
  DevSteward lab). With REQ-007 (stamping) + REQ-030 (bundled skills).
- REQ-035 — **done re-validation freezes verified_by** (draft, fix): re-validating a `done`
  REQ (`steward validate`, REQ-030 D5) silently overwrote its `verified_by`, clobbering the
  landing provenance (postmortem Finding 3). The fix leaves `verified_by` and `status`
  untouched on a done re-validation — the fresh re-check lives in the appended `events.jsonl`
  event (REQ-030 D3), which is already the durable record — and makes the CLI message honest.
  Clarifies REQ-030 D5; the in-flight landing write is unchanged. Regression-only, fused.
- REQ-034 — **guided async human validation** (draft): reworks the `manual`-AC half of the
  System-Test phase (**amends REQ-030 D4**). Human validation becomes a fresh, diff-free but
  **interactive** guided session (prepare the lab/surfaces + operator entrypoint, walk the
  procedure, answer questions) with the verdict engine-owned — not a bare `y/N`. A pending
  human validation parks as an **async QA-ticket** (clean tree, HEAD back on the integration
  branch, feature branch intact + unmerged) so a waiting human never freezes the pipeline,
  and `steward validate` **cleanly re-enters** a parked validation later by reconciling the
  branch from current `dev` (fixes postmortem Finding 1). Spawn isolated from any ambient
  Claude Code session (Finding 4); declined verdict routes to `steward rework`. From the
  2026-06-12 human-oracle postmortem.
- REQ-033 — **rework loop** (draft): `steward rework REQ-NNN` — the V-model's return edge.
  A red validation parks (REQ-030 D8 stands; the engine never auto-loops), but today no verb
  expresses the human's answer "the lab found a defect — fix and revalidate": `decision answer`
  only re-runs the same red validation, `recover` refuses (no FAILED step). Rework flips
  develop DONE→RECOVER and validate→PENDING, answers the parked fork, and hands the red
  evidence (findings, brief) to the resuming `/advance` session via a `rework` ledger event;
  fix happens on the still-open req branch, re-validation produces fresh evidence. First
  case: FlowSteward REQ-012's live IMAP red (MODSEQ tuple decode) — the manual proof AC.
- REQ-032 — **ledger always committed** (draft): every terminal step outcome — land+merge,
  deferred develop close, red validation, park — leaves a clean tree; the REQ-018
  `branch_merged` wart plus the two sibling leaks surfaced 2026-06-11. The explicit gate
  before the first multi-REQ batch night

- REQ-010 — **memzy frontmatter-dialect converter** (open; promoted — memzy is the first
  consumer to migrate; archivist conversion + active-only lint relaxation)
- REQ-017 — legacy-**prose** converter for ExamEngineer (draft; promote when its upscale
  evolution concludes — reuses REQ-010's core)
- REQ-020 — **branch lifecycle automation** (draft; eligible now): the executor auto-creates
  the feature branch on the first guarded `build` and auto-merges (`--no-ff`) after a green
  `land` — completes the create→merge dance REQ-019 left manual, replacing its refusal with
  management while the REQ-011 production guard stands
- REQ-021 — **lettered REQ ids** (draft; eligible now): relax the id format to
  `^REQ-[0-9]{3}[a-z]?$` so split-umbrella REQs like memzy's `REQ-028p`/`-028s` validate.
  Purely lexical; unblocks plan 0005 (memzy onboarding) Piece 1.
- REQ-022 — **`steward seed-ledger`** (draft): a dialect-independent command that seeds a
  ledger for an already-built corpus so historic REQs read as `done` and the work queue starts
  empty. Plan 0005 Piece 3; reusable across onboardings (operates on converted output only).
- REQ-023 — **converter index splice** (draft): make [[REQ-010]] conversion non-destructive in
  place — replace only the REQ table, preserve a project's Planned/Scenarios prose. Plan 0005
  Piece 2 mitigation; unblocks running the converter on memzy in place.
- REQ-024 — **`onboard` skill** (draft): orchestrate the full migration of an existing project
  (convert → seed → stamp → reconcile) with verification gates and merge-not-overwrite. Plan
  0005 pieces 2–5; memzy is the reality test before heavier projects.
- REQ-025 — **visible account rotation + fixed-quota gating + graceful stop** (draft;
  eligible now): port `Theresa/run_batch.py`'s proven machinery onto the engine seams —
  read cswap `usage.json` for 5h/7d %, gate at a fixed 70% (CLI/config overridable, no
  adaptive), prefer-current rotation with `--use` pin, interruptible wait through resets,
  visible utilization/switch lines, two-level Ctrl-C, `start_new_session=True` (no Ctrl-C
  to claude), and `--model`/`--effort` defaulting to Opus/high.
- REQ-026 — **lifecycle CLI** (draft; eligible now): three operator verbs the engine lacks —
  `steward activate REQ-NNN` (draft/dropped → open, syncing frontmatter + index), `steward
  recover REQ-NNN` (flip a FAILED step to a new ledger-level `RECOVER` status the existing
  `/advance` skill picks up and assesses; no repair skill), and `--only REQ-NNN` on
  `run`/`advance` to drive a single REQ full-circle, failing if it has no eligible step.
- REQ-027 — **acceptance test taxonomy, seeded by intake** (done 2026-06-10, plan 0011
  step 1; AC4 signed off on the REQ-029 intake run): the fix for nine
  green-but-hollow REQs (canonical: FlowSteward REQ-003 AC1, a mock discharging a system
  claim). Adds a required per-AC `check:` field (`regression | artifact | manual`) as a
  **routing key** that maps acceptance onto the V-model — `regression` → Build (verification),
  `artifact` + `manual` → a System-Test phase (validation) that only runs when such a check
  exists. `steward lint` validates only that each AC declares a valid `check:` (quality is
  intake's job, not lint's). Rewrites `/intake` to seed system-level, artifact-bound
  acceptance, classify each AC, and declare — in an optional `process:` frontmatter block —
  the concept phase, the lab dependency, and the fused-vs-split develop mode; the
  handbook documents the taxonomy. Building the **System-Test phase + flow-routing**, the
  independent **System Tester skill**, and the first **lab harness (IMAP)** are named
  follow-ons. (Dropped from the original draft: the over-broad "externally-facing" gate, its
  waiver, and the lint granularity gate — lint can't judge test quality.)
- REQ-028 — **gating integrity** (draft): the runtime/lint floor under REQ-027, from two
  FlowSteward post-mortems where one IMAP behaviour landed green three times without ever
  being gated. Sharpens "green" at land so it means *ran and passed*, not merely exit-0:
  a **skipped** named test fails the gate (a skip and a pass stop being the same signal); a
  **zero-collection** test id fails (no certifying yourself by naming a non-existent or
  delegated test); the **full suite** runs at land so any red anywhere turns the step red;
  the verifier runs in the **project venv** so `127 pytest: not found` can't reach a green
  land; and `steward lint` hard-errors when frontmatter `done` **contradicts the ledger**
  (the false `done` was a hand-edit lint never checked). Complements REQ-027 (which shapes
  *which* ACs exist); neither blocks the other. Enforcement only — no System-Test phase,
  taxonomy, or intake shaping here.
- REQ-039 — **concept phase** (draft): the left-arm counterpart of the System-Test
  (validate) phase. Today `process.concept:true` is a bare batch-ineligibility flag with no
  in-session semantics (mechanically identical to `develop: split`); FlowSteward's first
  concept phase surfaced that `/advance` never reads it and produces no mockups-first /
  sign-off behaviour. Adds a conditional **leading** `concept` step before develop — an
  **interactive-only** `/concept` guided session (`steward concept REQ-NNN`, same two-phase
  bring-up + `CLAUDECODE` guard as `steward validate`, but coupled-by-design: no decoupling,
  no evidence dir, no artifact gate). Deliverable is a `docs/concepts/REQ-NNN.md` architecture
  doc (recorded in `concept_refs`); spikes/prototypes are throwaway; the gate is an
  engine-recorded human sign-off (approve unblocks develop, defer parks async, decline routes
  to rework); runs on the integration branch. Concept is a higher altitude than `develop:
  split` (architecture vs implementation-plan review) — orthogonal, split untouched. Machinery
  + scratch `manual`-AC proof; FlowSteward's concept re-drive is the follow-on first real
  consumer (≡ REQ-031 after REQ-030). With REQ-027, REQ-029, REQ-030, REQ-034.
- REQ-040 — **live-ledger reads + checkpoint idempotency** (draft): the read-side follow-up
  to REQ-037. REQ-037 bound the ledger to the integration branch on the *write* paths but
  not the *read* path: `steward status` reads unbound and `/advance`'s step-1 reads
  `.devsteward/state.yaml` directly, so both return the stale branch-cut snapshot on a
  feature branch. The 2026-06-15 dogfood incident (postmortem
  `docs/reports/2026-06-15-req037-…-postmortem.md`) rode that into a mis-diagnosed re-run of
  `steward checkpoint`, which — lacking any already-`done` guard — appended a duplicate
  `develop_committed`. Binds the ledger on `steward status` (the one sanctioned orientation
  read; `/advance` uses it), and makes `steward checkpoint` hard-refuse an already-`done`
  step. Real-git ACs, no lab, no validate phase. With REQ-018, REQ-037.
- REQ-042 — **positional REQ target for advance/run** (draft): ergonomics on top of
  REQ-026's `--only`. `steward advance REQ-027` (and `steward run REQ-027`) are rejected
  today as "unexpected extra argument", so the natural gesture for steering which eligible
  REQ advances is invisible behind the `--only` flag — and plain `advance` silently grabs
  the lowest-id eligible step. Adds an optional positional `REQ_ID` mapping onto the existing
  `eligible_steps(only=…)` resolution (mutually exclusive with `--only`; ineligible target
  reuses `only_ineligibility_reason()`; no auto-activation of a draft), and makes the
  multi-eligible no-target case print the eligible ids + steer syntax. Regression ACs, no
  lab. With REQ-002, REQ-026.
- REQ-043 — **divergence surface + close-out switch are crash-proof** (draft, fix): the two
  paths REQ-037 D2 did not reach. `prepare_branch`'s diverged-branch refusal appends
  `branch_diverged` but never commits, dirtying the integration tree's tracked
  `events.jsonl`; a *later* step's green land then drives `_return_main_tree_to_integration`,
  whose `clean_untracked_ledger` (`git clean`, untracked only) leaves that dirt and whose
  `switch` = `git checkout` (check=True) → git refuses → uncaught `CalledProcessError`, with
  the worktree already gone and the checkpoint already committed (an unrecoverable half-state
  no verb targets). Commits the divergence diagnostic on the integration branch (matching the
  `reconcile_aborted`/`merge_aborted` siblings, satisfying REQ-032) and makes the close-out
  switch treat a dirty tree as a surfaced/parked precondition, not a crash. Prevention only —
  no `recover --resume-merge`; real-git ACs in `test_plane_split.py`. With REQ-032, REQ-037.
- REQ-052 — **post-REQ-047 cleanup: code + skill review** (draft): the disciplined sweep
  after the trunk-based pivot (REQ-048…051). A migration that size leaves residue — stale code
  paths and architecture still bent toward the removed feature-branch/worktree topology, and
  shipped skills still re-justifying a governance ("commit to dev not a feature branch") that
  is now a single stable invariant. Produces a sign-off review report in `docs/reports/`
  covering both reviews, fixes the feasible low-risk findings inline, and spins the rest out as
  recommendations / follow-on REQs. Manual sign-off + regression (suite stays green). With
  REQ-047.
- REQ-054 — **rename `recover` → `repeat`** (draft, refactor): recommendation #1 of REQ-053's
  audit. `steward recover` is misnamed for its dominant use — re-arming a `FAILED` step whose
  work was *sound* (an external crash/timeout/account swap) so the next run runs it again;
  `repeat` names that action honestly and reads right for the gate-red case too (the resuming
  session judges from the tree, so no split-by-cause). Renames the user-facing surface only —
  the `steward repeat` verb (**hard rename, no alias**), `lifecycle.repeat()`, and the
  `--recover` → `--repeat` resume flag (a two-sided contract: the executor appends it, the
  `advance` skill consumes it, so both move together). Leaves the internal `StepStatus.RECOVER`
  symbol and the `step_recover` event name unchanged (not user-facing; preserves ledger-history
  continuity). Code + tests only; handbook/skill *prose* defers to a docs REQ. No behavioural
  change. Independent of REQ-055. With REQ-026 (the verb it renames).
- REQ-055 — **`steward revalidate`** (draft, feature): the one correctness-of-fit gap from
  REQ-053's audit — the only place a named path makes a human redo *sound* work. A red
  validation today steers unconditionally to `steward rework` (re-open develop, rebuild),
  right only when develop was *hollow* (internal cause). When the cause is *external* (broken
  lab/fixture/credential the human fixed) the develop work stands and only the validation
  should re-run. Adds `revalidate` as `rework`'s structural mirror — same precondition (an
  in-flight REQ parked on a *red* validation), opposite action: flip `validate` BLOCKED→PENDING,
  leave `develop` DONE, answer the parked decision, append a `revalidate` event — and fixes the
  `_park_red` brief to name *both* edges as a root-cause choice. Red-only precondition (state F
  / pending-awaiting-oracle stays `steward validate`, REQ-057). Regression-only; code + brief +
  tests, no handbook (docs → REQ-057). Independent of REQ-054. With REQ-033 (the mirrored edge),
  REQ-047.
- REQ-056 — **D/H fail to a repeatable step, not a decision park** (draft, fix): recommendation
  #4 of REQ-053's audit, reframed by the owner from *patch* to *subtract*. Two states that
  REQ-053 enumerated as stalemate-generators are not genuine forks — **repair-exhausted** (D:
  budget spent, gate still red) and **land-refused** (H: no plan names the REQ) — yet both park
  a decision, and answering one restarts the step clean, abandoning the partial work, so the
  human re-parks in a loop. Neither is a *choice*; both want "fix it out-of-band, run it again",
  which the engine already has as `steward repeat` (FAILED→RECOVER→`--repeat`, the audit's state
  A). Takes D/H **off** the decision mechanism: set the step `FAILED` (not `BLOCKED`), park no
  decision, keep the `repair_exhausted`/`land_refused` event, and let `repeat` carry the dirty
  tree forward — `answer_decision`/`park_decision` untouched (pure subtraction). Companion: a
  `FAILED` step's `steward status` line names its forward verb (`steward repeat REQ`) so the
  guidance the decision gave isn't lost. Leaves the decision surface meaning only real forks
  (attended / skill-question / rework-vs-revalidate). Regression-only; rewrites the two
  park-asserting phase-model tests. With REQ-029 (the repair loop + land gate that create D/H),
  REQ-054 (the `repeat` verb).
- REQ-057 — **post-REQ-047 docs refresh + a Claude-targeted `steward` black-box manual** (draft,
  docs): recommendation #5 of REQ-053's audit, widened by the owner into the documentation REQ
  the whole REQ-054…056 cluster deferred to. Two needs. (1) The Quarto handbook is stale — it
  still describes feature branches/worktrees/switching, names the dead verb `recover` (renamed
  `repeat` by REQ-054), has no `revalidate` (REQ-055), and predates REQ-056 — so it gets a
  **complete** revision to the trunk-based model with the recovery/forward-path model documented
  as one section. (2) Agents driving DevSteward from a consumer project (FlowSteward) read the
  engine's `cli.py` to learn the tool and recover states — the wrong behaviour: DevSteward is an
  **encapsulated unit**, the `steward` CLI is its only public interface. Adds a concise
  **Claude-targeted `steward` manual** (black-box: operate + recover from every red/parked state
  without reading source), ships it in the templates, has `steward new` stamp it into new
  projects, and references it from the consumer `CLAUDE.md.tmpl`. Both docs + the bundled skills
  carry `repeat`/`revalidate` (REQ-054/055 deferred the prose here). Rides one behavioural fix:
  `decision answer` on a pending-validation (state-F) ticket refuses and redirects to
  `steward validate` (closing the same circle REQ-056 closed for D/H). 3 regression ACs
  (guard, stamping+reference, verb strings) + 1 manual sign-off (revision complete + manual
  black-box-sufficient); fused, no lab. With REQ-007, REQ-034, REQ-047, REQ-054, REQ-055,
  REQ-056.
- REQ-058 — **engine budget gate delegates to clauder** (draft, feature): bring the sibling
  project **clauder** (the built combined-budget policy layer over cswap) into the engine and
  retire DevSteward's hand-rolled per-account gate. Today `CswapAccountProvider.precheck()` reads
  cswap's `usage.json` directly and gates each account against a fixed 70% margin — refusing a job
  when the active account is low even if the pool could carry it. This delegates the per-step gate
  to `clauder gate --threshold T --json` (combined-budget: proceed/switch/wait/unsatisfiable,
  picks the best entry account, computes waits), treating clauder as an **optional external
  black-box tool** shelled via its CLI (Q1). The engine gates at **every step boundary** but never
  owns clauder's continuous `monitor` (operator-run, manually or as a service); it adds **no
  second switcher** — all account interaction routes through the single `clauder gate` chokepoint,
  never cswap directly, so the engine's gate and a background monitor cannot race (the lock that
  serialises the shared switch is a **clauder-side** prerequisite, not a DevSteward dep). Drops the
  direct-cswap machinery (`usage_snapshot`, the per-account loop) and the `use=N` slot-pin; absent
  clauder degrades to proceed-without-check (Q3). In-flight reality: a running `claude -p` can't be
  moved mid-session, so the gate enters each step on a healthy account and the monitor
  pre-positions between calls. AC1/AC2 regression (verdict mapping, single chokepoint, degradation,
  stubbed clauder) + AC3 manual (real cswap + ≥2 accounts + live monitor, no race); fused, no
  owned lab. With REQ-008 (provider seam), REQ-025 (the gate behaviour it replaces).
- REQ-053 — **process resilience: forward-path audit + rework/repeat model** (draft, design):
  the third strand of REQ-052's idea stub, split out as a process redesign. Audits whether,
  post-REQ-047 (state can no longer diverge), every red/failed/parked state has a clear,
  *available* forward path — and whether the `recover`/`rework` verbs map onto the real two
  options: **repeat** (external root cause — rate limit, API timeout, a setup the human fixed;
  the work was sound) vs **rework** (the work was insufficient). Covers the out-of-tool
  root-cause case (a stable path to adopt an external fix and continue) and recommends whether
  `recover` should become `repeat`. Audit-and-recommend: a `manual` report; implementation
  spins out. With REQ-047.
- Future REQs land here as `/intake` produces them.

## Dependency graph

```
REQ-001
 ├─ REQ-002 ──┬─ REQ-004 ── (with REQ-003)
 │            ├─ REQ-007
 │            ├─ REQ-009 ── (with REQ-005)
 │            ├─ REQ-010 (open) ──┬─ REQ-017 (draft, legacy prose)
 │            │                   └─ REQ-023 (draft, index splice — non-destructive in place)
 │            └─ REQ-021 (draft, lettered ids — unblocks memzy onboarding)
 └─ REQ-003 ──┬─ REQ-004 ── REQ-022 (draft, seed-ledger; with REQ-021)
              ├─ REQ-005 ── REQ-009
              ├─ REQ-006 ── REQ-015 ── REQ-028 (draft, gating integrity: skip≠green, full-suite+venv gate, marker↔ledger lint; with REQ-002)
              ├─ REQ-008 ── REQ-012 ── REQ-025 (draft, account rotation + quota gate + graceful stop; with REQ-003)
              ├─ REQ-018 (draft, revised: checkpoint = verifying bookkeeper + close-out; with REQ-020, REQ-028, REQ-029)
              ├─ REQ-026 (draft, lifecycle CLI: activate / recover / --only; with REQ-002) ── REQ-042 (draft, positional REQ target for advance/run — ergonomics over --only; with REQ-002)
              └─ REQ-004 ── REQ-027 (done, acceptance taxonomy + intake seeding; with REQ-002, REQ-009)
 REQ-028 ── REQ-029 (draft, develop fusion + mechanical land + repair-on-red; with REQ-004, REQ-020, REQ-027)
 REQ-029 ──┬─ REQ-018 (draft, revised — see above)
           └─ REQ-030 (draft, System-Test phase + evidence events; with REQ-005, REQ-027) ── REQ-031 (draft, first lab: IMAP + FlowSteward re-drive)
 REQ-030 ──┬─ REQ-033 (rework loop: human-authorized red-validation → develop return edge; with REQ-026)
           ├─ REQ-034 (draft, guided async human validation + QA-ticket park + clean re-entry; with REQ-020, REQ-032, REQ-033)
           │   ├─ REQ-037 (draft, ledger on dev only + atomic recoverable topology — the live-crash root fix; unblocks REQ-034 re-validation; with REQ-020, REQ-032)
           │   │   ├─ REQ-038 (draft, cross-host validation deploy channel: artifact-export RC + patch-back via rework — Finding 90 opt A; with REQ-030, REQ-033)
           │   │   ├─ REQ-043 (draft, fix: divergence surface + close-out switch crash-proof — finishes REQ-037 D2 for the two paths it missed; with REQ-032) ── REQ-044 (draft, steward supersede: human-only close of a superseded branch + abort-recovery pointer — no false merge-by-hand; with REQ-037)
           │   │   └─ REQ-040 (done, live-ledger reads + checkpoint idempotency — read-side follow-up to REQ-037; with REQ-018)
           │   │       └─ REQ-041 (open, finish REQ-040 D1: route ALL read-side ledger access through live_ledger — validate pre-flight, no-arg checkpoint, report)
           ├─ REQ-035 (draft, fix: done re-validation freezes verified_by — provenance not clobbered)
           ├─ REQ-036 (draft, steward sync-skills: refresh stamped bundled skills + provenance manifest + drift signal; with REQ-007)
           └─ REQ-039 (draft, concept phase: interactive leading architecture session that gates develop — left-arm counterpart of validate; with REQ-027, REQ-029, REQ-034)
 REQ-047 (done, trunk-based pivot) ──┬─ REQ-052 (draft, post-pivot code + skill review → sign-off report)
                                     └─ REQ-053 (done, design: process-resilience forward-path audit + rework/repeat model)
 REQ-026 (recover verb) ── REQ-054 (draft, refactor: rename recover → repeat + --recover → --repeat; hard rename, no alias)
 REQ-033 (rework edge) ── REQ-055 (draft, feature: steward revalidate — mirror of rework, external-cause re-validate; with REQ-047)
 REQ-053 (forward-path audit) ──┬─ REQ-056 (draft, fix: D/H off decisions → repeat; FAILED-step names its forward verb; with REQ-029, REQ-054)
                                └─ REQ-059 (draft, fix: interrupted run self-heals a stranded RUNNING step + honest ineligibility diagnosis; with REQ-025, REQ-026)
 REQ-047 + REQ-056 ── REQ-060 (draft, fix: caught-up project reports an honest terminal state — cursor never names a done step; with REQ-018)
 REQ-054 + REQ-055 + REQ-056 ── REQ-057 (draft, docs: complete post-REQ-047 handbook revision + Claude-targeted black-box steward manual shipped via templates + state-F decision-answer guard; with REQ-007, REQ-034, REQ-047)
 REQ-008 (account provider seam) ── REQ-025 (visible rotation + quota gate) ── REQ-058 (draft, feature: engine budget gate delegates to clauder CLI; drop direct cswap; race-free with operator-run background monitor [clauder-side lock prereq]) ── REQ-061 (draft, feature: re-wire account pin — steward --pin N forwards clauder gate --pin N [clauder REQ-006 PATH prereq]; hard-rename --use→--pin; drain a 7d window before reset)
 REQ-011 (done, production-branch guard) ── REQ-019 (done, integration-branch guard) ── REQ-020 (draft, branch lifecycle automation)
 REQ-024 (draft, onboard skill) ── orchestrates REQ-007 + REQ-009 + REQ-010/023 + REQ-021 + REQ-022 (memzy onboarding)
```
