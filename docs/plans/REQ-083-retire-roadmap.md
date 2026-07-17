# REQ-083 — Retire the roadmap artifact

Pure subtraction: delete the stamped `ROADMAP.md`, the `roadmap_file` config seam, the
roadmap steps in the stamped skills, and the doctrine sentences that describe the
artifact. No deprecation markers, no replacement prose (decision 1). Two regression tests
pin the result.

## Surface (the complete reference sweep)

`grep -ril roadmap` over the package plus the doctrine text — everything below is touched
in this one checkpoint.

| File | Change |
|---|---|
| `devsteward/templates/docs/requirements/ROADMAP.md` | **delete** — a `steward new` project never receives one |
| `devsteward/config.py` | drop the `roadmap_file` field, the `roadmap_path` property, the `from_dict` `data.get("roadmap_file", …)` line |
| `devsteward/templates/.devsteward/config.yaml.tmpl` | drop the `roadmap_file:` key |
| `.devsteward/config.yaml` (our own) | drop the `roadmap_file:` key |
| `devsteward/profiles/req/__init__.py` | docstring "REQ/ROADMAP files" → "REQ files" |
| `templates/.claude/skills/intake/SKILL.md` | drop the roadmap emit bullet + the roadmap half of the one-commit sentence |
| `templates/.claude/skills/bootstrap/SKILL.md` | "index and ROADMAP" → index only |
| `templates/.claude/skills/onboard/SKILL.md` | "richer artifacts (its ROADMAP, …)" → generic living docs; out-of-scope bullet names scenarios only |
| `templates/CLAUDE.md.tmpl` | intake parenthetical → frontmatter + index |
| `CLAUDE.md` (own) | status bullet keeps index↔frontmatter content, loses the roadmap clauses; branching bullet → frontmatter + index |
| `README.md` | "dependency-ordered roadmap" → the `depends_on` graph; "REQ/ROADMAP files" → REQ files |
| `handbook/_00-method.qmd` | item 3 keeps the DAG + status-one-source content, loses the roadmap view/drift sentences |
| `handbook/_03-workflow.qmd` | branching sentence → frontmatter + index |
| `handbook/_04-skills.qmd` | `/intake` emit → REQ + index row + scenarios |
| `docs/requirements/ROADMAP.md` (own, 616 lines) | **delete** (decision 4) |
| `tests/test_onboard_skill.py` | AC4 assertion drops the roadmap token, keeps scenarios |

**Deliberately untouched:** `tests/fixtures/**` and `tests/test_convert_reqs.py` roadmap
strings — foreign input corpus, not doctrine (decision 3). `.devsteward/evidence/**` —
historical artifacts. `docs/plans/*`, `docs/reports/*`, prior `REQ-*.md` — the archive of
what was true when written. `docs/requirements/REQ-001.md` — frozen; its
"dependency-ordered roadmap" promise is the `depends_on` graph, which stays.

## Hardlink hazard

`.claude/skills/{intake,bootstrap,onboard}/SKILL.md` and their
`devsteward/templates/.claude/skills/…` counterparts are **one inode each** (verified this
session: 1824074 / 1823978 / 380364). Edit the template path only — the repo copy follows.
Never apply the same edit twice.

## Config seam removal (requirement 2 / decision 2)

`load_config` builds `Config` from `data.get(...)` per known key and keeps the whole
mapping in `raw`. Deleting the field is therefore sufficient for legacy tolerance: a
consumer `config.yaml` still carrying `roadmap_file:` parses, the key lands in `raw`, and
nothing reads it. No warning path, no migration verb, no `**data` splat to guard.

## Tests

**`tests/test_req083_roadmap_retired.py` (AC1)** — meta-test over the package tree,
scoped to `devsteward/` so it pins the shipped artifact and cannot creep back via a
template edit (`tests/fixtures` are out of scope by construction — the sweep never leaves
`devsteward/`):

1. case-insensitive sweep: no file under `devsteward/` contains `roadmap`, failing with
   the offending `path:line` list so a regression is diagnosable at a glance;
2. no `ROADMAP.md` anywhere under `devsteward/templates/`;
3. the stamped intake skill's emit section names REQ + index and nothing roadmap-shaped.

**`tests/test_req083_legacy_config_key.py` (AC2)** — config regression:

1. `Config` exposes neither `roadmap_file` (dataclass field) nor `roadmap_path`
   (property) — asserted against `dataclasses.fields` + the class attrs, not an instance;
2. `load_config` over a tmp project whose `config.yaml` carries a legacy `roadmap_file:`
   key succeeds; the value is present in `raw` and absent as an attribute.

Both are `check: regression`. The full-suite gate covers the `test_onboard_skill.py` edit.
