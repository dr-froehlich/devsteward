# 0006 — `steward seed-ledger` (REQ-022)

**Date:** 2026-06-21
**Covers:** [[REQ-022]] — seed a ledger for an already-built corpus so historic REQs read as
done. Piece 3 of the memzy onboarding sequence (plan
[0005-memzy-onboarding](0005-memzy-onboarding.md)); build order REQ-023 → **REQ-022** →
REQ-024 → REQ-062.

## Problem

Onboarding an already-built project arrives with a corpus of REQs whose verdict is already
settled (memzy: 23 terminal REQs). `steward init` creates an *empty* ledger. The cursor must
start at the *end* for finished history — every terminal REQ's phase-step(s) marked `done`
with an honest provenance trail, distinct from steps the engine actually drove.

The post-REQ-029 step model is one fused `develop` step per REQ, plus a `validate` step when
the REQ declared an `artifact`/`manual` AC (REQ-030). The seeder marks exactly those.

## Approach

A first-class, dialect-independent `steward seed-ledger` subcommand (Decision 1) — it reads
only converted, schema-valid frontmatter (`id`, `status`), so the *same* command seeds memzy,
ExamEngineer, or any future onboarding. Conversion stays a per-project script (REQ-010);
seeding is uniform.

### New module: `devsteward/profiles/req/seed.py`

```python
def seed_ledger(ledger: Ledger, req_dir: Path) -> list[str]:
    """Seed already-finished history. Returns the newly-seeded REQ ids."""
```

- Lives in the **REQ profile** (it is content-aware: it knows the phase model + terminal
  statuses), alongside `source.py`/`checkpoint.py`.
- Reuses the profile's own derivation so it can never drift from the step source:
  `PHASES` (the one `develop` phase) and `has_validate_step(req)` (REQ-030's
  artifact/manual test). Step ids are built by string from `r.id` — **opaque**, so lettered
  ids (`REQ-099z`, REQ-021) seed via the identical path (Decision 6).
- For each **terminal** REQ (`done`/`dropped`/`superseded` — `ReqFile.is_terminal`): mark
  `REQ-NNN:develop` (and `REQ-NNN:validate` when `has_validate_step`) `done` via
  `Ledger.set_status`, and record one `ledger_seed` provenance event (`req=`, `steps=`) —
  reusing `append_event`, no new state schema (Decision 3).
- **Active/draft REQs are skipped entirely** (Decision 2) — they stay pending so the engine
  still drives them.
- **Idempotent** (Decision 4): a terminal REQ whose `develop` step is already `done` (seeded
  earlier, or genuinely engine-driven) is skipped — no duplicate event, no re-seed, no error.
- Save ordering mirrors `park_decision`: mutate statuses, `save()` once, then append the
  per-REQ events.

### CLI: `steward seed-ledger`

- Resolves the project via `_load_or_die()` (Decision 5) — `ProjectNotFound` →
  `ClickException`, so it errors cleanly with no initialized ledger (AC6). No hidden `init`.
- Constructs `Ledger(cfg.root)`, calls `seed_ledger`, reports the seeded ids (or "nothing to
  seed").

## Files touched

| File | Change |
|------|--------|
| `devsteward/profiles/req/seed.py` | **new** — the `seed_ledger` function |
| `devsteward/cli.py` | new `seed-ledger` command |
| `tests/test_seed_ledger.py` | **new** — AC1–AC6 |

## Out of scope (travels to sibling REQs)

Dialect conversion (REQ-010), re-verification of history (verdict travels from the converted
`status`; the REQ-015 gate never fires on seeding), and the full onboarding pipeline / live
proof (REQ-024 / REQ-062). This REQ ships the command + its tests only.

## Acceptance → test map

| AC | Test |
|----|------|
| AC1 terminal REQs' develop (+validate) → done | `test_seeds_terminal_reqs_done` |
| AC2 active/draft untouched | `test_active_and_draft_reqs_not_seeded` |
| AC3 one `ledger_seed` event/REQ; idempotent | `test_provenance_event_and_idempotent` |
| AC4 fully-terminal corpus → empty work queue | `test_seeded_corpus_yields_no_active_steps` |
| AC5 lettered id seeded via opaque path | `test_seeds_lettered_id_req` |
| AC6 clean error with no ledger | `test_errors_without_initialized_ledger` |
