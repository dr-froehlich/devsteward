# Plan — REQ-087: the north star lands at bootstrap

Implements [REQ-087](../requirements/REQ-087.md). Three template/skill edits plus one new
regression module. No engine code changes.

## Approach

The defect is entirely in the stamped scaffolding, so the fix is too. Four artifacts move:

| # | File | Change |
|---|------|--------|
| 1 | `devsteward/templates/tests/test_project_initialized.py` | **new** — the shipped initialization check (stdlib + pytest only) |
| 2 | `devsteward/templates/docs/requirements/REQ-001.md.tmpl` | AC1 test `{{TEST_COMMAND}}` → `python -m pytest tests/test_project_initialized.py` |
| 3 | `.claude/skills/bootstrap/SKILL.md` (= `devsteward/templates/.claude/skills/bootstrap/SKILL.md`, one inode) | §3 closes with `steward checkpoint` |
| 4 | `tests/test_req087_north_star_bootstrap.py` | **new** — the five acceptance tests |

### 1. The shipped check

`tests/test_project_initialized.py` asserts the three invariants REQ-001 actually claims —
scaffold coherence, ledger initialized, no surviving placeholder. Hard constraints:

- **stdlib + pytest only.** No `ruamel.yaml`, no `import devsteward`, no project imports.
  It must pass from a `git archive` extract with an empty environment (REQ-063's capture
  check runs it exactly there). The two scalar config keys it needs (`requirements_dir`,
  `index_file`) come from a ~10-line line scanner over `.devsteward/config.yaml`, with the
  documented defaults as fallback.
- **root-relative.** `Path(__file__).resolve().parents[1]` — correct in the repo and in an
  extract, with no cwd assumption.
- **self-exempt placeholder scan.** The scan walks committed text files for
  `{{[A-Z_]+}}`; it skips its own file (it necessarily *describes* the pattern) and skips
  `_templates/` (the REQ/plan/scenario stencils legitimately keep their tokens).

### 2/3. Template + skill

REQ-001's AC becomes the narrow check. `/bootstrap` §3 gains a final step: after the first
commit on `dev`, run `steward checkpoint` and report the landed step. The skill file and
the template are the same inode (`ls -i` confirms) — edit once, never twice.

### 4. The acceptance tests

One module, five tests, mirroring AC1–AC5. The shared fixture stamps a project with
`steward new` into `tmp_path`, fills placeholders the way `/bootstrap` would, `git init`s
on `dev`, and commits — i.e. the state at the moment bootstrap calls `steward checkpoint`.

- `test_initialization_check_passes_from_bare_extract` (AC1) — `git archive` the committed
  skeleton into a second dir, run the shipped test there. Guards the DocSteward failure.
- `test_stamped_skeleton_lands_req001_via_checkpoint` (AC2) — run `steward checkpoint`;
  assert ledger step `done`, REQ-001 `status: done` with `completed:`, index row `DONE`,
  the flip in the same commit as the code, clean tree after.
- `test_no_eligible_step_after_bootstrap` (AC3) — `steward status` reports nothing
  eligible. Also asserts the *pre-fix* shape was eligible, so the test would have failed
  before the fix.
- `test_initialization_check_fails_on_broken_skeleton` (AC4) — three independent
  corruptions (index/frontmatter status disagreement, removed `state.yaml`, surviving
  placeholder), each must red the shipped test. Disconfirmability.
- `test_shipped_contract_is_coherent` (AC5) — template REQ-001 names the check and no
  longer references `{{TEST_COMMAND}}`; `templates/tests/test_project_initialized.py`
  exists; both bootstrap skill copies instruct `steward checkpoint`.

Subprocess calls use `sys.executable -m pytest` and the resolved `steward` console script,
per the `python -m pytest` rule (REQ-040).

## Risks

- ~~AC2/AC3 drive `steward checkpoint` over a temp repo — the profile of the known
  intermittent clean-tree flake. Re-run before diagnosing a lone red.~~ **Superseded by
  REQ-088**: that flake was a real engine defect (git's stat cache missing the size-preserving
  `open` → `done` flip inside one second) and is fixed. Diagnose a lone red, don't re-run it.
- The stamped test lands in the package tree at `devsteward/templates/tests/`. DevSteward's
  own `testpaths = ["tests"]` keeps it out of this project's collection; verified, not
  assumed.

## Out of scope

No engine change, no lint rule, no migration command, no `/onboard` audit (REQ-087
Decision 7). The DocSteward retrofit is a develop-session obligation (Decision 8), carried
out in this session but deliberately not an acceptance criterion.
