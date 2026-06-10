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
2. REQ-029 — **phase-model rework** (stub): one fused `develop` step; land becomes engine
   code on green (zero Claude tokens); bounded repair session (budget 2, Sonnet) on red;
   per-step model/effort config
3. REQ-018 — **revised**: `steward checkpoint` verifies with the REQ-028 gate and shares
   REQ-029's mechanical bookkeeping — the engine certifies in both modes; handbook flips
   to interactive-first
4. REQ-030 — **System-Test phase** (stub): conditional on `artifact|manual` ACs; fresh
   context, never sees develop's diff; evidence = ledger event + captured artifact +
   `verified_by`; `manual` = decision stop; `steward validate REQ-NNN` re-run
5. REQ-031 — **first lab, IMAP** (stub): owned, versioned fixture with reality-derived
   provenance; FlowSteward REQ-003a/006/007 re-driven through the validate phase
6. (no REQ yet) re-earn batch mode: one overnight `steward run` under the new model,
   then postmortem

## Next

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
- REQ-027 — **acceptance test taxonomy, seeded by intake** (draft): the fix for nine
  green-but-hollow REQs (canonical: FlowSteward REQ-003 AC1, a mock discharging a system
  claim). Adds a required per-AC `check:` field (`regression | artifact | manual`) as a
  **routing key** that maps acceptance onto the V-model — `regression` → Build (verification),
  `artifact` + `manual` → a System-Test phase (validation) that only runs when such a check
  exists. `steward lint` validates only that each AC declares a valid `check:` (quality is
  intake's job, not lint's). Rewrites `/intake` to seed system-level, artifact-bound
  acceptance, classify each AC, and declare the optional concept phase + lab dependency; the
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
              ├─ REQ-018 (draft, revised: checkpoint = verifying bookkeeper; with REQ-028, REQ-029)
              ├─ REQ-026 (draft, lifecycle CLI: activate / recover / --only; with REQ-002)
              └─ REQ-004 ── REQ-027 (draft, acceptance taxonomy + intake seeding; with REQ-002, REQ-009)
 REQ-028 ── REQ-029 (draft, develop fusion + mechanical land + repair-on-red; with REQ-004, REQ-020)
 REQ-029 ──┬─ REQ-018 (draft, revised — see above)
           └─ REQ-030 (draft, System-Test phase + evidence events; with REQ-027) ── REQ-031 (draft, first lab: IMAP + FlowSteward re-drive)
 REQ-011 (done, production-branch guard) ── REQ-019 (done, integration-branch guard) ── REQ-020 (draft, branch lifecycle automation)
 REQ-024 (draft, onboard skill) ── orchestrates REQ-007 + REQ-009 + REQ-010/023 + REQ-021 + REQ-022 (memzy onboarding)
```
