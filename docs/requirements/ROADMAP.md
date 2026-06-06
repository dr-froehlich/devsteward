# Roadmap

The dependency DAG over DevSteward's own requirements. The engine derives step
eligibility from `depends_on`; this is the human-readable view of the same graph.

## Now

- REQ-001 — north star (the compass)

## Done (the baseline vertical slice)

REQ-002 … REQ-009 — the format + linter, the executor core, the REQ profile,
park-and-surface, the verification gate, `steward new`, the account provider, and the
three bundled skills. Built and dogfooded in Phase 0/1.

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
