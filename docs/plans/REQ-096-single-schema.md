# Plan — REQ-096: delete the stamped schema copy

**REQ:** [REQ-096](../requirements/REQ-096.md) · one fused develop checkpoint, no concept
phase, no lab, no System-Test phase (three `regression` ACs).

## Approach

The smallest possible change that closes the drift permanently: remove the duplicate,
change no stamping code, add no guard. The stamper is a generic `src.rglob("*")` copy of
the whole template tree (`cli.py` `new`), so deleting the directory is sufficient — the
file simply stops existing and stops being copied. Nothing else in the package references
the path.

The one non-obvious piece of work is REQ-095's AC4 test, which is the only test in the
suite that reads the stamped schema (it asserts the retired-`develop:` description in
*both* copies). It is updated to assert over the surviving copy, so the guarantee keeps
its full strength over the file that still exists (REQ-096 decision 6).

## 1. Delete the duplicate

`git rm -r devsteward/templates/docs/requirements/schema/`

That leaves the template's requirements tree as `REQ-001.md.tmpl`,
`REQUIREMENTS_INDEX.md`, `_templates/`, `scenarios/`. No code change accompanies it:

- `cli.py`'s `new` copies whatever the template tree contains.
- `skillsync.py`'s tracked set is engine-derived (skills + `STEWARD.md` +
  `_templates/req.md`) and never named the schema.
- `lint.py` reads `files("devsteward") / "schema"` — the packaged copy — in every project.

## 2. Record the invariant (engine-dev doctrine only)

Add one bullet to **`/CLAUDE.md`** under *House conventions*, after the REQ-094 bullet:
an artifact shipped in two locations is unified at the filesystem — inode-shared or
symlinked — never duplicated as a second file, because a copy is a drift generator; and
name the existing instances (`_templates/req.md` is one inode, `STEWARD.md` is a symlink,
the bundled skills are inode-shared) so the pattern is recognisable rather than abstract.

It goes **only** here. Not `CLAUDE.md.tmpl`, not `STEWARD.md`, not the handbook, not a
bundled skill: this governs developing DevSteward, and the skills are inode-shared with
their templates, so a rule added to a shipped surface ships to every consumer (REQ-096
decision 3, the standing dogfooding boundary).

## 3. Tests

**Updated — `tests/test_req095_develop_key_retired.py`:** its AC4 test loops over two
schema paths asserting each carries the `RETIRED (REQ-095)` description and the
`{fused, split}` enum. The loop becomes the single surviving path. Its package-wide sweep
already skips files named `req.schema.json`, so that half needs no change.

**New — `tests/test_req096_single_schema.py`**, owning the three ACs:

| AC | Test | Oracle |
|---|---|---|
| AC1 | `test_package_ships_exactly_one_schema` | `rglob("req.schema.json")` over the installed package returns exactly `[devsteward/schema/req.schema.json]`, and the stamped directory does not exist. |
| AC2 | `test_stamped_project_has_no_schema_dir_and_lints` | Stamp a real project with `CliRunner().invoke(main, ["new", …])` (the `test_new.py` pattern), assert no `docs/requirements/schema/`, and assert `lint(load_config(target))` reports no `schema:` problems — the deletion removed nothing lint read. |
| AC3 | `test_claude_md_records_the_one_file_invariant` | `/CLAUDE.md` states the invariant; the shipped surfaces (`CLAUDE.md.tmpl`, `STEWARD.md`, the handbook chapters, the bundled skills) do **not** — pinning decision 3's boundary in both directions. |

AC2 is the one with teeth: it exercises the real stamper end-to-end and would fail if the
schema were load-bearing for a fresh project.

## Verification

`python -m pytest` green in full (via `.venv/bin/python` — system Python lacks `ruamel`),
plus `steward lint`. Close with `steward checkpoint REQ-096 develop`.

## Out of scope

The packaged schema's *content* (REQ-096 out-of-scope note): this REQ deletes a duplicate
and does not revisit what the schema says. The four consumer repos keep their inert stale
copies (decision 4) — no sweep.
