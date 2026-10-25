# Plan 0047 — REQ-071: concept-phase & wiring-gap doctrine on four surfaces

REQ-071 is pure doctrine (kind: docs, no engine code). Five rules + the unifying decision
rule land on four surfaces; a hermetic anchor test proves every surface was actually
edited (the REQ's own wiring lesson applied to itself).

## Surfaces and what each carries

| Surface | File (canonical edit point) | Rules |
|---|---|---|
| STEWARD.md | `STEWARD.md` → symlink to `devsteward/templates/STEWARD.md` (one file) | decision rule + all five |
| handbook | `devsteward/handbook/_00-method.qmd` (no template twin) | decision rule + all five |
| /intake skill | `.claude/skills/intake/SKILL.md` (hardlinked to its template — one inode) | decision rule + rules 2, 3, 5 |
| /advance skill | `.claude/skills/advance/SKILL.md` (hardlinked to its template — one inode) | rule 4; drop the stale "never commit prototype code" line |

## The rules (see REQ-071 Requirement for full text)

1. **Concept-phase-as-functional-spec** + decision rule: set `concept: true` when the ACs
   **cannot be honestly written at intake**; "the concept phase is where you earn the ACs
   you can't yet write."
2. **Wire-through-the-live-entrypoint**: system-scoped ACs run through the real running
   entrypoint; present-but-unwired fails; **tests passing ≠ wired**.
3. **Don't-scope-a-known-defect-out**: fix here or home in a **named follow-on REQ**;
   never silently deferred.
4. **Concept-phase-iterates-until-frozen**: an empirical concept phase may commit + push +
   deploy repeatedly; **`steward checkpoint` is the terminal act**, sanctioned over an
   already-clean tree (records the step over an effectively no-op commit). Interactive
   only — batch parks `concept: true`.
5. **Phase-model-placement**: when `concept: true` because the ACs depend on the
   deliverable, intake asks split-vs-named-downstream-REQ; the upstream REQ must **never
   carry the downstream REQ's acceptance bar**. `concept:true`+`fused` stays the
   legitimate spike default.

## Edits

- `/advance` §2 concept bullet: rewritten — bundle/prototype deliverable (REQ-067),
  iterate-until-frozen scope, terminal checkpoint semantics; the anti-REQ-067 "never
  commit prototype code" sentence is deleted. §4 interactive close gets the mid-phase-
  commit exception cross-reference.
- `/intake` §2a: the wire-through-the-live-entrypoint paragraph. §2 (after the
  interrogation list): the known-defect rule. §2c `concept:` bullet: the decision rule +
  the phase-model-placement interrogation (with the REQ-081 AC6 trap as the worked
  example).
- `STEWARD.md`: the `/advance` bullet notes the empirical-concept exception; the
  concept-gate paragraph grows the decision rule + iterate/terminal-checkpoint semantics +
  phase-model placement; a compact "Authoring doctrine" section carries rules 2 + 3.
- `handbook/_00-method.qmd`: a new "Earning the acceptance criteria" section states the
  decision rule and all five rules in method terms (V-model left arm).

## Test

`tests/test_req071_doctrine_surfaces.py` (AC1, `check: regression`, hermetic) — style of
`test_handbook_taxonomy.py`: reads the four shipped surfaces via `importlib.resources`
(templates carry the skills/STEWARD.md; the handbook ships as package data) and asserts
the per-surface anchors: "cannot be honestly written at intake", "earn the ACs you can't
yet write", "≠ wired" / "real running entrypoint", "named follow-on REQ",
"is the terminal act", "never carry the downstream REQ's acceptance bar" — and that the
/advance skill no longer contains "never commit prototype code".

AC2 is the `manual` coherence sign-off → `steward validate REQ-071` from a plain terminal.

## Out of scope (per the REQ)

No engine/lint changes (Decisions 4, 6); the REQ-081 commit-sweep defect stays unfiled
(Decision 7); the copied postmortem in `docs/reports/` is the record.
