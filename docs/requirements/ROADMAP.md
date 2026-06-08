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
- Future REQs land here as `/intake` produces them.

## Dependency graph

```
REQ-001
 ├─ REQ-002 ──┬─ REQ-004 ── (with REQ-003)
 │            ├─ REQ-007
 │            ├─ REQ-009 ── (with REQ-005)
 │            └─ REQ-010 (open) ── REQ-017 (draft, legacy prose)
 └─ REQ-003 ──┬─ REQ-004
              ├─ REQ-005 ── REQ-009
              ├─ REQ-006
              ├─ REQ-008
              └─ REQ-018 (draft, interactive checkpoint)
 REQ-011 (done, production-branch guard) ── REQ-019 (done, integration-branch guard) ── REQ-020 (draft, branch lifecycle automation)
```
