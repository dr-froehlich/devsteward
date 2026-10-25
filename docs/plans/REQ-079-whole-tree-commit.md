# Plan — REQ-079: reestablish the whole-tree code commit

Subtract REQ-076's boundary-delta commit scoping (and REQ-077's `include` force-stage,
dead once nothing subtracts); keep REQ-077's guards (post-land clean-tree assertion,
symmetric HEAD-reading lint); codify one-session-at-a-time as doctrine.

## Engine changes

- `devsteward/core/git.py`
  - `_stage_code()` → parameterless: `git add -A -- ':(exclude).devsteward'` (whole tree,
    untracked included). Delete the baseline subtraction and the `include` force-add.
  - `commit_code(message)` / `write_code_tree()` lose `baseline`/`include`.
  - `dirty_paths()` stays — it now serves the REQ-077 clean-tree assertion only
    (docstring updated). `_parse_status_paths` stays with it.
- `devsteward/core/seams.py` — `GitTopology` protocol: `commit_code(message)`,
  `write_code_tree()`; `dirty_paths` doc re-anchored to the assertion.
- `devsteward/core/executor.py`
  - Delete `_session_commit_scope` and `self._commit_baseline`; `_drive_step` keeps only
    the `transaction(...)` context.
  - `_land_checked`: `_capture_gap(step)` (no baseline); on certify still call
    `on_verified(step)` (the flip write) but drop the returned-paths → `include`
    plumbing; `_commit(step)`; `_assert_committed_clean(step)`.
  - `_assert_committed_clean(step)`: nothing is allowed dirt — any leftover after the
    code commit raises (transaction rolls back). Simplified from the
    `baseline − include` allowance.
  - `_capture_gap(step)` / `_stage_and_write_tree()`: drop `baseline`.
  - `_commit(step)`: drop `baseline`/`include` (drop the now-unused `os.path.relpath`
    use if `os` becomes unused).
- `devsteward/profiles/req/validate.py` — `guided_validate` drops the
  `ex._session_commit_scope()` wrapper.
- `devsteward/profiles/req/checkpoint.py` — `ReqDoneFlipper.__call__` keeps flipping
  before the commit; returned paths no longer feed a force-stage (docstring updated;
  return kept as informational or dropped to `None` — pick whichever leaves callers
  simplest).

## Tests

- **Delete** `tests/test_commit_scoping.py` (REQ-076's ACs — they assert the defect now).
- **New** `tests/test_req079_whole_tree_commit.py` (reuses the `test_commit_integrity`
  real-git harness):
  - `test_commit_stages_prior_attempt_work` (AC1) — prior-attempt dirt (one modified
    tracked + one untracked file) + a fresh session file all land in `commit_code`'s
    commit; `.devsteward/` excluded; `commit_code`/`write_code_tree` signatures expose
    no scoping parameters.
  - `test_headless_land_commits_whole_tree_and_flip` (AC2) — real headless land
    (`advance_once` over `AuthoringRunner`) with prior-attempt dirt present lands dirt +
    session files + `status: done` flip + index `DONE` in the one commit, clean tree,
    no `capture_gap` event.
  - `test_capture_gate_tree_is_whole_tree` (AC3) — with pre-existing dirt,
    `write_code_tree()` sha == the committed tree sha (`rev-parse <sha>^{tree}`).
- **Adapt** `tests/test_req077_atomic_flip.py`: drop AC2's scoped-staging test
  (superseded — the scenario is subsumed by the new AC2 above); AC1 + AC3 stay; module
  docstring rewritten. `tests/test_lint_marker_ledger.py` unchanged (AC4 runs both).
- **Adapt** `tests/conftest.py` `FakeGitTopology` (`commit_code(message)`,
  `write_code_tree()`) and the `AuthoringRunner` docstring.

## Docs / registry

- `REQ-076.md` `status: done → superseded` + index row `SUPERSEDED` (REQ-079 carries
  `supersedes: REQ-076`).
- `REQ-077.md` AC2: annotate as superseded by REQ-079, re-point its `test:` at the
  superseding node-id so the AC stays executable.
- Doctrine (Decision 3): STEWARD.md (edit `devsteward/templates/STEWARD.md` — the repo
  root file is a symlink, one inode) + `devsteward/handbook/_02-engine.qmd`: exactly one
  engine session (interactive or headless) per repo at a time; parallel sessions are
  operator error with undefined results; no lock machinery.

## Order

1. Engine subtraction (git.py, seams.py, executor.py, validate.py, checkpoint.py).
2. Test surgery (delete/new/adapt) → `python -m pytest` green.
3. Registry + doctrine edits → `steward lint` green.
4. `steward checkpoint REQ-079 develop`.
