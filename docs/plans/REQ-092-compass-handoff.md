# REQ-092 — the compass may be handed on

Plan for [REQ-092](../requirements/REQ-092.md). One fused develop checkpoint; no concept
phase, no lab, no System-Test phase (both criteria are `regression`).

## The defect in one line

`devsteward/lint.py` rule 6 refuses any `dropped`/`superseded` REQ-001 unconditionally,
which is precisely the move `handbook/_00-method.qmd` rule 2 prescribes — so a project
whose direction changes (DriveSteward REQ-016) cannot land its own supersede.

## Data shapes

Nothing new on disk. The rule reads two existing frontmatter fields:

- `supersedes:` — `null | "REQ-NNN" | [REQ-NNN, …]` (schema already allows all three; lint
  check 2 already normalizes it the same way).
- `tags:` — a unique string array; the marker value is the literal `north-star`, already
  carried by devsteward's own REQ-001 and DriveSteward's REQ-016.

No schema change (REQ-092 Decision 8).

## Interfaces

`devsteward/profiles/req/reqfile.py` — two properties on `ReqFile`, matching the existing
`depends_on` / `concept_refs` accessors:

- `supersedes -> list[str]` — normalizes the string/list/null union into a list, so lint
  check 2 and the new rule share one reading of the field.
- `tags -> list[str]`.

`devsteward/lint.py`:

- module-level `NORTH_STAR_TAG = "north-star"` and `NORTH_STAR_ID = "REQ-001"`.
- a private `_live_compass(reqs) -> ReqFile | None` that walks the supersedes graph
  outward from REQ-001 breadth-first — a REQ is an heir when its `supersedes` contains
  REQ-001 or contains another heir — visiting each id at most once (cycle-safe), and
  returns the first heir that is **live** (status not in `dropped`/`superseded`) **and**
  carries the tag.
- rule 6 becomes: silent unless REQ-001 exists *and* its status is `dropped`/`superseded`
  *and* `_live_compass` returns `None`; the one problem names both conditions.
- the docstring's numbered check 6 is rewritten to state the rule as implemented.

`tests/conftest.py` — `write_req` gains `supersedes=None` and `tags=()` keyword arguments
(additive, defaults reproduce today's output byte-for-byte).

## Files touched

| File | Change |
|---|---|
| `devsteward/lint.py` | rule 6 + docstring + the chain walk |
| `devsteward/profiles/req/reqfile.py` | `supersedes` / `tags` properties |
| `tests/conftest.py` | `write_req(supersedes=…, tags=…)` |
| `.claude/skills/intake/SKILL.md` (= stamped template, one inode) | orient by the live compass |
| `.claude/skills/bootstrap/SKILL.md` (= stamped template, one inode) | the heir must carry the tag |
| `tests/test_req092_compass_handoff.py` | new — both ACs |

## Tests

`tests/test_req092_compass_handoff.py`, synthetic requirement dirs via `write_req` /
`write_index` (the `tests/test_lint.py` house pattern), one case per branch:

1. live REQ-001 → silent (today's behaviour preserved);
2. `superseded` REQ-001 + live tagged heir → silent;
3. `superseded` REQ-001 + heir with the supersede but no tag → one problem;
4. `superseded` REQ-001 + tagged heir that is itself `superseded`, no further heir → one problem;
5. `superseded` REQ-001, no heir at all → one problem;
6. `dropped` REQ-001 judged identically (a live tagged heir passes; none refuses);
7. two-hop chain 001 → A (superseded) → B (live, tagged) → silent;
8. a `supersedes:` list containing REQ-001 among others counts as an heir;
9. a supersedes cycle terminates (no hang, refusal is reported);
10. `test_surfaces_and_self_lint` — devsteward's own repo lints green, both skills carry
    the chain-following instruction, and each repo skill file is the same inode as its
    stamped template.

## Order of work

1. `ReqFile` properties; point lint check 2 at `r.supersedes` so there is one reader.
2. The rule + docstring.
3. `conftest` kwargs, then the test file.
4. Skill wording (edit the repo path only — the template is the same inode).
5. `python -m pytest`, `steward lint`, then `steward checkpoint REQ-092 develop`.
