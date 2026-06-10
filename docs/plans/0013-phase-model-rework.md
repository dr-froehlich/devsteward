# Plan 0013 — Phase-model rework (REQ-029)

**Develop checkpoint for REQ-029** (plan 0011 step 2, driven interactively per the
migration note: fused develop, human present). Collapse the three-step
`design → build → land` cycle into **one `develop` Claude session**; on a green REQ-028
gate the engine performs the **mechanical land** itself (status flip, index sync, one
commit, `--no-ff` merge, ledger advance) with **zero Claude tokens**; on a red gate it
spawns at most **two** repair sessions (fresh context + failure brief, default Sonnet)
then parks. Model/effort become **per-step-kind** config. The mechanical-land tail is
extracted as a clean shared routine because REQ-018 (`steward checkpoint`) is its second
caller.

All ten mechanics were settled at the 2026-06-10 interview (REQ-029 Decisions 1–10); this
plan is grounded, not exploratory. No forks remain open.

## What the new model is, concretely

Today (`reqfile.PHASES = ("design", "build", "land")`): three steps per REQ, each a cold
`claude -p` session. `design`/`build` carry no `verify` and pass on marker-trust; `land`
carries the acceptance `test:` commands, and the executor runs the REQ-028-toothed
`ReqVerifier`, the `ReqDoneFlipper` (`on_verified`), the checkpoint commit, then
`_merge_after_land`.

After this REQ (`PHASES = ("develop",)`): **one** step per REQ. `develop` is the old
`build`+`land` fused — it carries the acceptance `test:` commands as its `verify`, is the
session that does design+code+tests, and is the gate the engine verifies. `design`
disappears as a session boundary (plan-first survives *inside* the develop session as a
required artifact, enforced by the plan gate at land). There is **no `land` Claude step**:
the green-gate tail is engine code.

## Surfaces (confirmed by reading the code)

- `devsteward/profiles/req/reqfile.py` — `PHASES = ("design", "build", "land")` →
  `("develop",)`. The `land`-carries-acceptance logic in the step source keys off the
  phase name; the dependency edge (`{dep}:land`) must move to `{dep}:develop`.
- `devsteward/profiles/req/source.py` — `ReqStepSource.steps`: emit one `develop` step per
  active REQ. It carries `verify = tuple(c.test …)` (was the `land` branch), `depends_on`
  resolves each unsatisfied dependency to `{dep}:develop` (was `:land`). The
  per-phase loop collapses to a single step; `prev`-chaining within a REQ goes away.
  **Decision 9:** set a new generic `Step.attended` flag when `process.develop == "split"`
  or `process.concept` is true (read via `ReqFile.process`, already shipped by REQ-027).
- `devsteward/core/model.py` — `Step` gains `attended: bool = False` (content-agnostic
  name: "this step needs a human present"; the profile gives it meaning). Frozen dataclass,
  additive default — existing construction sites unaffected.
- `devsteward/profiles/req/verify.py` — `ReqVerifier.verify`: the `if step.phase != "land"`
  guard becomes `!= "develop"`; the teeth (no-skip, no-zero-collection, full-suite, env
  resolution) now gate the develop step. No semantic change to *what* green means — only
  *which* step is the delivering one.
- `devsteward/profiles/req/checkpoint.py` — `ReqDoneFlipper.__call__`: `if step.phase !=
  "land"` → `!= "develop"`. Still idempotent, still flips frontmatter + index in lockstep.
- `devsteward/core/executor.py` — the heart of the change:
  - `implementation_phases` default `("build", "land")` → `("develop",)` (branch management
    now brackets the develop step; `prepare_branch` and the merge both key off it).
  - `_drive_step`: the `step.phase == "land"` merge trigger → `"develop"`.
  - **Extract `mechanical_land(step)`** — the post-green tail shared by `run_step` and
    `checkpoint`: plan gate (Decision 6) → `on_verified` flip → `_commit` → ledger DONE +
    `checkpoint` event. The `--no-ff` merge stays in `_merge_after_land` (called by
    `_drive_step` after a green develop), so the shared routine is the in-branch tail and
    REQ-018's `steward checkpoint` reuses exactly it.
  - **Repair loop** (Decision 3/8): wrap the develop verify. On a red gate, spawn up to 2
    fresh `claude -p` repair sessions, each with the failure brief, then park.
  - **Batch park** (Decision 9): in `run_step` (or `_drive_step`), when `step.attended` and
    `unattended`, park a decision naming the attended need and return `PARKED` — no develop
    session spawned.
  - **Per-step-kind model/effort** (Decision 4): the runner call resolves model/effort by
    session kind (develop vs repair) instead of the single `self.model`/`self.effort`.
- `devsteward/config.py` + `devsteward/templates/.devsteward/config.yaml.tmpl` — a
  `claude.steps` mapping with documented defaults: `develop → {model: claude-opus-4-8,
  effort: high}`, `repair → {model: claude-sonnet-4-6}`. A `Config.step_claude(kind)`
  accessor returns the merged (step-override-over-`claude`-default) model/effort.
- `devsteward/build.py` — `build_executor` threads the per-step resolver into the
  `Executor` (replacing the flat `model`/`effort` it passes today; the CLI `--model/--effort`
  override still wins for `develop`, the primary session).
- `.claude/skills/advance/SKILL.md` **and** `devsteward/templates/.claude/skills/advance/SKILL.md`
  — currently the workflow is "A·Design → B·Build → C·Land". Rewrite to the single
  **Develop** checkpoint (plan-first + code + acceptance tests in one session) and add the
  **repair** path (the `--repair` brief). `tests/test_skills.py` parametrizes over both
  copies — keep them identical.
- `devsteward/handbook/02-engine.md` (verification "where work is delivered" now says
  `develop`, not `land`; document mechanical land + repair budget) and `03-workflow.md`
  (the one-session cycle; the split/concept batch-park).
- **Not touched:** `devsteward/core/verify.py` (the REQ-028 machinery is phase-agnostic —
  only the profile's phase guard moves), the lint rules (no new static rule; the plan gate
  is a *land-time* check, deliberately not a lint rule — Decision 6 rationale).

## AC1 — one develop step, no design/build/land Claude step

`source.py` emits exactly one `Step` per active REQ, `id = "REQ-NNN:develop"`, carrying the
acceptance `test:` commands as `verify`. No `:design`, `:build`, or `:land` step exists.

`tests/test_phase_model.py::test_single_develop_step`: a temp project with one active REQ
(two acceptance tests) → `source.steps()` yields a single step; its id ends `:develop`, its
`verify` equals the two `test:` strings, and no step id contains `design`/`build`/`land`.
A second active REQ depending on the first → its develop `depends_on == ("REQ-AAA:develop",)`.

## AC2 — green develop lands mechanically, zero Claude at land

In batch, `_drive_step` runs the develop session (one runner call), `ReqVerifier` gates it
green, then `mechanical_land` + `_merge_after_land` run as **engine code** — no second
runner invocation. `events.jsonl` shows `step_started` (one, for develop) → `verify ok` →
`checkpoint` → `branch_merged`, with no second `claude session started`/`step_started` for a
land.

`tests/test_phase_model.py::test_mechanical_land_zero_claude`: a fake runner that records
its call count and leaves the tree green; drive one REQ green via `Executor.run`. Assert the
runner was called **once**, the REQ frontmatter + index are `done`, the ledger develop step
is `DONE`, and the `events.jsonl` has exactly one `step_started`. (Mirror the existing
`test_executor.py` / `test_branch_lifecycle.py` harness for the fake runner + temp git repo.)

## AC3 — the plan gate

`mechanical_land` runs a **grep-shaped existence check** before the flip: does any file in
`docs/plans/` contain the REQ id (`step.req`)? If not, do **not** flip/commit/merge — park
the step (BLOCKED) and surface
`"REQ-NNN: refusing to land — no file in docs/plans/ names REQ-NNN (plan-first discipline)"`.
With a matching plan file present, the land proceeds. The engine checks **existence only**,
never plan quality (Decision 6).

Resolution detail: read each `docs/plans/*.md`, substring-match the REQ id — cheap, static,
load-bearing only at the one moment it matters. (Not a lint rule: lint would fire during the
entire develop window before the plan can exist.)

`tests/test_phase_model.py::test_land_requires_plan_artifact`: green-gate REQ with **no**
`docs/plans/` mention → land refused, REQ stays active, ledger step not DONE, surfaced
message names the REQ; then write `docs/plans/00xx-foo.md` mentioning the id and re-drive →
lands clean.

## AC4 — repair budget then park

On a red develop gate (`ReqVerifier` returns `(False, detail)`), the executor enters a
repair loop: for up to **2** attempts, spawn a **fresh** `claude -p` session (not
`--resume`) whose prompt carries the **failure brief** — the verifier `detail` (failed test
ids + tail) and the REQ id — re-verify after each. The repair command is the develop command
plus a `--repair` marker and the brief block; the advance skill, seeing `--repair`, assesses
the partial tree *and* the named failures (a sharper `--recover`). Repairs use the **repair**
model/effort (default Sonnet — Decision 4/8: cold-start tax is cheap on Sonnet). After the
budget is exhausted with the gate still red, **park** the step (BLOCKED) with a decision
naming the persistent failure; the run moves on / stops per existing red-handling.

`tests/test_phase_model.py::test_repair_budget_then_park`: a fake runner that stays red and
records each invocation's prompt + model. Drive one REQ. Assert: develop call (opus) + **2**
repair calls (each `--repair`, each carrying the failed-test detail, each Sonnet) = 3 runner
calls total; the step ends BLOCKED with an open decision; no `checkpoint` event; no merge.
A second case: red develop, repair #1 turns it green → land succeeds, only one repair spawned.

## AC5 — per-step-kind model/effort config

`Config.step_claude(kind)` merges `claude.steps.<kind>` over the flat `claude.*` defaults,
returning `(model, effort)`. Documented defaults: `develop → opus-4-8/high`,
`repair → sonnet-4-6/(inherit effort)`. `build_executor` passes a resolver; the executor
asks it for `develop` when spawning the main session and `repair` for each repair session,
and threads the result into `run_claude(model=…, effort=…)`. CLI `--model/--effort` still
override the develop session.

`tests/test_phase_model.py::test_per_step_model_config`:
(a) defaults — `step_claude("develop") == ("claude-opus-4-8", "high")`,
`step_claude("repair")[0] == "claude-sonnet-4-6"`;
(b) a config with `claude.steps.repair.model: claude-haiku-4-5` overrides only repair;
(c) end-to-end: the fake runner records the `model` kwarg per call and the develop call gets
opus while the repair call gets the configured repair model.

## AC6 — split / concept park in batch

`source.py` sets `Step.attended = True` when the REQ's `process.develop == "split"` **or**
`process.concept` is true. In batch (`unattended=True`), the executor parks such a step
before spawning anything, with a decision whose question names the attended need —
`"REQ-NNN declared a split develop — needs an attended design review"` or
`"REQ-NNN declared a concept phase — needs an attended session"` — and returns `PARKED`
(no runner call). One shared rule for both flags (Decision 9). Full concept-phase mechanics
stay a future REQ; only this batch-park lands here.

`tests/test_phase_model.py::test_split_and_concept_park_in_batch`: two REQs, one with
`process: {develop: split}`, one with `process: {concept: true}`; `Executor.run` parks each
with a decision naming the right need, the fake runner is **never** called for them, and a
third default-process REQ in the same run still lands normally.

## AC7 — ledger reinterpreted, never rewritten

This falls out of the design — the test pins it. The source emits only `:develop` ids and
reads activeness from REQ frontmatter; the ledger's old `:design`/`:build`/`:land` rows are
orphaned history. `events.jsonl` is append-only throughout (no code path rewrites it).

`tests/test_phase_model.py::test_old_ledger_reinterpreted_not_rewritten`:
(a) a REQ whose frontmatter is `done` with an old `REQ:land` DONE row in `state.yaml` →
`source.steps()` yields no step for it (not active);
(b) a REQ active in frontmatter with only old `REQ:design`/`REQ:build` DONE rows (no land) →
a fresh `REQ:develop` step appears, PENDING, eligible;
(c) capture `events.jsonl` byte length before a drive and assert it only **grew** (append),
with the pre-existing old-shape events still present verbatim.

## AC8 — the real e2e proof (manual, after merge)

Not a build artifact (REQ-027 Decision 12; REQ-029 Decision 10). After the implementation
merges to `dev`, a real `steward run` (or `steward advance`) drives **one trivial scratch
REQ** green end-to-end under the new model — no owned lab needed (`process.lab` empty). The
reviewer (Peter) inspects the proof run's `events.jsonl` (develop → mechanical land, **zero
Claude invocations at land**) and the merged commit against Decisions 1–2, flips AC8
`status: pass` by hand, and records date/reviewer/scope in `verified_by`. REQ-029 stays
`in-progress` until that run happens; the `done` flip + index `DONE` sync ride that same
commit. No ledger advance (this REQ is interactive, pre-trusted-batch).

## Build order (one feature branch: `req-029-phase-model`)

Flip REQ-029 `draft → in-progress` at branch start (same-commit discipline at each step).

1. **Model + source + reqfile:** `Step.attended`; `PHASES = ("develop",)`; rewrite
   `ReqStepSource.steps` (single step, `:develop` deps, `attended` flag). AC1 + AC7(a/b)
   tests. (`test_executor.py`/`test_branch_lifecycle.py` will need their phase ids updated
   `build`/`land` → `develop` — expected churn, do it here.)
2. **Profile phase guards:** `ReqVerifier` and `ReqDoneFlipper` `"land"` → `"develop"`;
   `implementation_phases` default + `_drive_step` merge trigger → `"develop"`. Existing
   `test_verify_*` / branch-lifecycle suites green again.
3. **Mechanical land extraction + plan gate:** factor `mechanical_land(step)` out of
   `run_step`/`checkpoint`; add the `docs/plans/` existence gate. AC3 test; refactor keeps
   `checkpoint` behavior identical (regression via existing checkpoint tests).
4. **Per-step model config:** `Config.step_claude`, template `claude.steps` block,
   `build_executor` resolver, executor uses it. AC5 test.
5. **Repair loop:** the red-gate repair budget + park, repair prompt with brief. AC4 test.
6. **Batch park:** `attended` + `unattended` → park decision. AC6 test.
7. **Skill + handbook:** rewrite both `advance/SKILL.md` copies to the Develop checkpoint +
   repair path (identical copies — `test_skills.py`); handbook 02/03 passes.
8. `steward lint` + full `python -m pytest` green → merge plain into `dev` (no PR). AC8 +
   `done` follow per above, after the manual proof run.

## Invariants preserved

- **REQ-028 teeth unchanged:** the verifier machinery is phase-agnostic; only *which* phase
  is the delivering gate moves (`land` → `develop`). A no-op develop is still caught by its
  acceptance tests + the full suite; skip ≠ green; env resolution still hard-errors.
- **One authoritative commit** per checkpoint; the engine still owns it; the skill still
  leaves the tree dirty in batch and must not commit/branch.
- **Append-only event log** (the audit contract) — the migration reinterprets, never
  rewrites (Decision 7).
- **Declaration stays on the integration branch; only implementation branches** — `develop`
  is now the (only) implementation phase, so branch management brackets it; intake/plan/
  ledger writes still happen on `dev`.
- **Mechanical land is a clean shared function**, not inlined — REQ-018's `steward
  checkpoint` is its second entry point (REQ-029 Notes).
- English-only technical text; engine/profile/config strings carry no localized UI.

## Forks

None open. The four stub-era opens (ledger migration, repair context, human-presence
batching, the e2e proof) were settled at the 2026-06-10 interview and recorded as REQ-029
Decisions 6–10. Two small design points are resolved here by the obvious choice rather than
parked: (a) the **repair prompt carries the brief inline** via a `--repair` block (mirrors
the existing `--recover` flag mechanism, no new IPC); (b) `Step.attended` is the
**content-agnostic** carrier of the split/concept batch-park signal (the profile sets it,
the core only honors it) — keeping the core REQ-unaware.
