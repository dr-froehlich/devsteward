# 0038 — `onboard` operator skill (REQ-024)

**Date:** 2026-06-21
**REQ:** REQ-024 — onboard skill: orchestrate migrating an existing project under the engine.
**Builds on:** [0005 — memzy onboarding](0005-memzy-onboarding.md) (the deployment narrative this
skill operationalizes), [[REQ-023]] (converter index splice), [[REQ-022]] (`steward seed-ledger`),
[[REQ-007]] (scaffold stamp), [[REQ-021]] (lettered ids / widened schema).

## What this REQ ships

The `onboard` *skill* only — `.claude/skills/onboard/SKILL.md` + its content/tool-availability
tests. It owns **no migration logic**: it is the procedure-and-judgement layer over already-tested
tools (Decision 3). The live memzy run is **out of scope** here — it is REQ-062 (the proof run).

## Placement (Decision 2)

DevSteward's **own** `.claude/skills/onboard/`, *not* `devsteward/templates/`. A stamped consumer
is already onboarded and never runs `onboard`; bundling it would ship dead scaffolding. Same home
as the operator `intake`/`advance`/`bootstrap` skills. Because it is absent from `templates/`,
`skillsync.bundled_skill_names()` will not see it, so the REQ-036 drift/sync tests are unaffected.

## The skill's content — the five-step pipeline (in order)

1. **Convert** the corpus in place — `scripts/convert_reqs.py` ([[REQ-010]] + [[REQ-023]] splice)
   — then **gate** on `steward lint` clean.
2. **Seed** the ledger — `steward init` then `steward seed-ledger` ([[REQ-022]]) — **gate** on
   `steward status` showing the corpus all-done and the work queue empty.
3. **Stamp** the scaffold ([[REQ-007]]): widened schema ([[REQ-021]]), `_templates/`, `.gitignore`
   additions, config with the project's real branch names — **merging** into any existing
   `.claude/`/settings, never overwriting.
4. **Reconcile CLAUDE.md** — fold the house conventions (same-commit discipline, ledger contract,
   branching model, co-author trailer) into the target's existing CLAUDE.md without discarding its
   domain guidance.
5. Carry the **park-and-surface** contract (honour `DEVSTEWARD_UNATTENDED=1`); **stop on any red gate**.

Scenarios (`SCN-*`) and ROADMAP conversion are **out of scope** (Decision 7 / plan 0005).

## Tests — `tests/test_onboard_skill.py` (all `check: regression`)

A skill's guarantee is its documented procedure + the existence of the tools it names (REQ-021 D5 /
REQ-009 posture), not an end-to-end re-migration. The five ACs map one-to-one to test functions:

| AC  | Test | Asserts |
|-----|------|---------|
| AC1 | `test_onboard_documents_pipeline_in_order` | skill exists with `name:`/`description:` frontmatter; the four pipeline verbs (convert→seed→stamp→reconcile) appear **in order** |
| AC2 | `test_onboard_tools_exist` | skill names the real tools; `scripts/convert_reqs.py` exists; `seed-ledger` is a registered `steward` subcommand |
| AC3 | `test_onboard_documents_verification_gates` | `steward lint` after convert, `steward status` after seed, and "stop on a red gate" are documented |
| AC4 | `test_onboard_merge_and_scope` | merge-not-overwrite for existing `.claude/`/CLAUDE.md; scenarios/ROADMAP marked out of scope |
| AC5 | `test_onboard_documents_park` | the park-and-surface contract (`DEVSTEWARD_UNATTENDED`) is carried |

## Files touched (same commit)

- `.claude/skills/onboard/SKILL.md` — new.
- `tests/test_onboard_skill.py` — new.
- `docs/requirements/REQ-024.md` frontmatter + `REQUIREMENTS_INDEX.md` row — **the engine flips
  these to `done` on green** (not hand-edited here).
