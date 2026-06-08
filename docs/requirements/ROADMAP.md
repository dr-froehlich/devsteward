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
              ├─ REQ-006
              ├─ REQ-008
              └─ REQ-018 (draft, interactive checkpoint)
 REQ-011 (done, production-branch guard) ── REQ-019 (done, integration-branch guard) ── REQ-020 (draft, branch lifecycle automation)
 REQ-024 (draft, onboard skill) ── orchestrates REQ-007 + REQ-009 + REQ-010/023 + REQ-021 + REQ-022 (memzy onboarding)
```
