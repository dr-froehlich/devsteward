# REQ-086 — onboarding machinery repairs from the memzy run

Three independent repairs, one per finding in the
[REQ-062 memzy onboarding report](../reports/2026-08-01-req062-memzy-onboarding-report.md).
They share a REQ because they share a theme and a downstream blocker ([REQ-085](../requirements/REQ-085.md)),
but they touch three disjoint surfaces and are implemented independently.

## Repair 1 — `/onboard` commits the converted corpus before seeding (AC1)

**Surface:** `.claude/skills/onboard/SKILL.md` **only**. That path and
`devsteward/templates/.claude/skills/onboard/SKILL.md` are the *same file*
(`.claude/skills` is a symlink onto the template tree) — edit once, never twice.

**Change:** the pipeline grows a step between convert and seed:

| # | step | gate |
|---|------|------|
| 1 | Convert the REQ corpus | `steward lint` |
| 2 | **Commit the converted corpus** | working tree clean |
| 3 | Seed the ledger | `steward status` (+ `steward lint`, now meaningful) |
| 4 | Stamp the scaffold | — |
| 5 | Reconcile CLAUDE.md | — |

The new §2 states the *reason*: REQ-077's symmetric lint rule compares a seeded `done` step
against the **committed** marker (HEAD frontmatter + HEAD index row). Before the conversion
commit, HEAD still holds the pre-conversion corpus, whose annotated index cells
(`superseded *(by REQ-020)*`) the row regex rejects — so a lint run between `seed-ledger` and
the commit compares against a stale HEAD and reports rows as `ABSENT` that the working tree
has already normalized. With the commit first, every gate in the sequence means what it says
and the operator is never asked to wave a red gate through.

The §1 gate text and the §5 park contract keep their "stop on red" absolutism — the cure is
ordering, not a licence to proceed on red.

**Oracle (stated as the weak one it is, REQ-086 Decision 3):** a content assertion over the
skill text — the commit step exists, sits between convert and seed, and names REQ-077 as the
reason. The decoupled proof is REQ-085's live THermo run. Existing `test_onboard_skill.py`
assertions (four steps in order, gate ordering, merge/scope, park) must stay green: the new
step is *inserted*, the four named headings keep their relative order.

## Repair 2 — `steward sync` seeds `_templates/req.md` (AC2, AC3)

**Surface:** `devsteward/skillsync.py` + the two `cli.py` call sites.

The tracked-artifact model assumes one relpath valid on **both** sides (a same-relative-path
byte copy). The REQ template breaks that assumption: it ships at a fixed
`docs/requirements/_templates/req.md` in the template tree, but lands at
`<requirements_dir>/_templates/req.md` in a consumer, and `requirements_dir` is a REQ-084
config seam (THermo's is the singular `doc/requirements`).

**Change:**

- `Tracked` gains a second path: `relpath` (template side) and `dstpath` (consumer side),
  defaulting to `relpath` so the skills and `STEWARD.md` are unaffected.
- `tracked_artifacts(templates_root, requirements_dir=DEFAULT_REQUIREMENTS_DIR)` appends
  `Tracked("_templates/req.md", docs/requirements/_templates/req.md,
  <requirements_dir>/_templates/req.md)` **iff** the template ships it — engine-derived, same
  as the manual, never a hand-maintained list.
- `classify` / `drift` / `sync` / `seed_lock` thread `requirements_dir` through; `cli.py`
  passes `cfg.requirements_dir` from `status` and `sync`.
- Lock key is `_templates/req.md` — stable regardless of where the consumer puts it.

Everything else is inherited, not re-implemented: missing → seeded and reported in
`synced`; customized (differs from template, no matching lock baseline) → **refused** untouched,
`--force` backs up to `.orig` first; the lock prune keeps the manifest to tracked keys.

**DevSteward's own repo:** it has no `docs/requirements/_templates/` (its index footer links
straight into the template tree), so the new tracked artifact would report `missing` on every
`steward status`. Cure it the way the skills are already cured — a **symlink**
`docs/requirements/_templates → ../../devsteward/templates/docs/requirements/_templates`, so
S == T and the artifact is in-sync with no second copy to drift.

## Repair 3 — the converter reports dropped frontmatter keys (AC4, AC5)

**Surface:** `scripts/convert_reqs.py`, additive only.

`dump_frontmatter` emits `_FIELD_ORDER` and nothing else, so *every* non-schema key is
dropped, not just the known `superseded_by`. The cure is a report, never preservation
(Decision 5): the output schema does not grow and the emitted frontmatter is byte-identical.

- `dropped_frontmatter_keys(frontmatter) -> list[str]` — pure: the source keys `_FIELD_ORDER`
  will not carry, in source order.
- `scan_dropped_keys(src_dir) -> dict[filename, list[str]]` — the per-file corpus scan, read
  from the **source** files (before conversion, which is what makes it observable).
- `main()` prints one line per file to the same operator channel as the prose converter's
  title-conflict and demotion reports.

`convert_corpus`'s signature and return type are **untouched**, which is what keeps REQ-010's
and REQ-017's suites green unchanged (AC5).

## Test file

One new `tests/test_req086_onboarding_repairs.py` with the four named nodes (AC1–AC4); AC5
runs the two existing converter suites unchanged.

## Out of scope

Per the REQ: no preservation of dropped keys, no change to REQ-077's lint rule, no re-run of
the memzy onboarding, and not the THermo retrofit itself (REQ-085).
