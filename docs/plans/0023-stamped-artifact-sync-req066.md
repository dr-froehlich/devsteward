# Plan 0023 — REQ-066: sync covers STEWARD.md (engine-owned stamped artifacts)

Generalize REQ-036's bundled-skill drift machinery from "bundled skills" to **engine-owned
stamped artifacts** (the four `.claude/skills/<name>/SKILL.md` files **plus** the root
`STEWARD.md`), so the black-box manual gets the same provenance / drift-signal / refresh
the skills got. The mechanism is reused verbatim; only its *scope* generalizes — prefer
subtraction over a parallel one-off tracker.

## Mechanism (already general, only scope was skills-specific)

`skillsync.py` is a three-hash content drift tracker per artifact: **S** stamped (consumer),
**L** lock baseline, **T** installed template; buckets `in-sync / stale / customized /
both-moved / missing`. Only the *enumeration* (`bundled_skill_names`), the lock filename
(`skills.lock`), and the verb/signal strings were skills-bound.

## Files & changes

### `devsteward/skillsync.py` — generalize scope
- New `Tracked(key, relpath)` artifact descriptor; `relpath` is relative to **both** consumer
  root and templates root (skills: `.claude/skills/<name>/SKILL.md`, key=skill name; manual:
  `STEWARD.md`, key=`STEWARD.md`).
- `tracked_artifacts(templates_root)` — engine-derived: discovered skill dirs + `STEWARD.md`
  **iff the template ships it** (no hand-maintained list). Keep `bundled_skill_names` etc.
  (REQ-036 helpers/tests still use them).
- Lock rename: `LOCK_FILENAME = "stamped.lock"`, legacy `skills.lock` **read** when the new
  file is absent (`read_lock`), and the next `write_lock` **migrates** (writes `stamped.lock`,
  removes the legacy file). No consumer's provenance is lost (Decision 2 / AC4).
- `classify` / `drift` / `seed_lock` / `sync` iterate `tracked_artifacts` keyed by `key`,
  reading/writing each artifact at its `relpath`. `SkillDrift` → `Drift` (alias kept).

### `devsteward/cli.py`
- `new` already calls `seed_lock` → now seeds `STEWARD.md` too (Decision 5). `_stamp` copies
  `STEWARD.md` **verbatim** (like skills) so it byte-matches the template (drift premise).
- `status` drift section: label "stamped artifacts", hint **`steward sync`** (Decision 3).
- Verb rename `sync-skills` → **`sync`** with `sync-skills` kept as an alias
  (`main.add_command(sync, name="sync-skills")`). Output names "engine-owned artifacts".

### `.claude/skills/onboard/SKILL.md` (Decision 6)
- §3 scaffold-stamp step runs `steward sync` to seed the generalized lock, so a retrofitted
  project ends with `STEWARD.md` present + a populated `stamped.lock` — same baseline a
  `steward new` project gets — while `sync`'s customized-refusal preserves any same-named
  artifact the project already owns (merge, never overwrite).

### Tests — `tests/test_sync_skills.py`
- AC1 `test_new_seeds_stamped_lock_includes_manual_in_sync`
- AC2 `test_missing_steward_manual_acquired_by_sync`
- AC3 `test_steward_manual_stale_and_customized_buckets`
- AC4 `test_legacy_skills_lock_read_and_migrated_and_alias`
- AC5 `test_onboard_sync_seeds_full_lock_and_preserves_existing`
- Update REQ-036 tests for the lock now including `STEWARD.md` and the status hint now naming
  `steward sync`.
- AC6 = manual FlowSteward closure → **validate** phase (this develop land defers).
