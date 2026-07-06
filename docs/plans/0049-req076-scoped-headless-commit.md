# Plan 0049 — REQ-076: scope the headless code commit to what the command authored

Covers **REQ-076**. Source: FlowSteward REQ-081 postmortem (2026-07-05) — a background
`steward validate` for REQ-090 swept a concurrent interactive session's in-progress REQ-081
files into a commit labelled `REQ-090:validate`, silently violating same-commit discipline.

## Approach

The engine already snapshots the transaction boundary (`HEAD` at entry, *before* `claude -p`
runs). At that boundary anything already dirty belongs to someone else; everything the session
dirties afterward is this command's work. So: **record the dirty-path set at the boundary and
commit only the delta.** No worktree, no lock (that would solve an information-flow problem
with git topology — the REQ-047 anti-pattern, `[[trunk-based-pivot-req047]]`).

## Data shape

- **baseline** — `set[str]` of code paths (relative, `.devsteward/` excluded) dirty at the
  boundary, from `git status --porcelain -z -- :(exclude).devsteward`.
- **delta to stage** — `dirty_paths_now − baseline`, sorted for determinism.

## Files touched

- `devsteward/core/git.py`
  - `_parse_status_paths(z)` (module) — parse porcelain `-z` (handles rename/copy source token).
  - `GitCli.dirty_paths() -> set[str]` — the boundary baseline probe.
  - `GitCli._stage_code(baseline)` — `None` → today's whole-tree `add -A -- :(exclude).devsteward`;
    a set → `git reset -q` (rebuild index from HEAD, so a pre-staged concurrent file can't ride)
    then `git add -A -- <delta>`.
  - `GitCli.commit_code(message, baseline=None)` — stage via `_stage_code`, then commit.
  - `GitCli.write_code_tree(baseline=None)` — stage via `_stage_code`, `write-tree` → sha (the
    capture-gate mirror, so the gate tree and the commit are built from *one* staging routine).
- `devsteward/core/executor.py`
  - `self._commit_baseline: set[str] | None` + `_session_commit_scope()` contextmanager
    (captures the baseline at entry, restores on exit).
  - `_drive_step` enters the scope (batch develop **and** batch validate — the sweeper was a
    background/headless `steward validate`).
  - `_land_checked` reads `self._commit_baseline`, threads it to `_capture_gap` and `_commit`.
  - `_capture_gap(step, baseline)` → `_stage_and_write_tree(baseline)` → delegates to
    `self.git.write_code_tree(baseline)` (duck-typed; a fake without it no-ops the self-check).
  - `_commit(step, baseline)` → `git.commit_code(message, baseline)`.
- `devsteward/profiles/req/validate.py` — `guided_validate` (attended `steward validate`, shape A,
  not wrapped by `_drive_step`) enters `ex._session_commit_scope()`.
- `devsteward/core/seams.py` + `tests/conftest.py::FakeGitTopology` — `dirty_paths`,
  `write_code_tree`, and the `commit_code(baseline=None)` signature.

## Out of scope (Decision 3, REQ Notes)

`steward checkpoint` (no `claude`; dirty-at-entry) passes **no** baseline → keeps today's
whole-tree stage; scoping it would stage nothing. `commit_ledger` (`.devsteward/`-scoped) and
the transaction rollback `reset_hard` are untouched.

## Tests — `tests/test_commit_scoping.py` (real git, `.devsteward` fake only for `claude`)

- `test_scoped_commit_excludes_preexisting_dirt` (AC1)
- `test_capture_gate_tree_matches_scoped_commit` (AC2)
- `test_unscoped_commit_stages_whole_tree` (AC3)
- `test_headless_land_does_not_sweep_concurrent_file` (AC4) — full `advance_once` land, the
  session authors its file *during* the run (via a runner side-effect) so the planted concurrent
  file is the only thing dirty at the boundary.
