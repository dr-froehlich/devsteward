# Plan 0050 — REQ-077: the checkpoint commit is atomic (flip rides the commit) + symmetric ledger↔marker guard

Covers **REQ-077**. Develop phase, fused, all `check: regression`.

## Root cause — reproduced, not theorized

The intake named REQ-076's boundary-delta staging as the prime suspect. A throwaway-repo
reproduction confirms it exactly. With `docs/requirements/REQ-NNN.md` (or the index) **dirty
at the transaction boundary** — so it lands in the `baseline` set — `GitCli.commit_code(msg,
baseline)` stages only `dirty_paths() - baseline`, which **subtracts the flip path back out**.
`ReqDoneFlipper` (the `on_verified` seam) writes `status: done` to that same path *after* the
boundary, but the subtraction drops it: the commit omits the REQ file, the committed status
stays `open`/`draft`, and the worktree is left `M REQ-NNN.md` — the FlowSteward REQ-098/099
drift (both REQ file and index were baseline-dirty, so both were dropped).

The flip is the **engine's own authoritative bookkeeping**, not a concurrent session's delta —
it must never be scoped out. The REQ-076 subtraction is right for *concurrent* dirt; it is
wrong for the flip the engine itself just wrote.

## The fix (three parts, matching the three acceptance concerns)

### 1. The flip is force-staged into the commit (`git.py`, `checkpoint.py`, `executor.py`)

- `ReqDoneFlipper.__call__` returns the **absolute paths it wrote** (the REQ file + the index),
  or an empty set when it flipped nothing (non-landing phase / missing REQ). Signature of the
  `on_verified` seam widens from `-> None` to `-> set[Path] | None`.
- `Executor._land_checked` captures `flip_paths = self.on_verified(step) or set()`, converts to
  repo-root-relative pathspecs, and threads them into the commit as an **`include`** set.
- `GitCli._stage_code(baseline, include=None)` / `commit_code(message, baseline=None,
  include=None)`: after staging `dirty_paths() - baseline` (and the `git reset -q` index
  rebuild), it **also `git add`s the `include` paths unconditionally** — so a flip path that
  was in `baseline` is still staged. `include` is a no-op in the `baseline is None`
  (`git add -A`) checkpoint path and when empty.
- `write_code_tree` (the capture-gate mirror) is **not** given `include`: it runs *before* the
  flip is written, its job is to check the *code* reproduces green, and the flip is
  test-neutral. The gate tree and the landed tree already differ by exactly the flip in today's
  clean-at-boundary path; nothing about REQ-063/REQ-076's seam invariant changes (those tests
  call the two seams with identical working-tree state and no `include`).

### 2. Post-commit clean-tree assertion (`executor.py`) — strengthens REQ-032

- New `Executor._assert_committed_clean(baseline, flip_paths)`: after the code commit, the only
  paths allowed to remain dirty are the **pre-boundary/concurrent** dirt REQ-076 deliberately
  preserves — `allowed = ∅ if baseline is None else (baseline - flip_paths)`. Any
  `dirty_paths() - allowed` leftover means the session's own delta or the flip did **not** fully
  land: raise a plain error so the enclosing `transaction` rolls the half-land back and surfaces
  a `RecoverableError` (fail loudly, never return DONE over a dirty tree). Runs in both the
  certify and the deferred (validate-pending) tails; a no-op under the in-memory fake
  (`dirty_paths()` is empty).

### 3. Symmetric, HEAD-reading marker↔ledger lint guard (`lint.py`, `git.py`) — extends REQ-028 rule 7

- The existing rule 7 (marker-ahead: frontmatter `done`, ledger not) stays exactly as-is,
  reading the working tree.
- **New direction (ledger-ahead):** for each ledger-tracked REQ whose **delivering** step is
  DONE (the `validate` step when one exists, else `develop`/legacy `land`), read the
  **committed HEAD** frontmatter status and index row; if either is not `done`/`DONE`,
  hard-error. Reading HEAD (via a new `GitCli.file_at_head(relpath)`) is what catches a flip
  written to the worktree but never committed — a working-tree read looks consistent and misses
  it. Gated on a real git repo + the file existing at HEAD (skip when it can't be assessed, so a
  no-git lint and a develop-done/validate-pending REQ are never false-flagged).

## Files

- `devsteward/core/git.py` — `_stage_code`/`commit_code` gain `include`; add `file_at_head`.
- `devsteward/profiles/req/checkpoint.py` — `ReqDoneFlipper.__call__` returns the written paths.
- `devsteward/core/executor.py` — thread `flip_paths` → `include`; `_assert_committed_clean`.
- `devsteward/lint.py` — the ledger-ahead HEAD-reading direction.
- `tests/conftest.py` — `FakeGitTopology.commit_code` accepts `include`.
- `tests/test_req077_atomic_flip.py` — AC1/AC2/AC3 (new).
- `tests/test_lint_marker_ledger.py` — AC4/AC5 (extend).

## Tests (the named acceptance)

- **AC1** `test_checkpoint_commits_flip_clean_tree` — real-git `ex.checkpoint` (baseline None):
  HEAD commit carries `status: done` + index `DONE`, `git status --porcelain` (sans
  `.devsteward/`) empty.
- **AC2** `test_headless_land_scoped_staging_includes_flip` — the reproduction: REQ file + index
  **dirty at the boundary** (in `baseline`); the headless land still commits the flip and leaves
  a clean (scoped) tree. Fails on today's code, passes after the fix.
- **AC3** `test_land_asserts_clean_tree_or_fails_loudly` — inject a stubbed flipper that writes a
  path the commit won't capture; the land raises / rolls back rather than returning DONE dirty; a
  clean land returns DONE.
- **AC4** `test_ledger_done_but_marker_draft_hard_errors` — real git: ledger delivering-step DONE
  but committed HEAD frontmatter/index `draft`/`DRAFT` → lint hard-errors; the old marker-ahead
  case still fires.
- **AC5** `test_reconcile_reads_committed_head_not_worktree` — worktree flipped to `done` but
  HEAD at `draft`, ledger DONE → lint STILL flags (reads HEAD); a committed-consistent REQ is
  clean; a develop-done/validate-pending REQ is not flagged.
