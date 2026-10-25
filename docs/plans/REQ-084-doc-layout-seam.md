# Plan — REQ-084: doc-layout config seams + onboard leaves the stamped set

Two halves, one REQ. Half A gives the consumer's doc layout a full seam (`plans_dir`,
`concepts_dir`) honored by the land gates and by the prose that tells sessions where to
write. Half B takes the operator-only `onboard` skill out of the stamped set.

## Correction to the intake decisions (recorded before building)

Intake's Decision 2 said `/onboard` step 3 runs `steward new --force`, so the fix belonged
in the stamp. That premise is false — the skill says in so many words *"onboard does **not**
run `steward new`"*; step 3 hand-merges the scaffolding and runs `steward sync` for the
engine-owned artifacts. recipes confirms it: the corpus went to `requirements/` (the session
honored `requirements_dir`) while plans went to `docs/plans/` — the one path with no key to
honor. Operator's ruling at the fork (2026-07-30): **drop the `steward new` change**; a
greenfield target cannot carry a config before the stamp writes one, so honoring a
pre-existing config has no present consumer. The onboard skill's step 3 owns the placement.

Second finding, for the Context: REQ-024 **Decision 2** already ruled that `onboard` "Lives
in DevSteward's own `.claude/skills/`, not in `templates/` … Bundling it would ship dead
scaffolding." The develop commit that recorded that decision (`c7ce317`) added the template
copy anyway, and `tests/test_onboard_skill.py`'s own docstring has asserted the correct state
in prose ever since. Half B is a regression fix against a standing decision.

## Half A — the doc-layout seam

**`devsteward/config.py`**
- New loaded fields `plans_dir: str = "docs/plans"` and `concepts_dir: str = "docs/concepts"`,
  read in `load_config` via `data.get(...)` (legacy configs unaffected, REQ-084 decision 7).
- The resolved-`Path` properties are renamed `plans_path` / `concepts_path`. The dataclass
  cannot carry a field and a property of the same name, and the existing convention is exactly
  this split: `requirements_dir` (the raw key) → `req_dir` (resolved), `index_file` →
  `index_path`. Deviates from the REQ's "call sites untouched" parenthetical — two call sites,
  both in `build.py`; the naming collision is worth more than the churn saved.

**`devsteward/profiles/req/checkpoint.py`**
- `PlanArtifactGate(plans_dir, display=None)` and `ConceptArtifactGate(concepts_dir, req_dir,
  display=None)`: `display` is the configured path *relative to the repo root*, defaulting to
  `Path(...).name` so existing direct constructions keep today's message. All three refusal
  messages quote `display` instead of `.name` (REQ-084 decision 4).

**`devsteward/build.py`** — pass both: `PlanArtifactGate(cfg.plans_path, cfg.plans_dir)`,
`ConceptArtifactGate(cfg.concepts_path, cfg.req_dir, cfg.concepts_dir)`.

**`devsteward/templates/.devsteward/config.yaml.tmpl`** — document `plans_dir`/`concepts_dir`
next to `requirements_dir`, naming the mkdocs case they exist for.

**Prose (the half that makes the seam usable).** `templates/.claude/skills/{intake,advance,
bootstrap}/SKILL.md` and `templates/STEWARD.md` stop naming literal doc paths and point at the
configured dirs (`.devsteward/config.yaml`), keeping the conventional layout as a stated
*default*. Same edit for the engine repo's own `.claude/skills/onboard/SKILL.md` and the
handbook chapters `_01`/`_02`/`_03`. The repo's `.claude/skills` is a symlink onto the template
tree, so each skill has exactly one file — edit it once, in `templates/`.

**`.claude/skills/onboard/SKILL.md` step 3** additionally gains the placement duty: write
`plans_dir`/`concepts_dir` (and `requirements_dir`/`index_file`) into `.devsteward/config.yaml`
**before** copying any scaffolding, then place every doc artifact at those configured paths —
never under `docs/` unless that is what the config says. This is what recipes needed.

## Half B — onboard leaves the stamped set

**Correction, made while building.** The plan's first version said `git rm` the template copy
because the repo's skills are hardlinked twins. They are not: `.claude/skills` is a **single
symlink** to `devsteward/templates/.claude/skills` (git blob mode `120000`). Removing the
template path removed `/onboard` from DevSteward itself — observed, then reverted. Operator's
ruling: keep the file where it is and **filter by name** ("keep it simple"); a per-skill-symlink
restructure was explicitly rejected.

- `skillsync.OPERATOR_ONLY = frozenset({"onboard"})` plus `is_operator_only(rel)`.
- `bundled_skill_names()` drops operator-only skills, so `tracked_artifacts()` — and with it
  `sync`, `drift`, `status`, the lock — never sees `onboard`.
- `cli._stamp()` skips any path inside an operator-only skill directory, so `steward new`
  stamps the four consumer skills and not the fifth.
- A meta-test pins both directions: `onboard` excluded, the other four still shipped.
- `skillsync.sync()` currently seeds its lock from `read_lock(root)` and only ever *adds*
  keys, so a retired artifact's key would live in a consumer's `stamped.lock` forever. Build
  the written lock from the tracked artifacts only — dead keys are pruned on the next sync
  (REQ-084 decision 6). Nothing on disk is deleted; `drift()` already ignores untracked files.

## Tests

`tests/test_req084_doc_layout_seam.py`
- `test_config_keys` — non-default keys resolve under the root; omitted keys give the
  defaults; a legacy config (neither key) loads.
- `test_gates_follow_config` — over a tmp repo with `requirements/plans` + `requirements/
  concepts`: both gates accept the deliverable at the configured path, refuse the same file at
  `docs/plans` / `docs/concepts`, and every refusal contains the root-relative configured path
  (asserting the bare last segment is *not* what the message says).
- `test_onboard_skill_places_docs_by_config` — the operator skill's step 3 tells the session to
  write the doc-path keys before stamping and to place artifacts at the configured paths.
- `test_no_hardcoded_doc_paths_in_stamped_prose` — no `docs/plans` / `docs/concepts` literal in
  any `templates/.claude/skills/*/SKILL.md` or `templates/STEWARD.md`; `docs/requirements`
  only in a line that marks it as the default. Meta-test, so the pin survives later edits.

`tests/test_req084_onboard_untracked.py`
- `test_onboard_left_the_stamped_set` — `bundled_skill_names()`/`tracked_artifacts()` exclude
  `onboard` and still name the four consumer skills; a `steward new` stamp produces those four
  and no `.claude/skills/onboard`; the operator copy is still readable and still declares
  itself an operator tool.
- `test_stray_onboard_is_inert` — fixture consumer with a stray skill dir + an `onboard` lock
  key: `drift()` names it nowhere, `sync()` neither refuses nor refreshes it, the file's bytes
  are unchanged, and the lock sync writes has exactly the tracked keys.

## Order

config → gates → build wiring → template config docs → prose sweep → OPERATOR_ONLY filter +
sync lock pruning → tests → `steward lint` → `steward checkpoint REQ-084 develop`.
