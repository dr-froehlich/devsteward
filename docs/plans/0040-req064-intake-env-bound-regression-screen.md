# Plan 0040 — REQ-064: intake screens environment-bound `regression` ACs

Covers **REQ-064**. The left-shift complement to REQ-063 (engine cure, done): teach `/intake`
to catch an AC whose green silently rides hidden environment, at authoring time, and route the
fix by REQ-027's oracle-coupling rule. Docs/skill only — no engine, no lint, no schema.

## Approach

A pure authoring-surface guardrail (REQ-064 Decisions 1 & 5): the `/intake` skill gains an
**environment-binding screen** in §2b, and the handbook taxonomy (`_01-format.qmd`) documents
the **environment-bound-`regression` smell** with the FlowSteward REQ-043 worked example.

The screen reuses the taxonomy's own axis (REQ-027 D2 — oracle coupling), so it adds no new
concept: screen every `check: regression` for an oracle needing a service/secret/network
absent from a clean checkout; on yes, a **decoupled** oracle → reclassify `artifact` + name
the lab in `process.lab`; a **coupled** oracle that only needs a **runtime** → keep
`regression` and record the required environment in the REQ prose. It steers, never forbids
(REQ-063 makes the engine tolerate the skip).

## Files

- `.claude/skills/intake/SKILL.md` (**hardlinked** to `devsteward/templates/.claude/skills/
  intake/SKILL.md`, inode 523945 — edit once, then re-link with `ln -f` and verify byte-equal,
  per `[[skills-hardlinked-to-templates]]`): add the §2b "environment-bound `regression`"
  screen after the Honest-deferral block.
- `devsteward/handbook/_01-format.qmd`: add the smell paragraph after the Oracle glossary.
- `tests/test_intake_skill_contract.py`: add `test_intake_screens_environment_bound_regression`.
- `tests/test_handbook_taxonomy.py`: add `test_handbook_documents_environment_bound_regression`.

## Acceptance

- **AC1** `test_intake_screens_environment_bound_regression` — the stamped skill names the
  smell, the screening question (service/secret/network absent from a clean checkout), and the
  oracle-coupling routing (decoupled → artifact + `process.lab`; coupled-needs-runtime → keep
  regression + record the required environment).
- **AC2** `test_handbook_documents_environment_bound_regression` — `_01-format.qmd` documents
  the smell + screening + routing with the REQ-043 worked example.
- **AC3** (`manual`) — a human runs `/intake` on a deliberately env-bound idea and confirms
  the screen fires + honest classification. This makes REQ-064 carry a **validate** phase, so
  the develop land **defers** (committed, not flipped `done`); the sign-off is a separate plain
  session (a fresh `/intake` run; the guided path refuses to spawn from inside Claude).

## Out of scope

Any `steward lint` heuristic, any schema field, the engine (REQ-063), and the FlowSteward AC.
