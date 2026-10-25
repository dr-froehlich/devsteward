# Plan 0022 — REQ-036: `steward sync-skills` (bundled-skill drift)

Keep a consumer's stamped bundled skills current with the installed engine, and surface
when they are not. Provenance manifest (`.devsteward/skills.lock`) → drift detection →
`steward status` signal → `steward sync-skills` fix. Closes REQ-034 Finding 50.

## The drift model

For each engine-owned bundled skill, three reference points, by sha256 of file bytes:

- **S** — the *stamped* file: `<root>/.claude/skills/<name>/SKILL.md`
- **L** — the *lock* record: `<root>/.devsteward/skills.lock[name]`
- **T** — the installed *template*: `<templates>/.claude/skills/<name>/SKILL.md`
  (`templates` = the engine's bundled `templates/`, i.e. `_package_templates()`)

Buckets (Decision 2 / AC4 matrix):

| S | L | T | bucket | meaning |
|---|---|---|--------|---------|
| — | * | * | `missing` | not stamped at all |
| =T | * | =T | `in-sync` | stamped already byte-matches the installed template |
| =L | ≠L | — | `stale` | untouched since stamp; template advanced — **safe to refresh** |
| ≠L | =L | — | `customized` | consumer edited the stamped copy; template unchanged |
| ≠L | ≠L | — | `both-moved` | both diverged from the lock baseline |

`in-sync` is keyed on **S == T** (not strictly S==L==T): a stamped file that already
matches the installed template needs no action, even with a missing/stale lock — this is
also what keeps DevSteward's own hardlinked repo skills quiet, and gives a sane fallback
when there is no lock baseline yet (differs-from-template-with-no-lock → `customized`, the
conservative no-clobber bucket).

## Stamp fix (prerequisite)

`_stamp` currently substitutes `{{TODAY}}` everywhere — including inside
`bootstrap/SKILL.md`, where `{{TODAY}}` is *literal instruction text* ("set `{{TODAY}}` to
today's date"). That both corrupts the stamped skill and makes S ≠ T from day one. Fix:
**copy files under `.claude/skills/` verbatim** (no placeholder substitution). Skills are
pure engine behavior meant to track the engine byte-for-byte.

## Pieces

1. **`devsteward/skillsync.py`** (new) — pure, git-free, injectable `templates_root`:
   - `bundled_skill_names(templates_root)` — engine-derived from `<t>/.claude/skills/*/SKILL.md`.
   - `read_lock(root)` / `write_lock(root, mapping)` — `.devsteward/skills.lock`, JSON map
     `{name: sha256}`, sorted keys, trailing newline (committed registry provenance).
   - `_bucket(s, l, t)` / `classify(root, templates_root) -> list[SkillDrift]`.
   - `seed_lock(root, templates_root)` — record each template hash (for `steward new`).
   - `sync(root, templates_root, force) -> SyncResult` — refresh `stale`/`missing`, update
     lock; `customized`/`both-moved` refused unless `force` (then back up `SKILL.md.orig`
     first, refresh, re-record). Never a prose merge.

2. **`cli.py`**
   - `_stamp`: skip substitution under `.claude/skills/`.
   - `new`: after `Ledger.init`, `skillsync.seed_lock(target, src)`.
   - `status`: append non-blocking drift lines (warn per non-in-sync skill → point at
     `steward sync-skills`). Never fails a gate (Decision 3).
   - new `sync-skills` command (`--force`).

3. **`tests/test_sync_skills.py`** — AC1–AC4 (headless, synthetic stamped projects in tmp).

## Acceptance

- AC1 `test_new_seeds_lock_and_reports_in_sync`
- AC2 `test_stale_skill_detected_then_synced`
- AC3 `test_customized_skill_not_clobbered_without_force`
- AC4 `test_drift_bucket_matrix`
- AC5 manual (FlowSteward) — validate phase, deferred land.
