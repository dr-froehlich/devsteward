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

- REQ-013 — **reality harness**: opt-in end-to-end test that drives a real `claude -p`
  (in-progress; the standing trust gate, expected red until the two fixes below land)
- REQ-014 — headless `claude -p` runs with a permission mode so a real session can edit
  files (in-progress; turns the first half of REQ-013's gate green)
- REQ-012 — real cswap 0.11 switcher CLI (draft; the provider speaks a fictional CLI)

## Next

- REQ-010 — legacy-format converter (draft; promote when a consumer needs it)
- Future REQs land here as `/intake` produces them.

## Dependency graph

```
REQ-001
 ├─ REQ-002 ──┬─ REQ-004 ── (with REQ-003)
 │            ├─ REQ-007
 │            ├─ REQ-009 ── (with REQ-005)
 │            └─ REQ-010 (draft)
 └─ REQ-003 ──┬─ REQ-004
              ├─ REQ-005 ── REQ-009
              ├─ REQ-006
              └─ REQ-008
```
