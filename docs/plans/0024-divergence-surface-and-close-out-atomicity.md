# Plan 0024 — REQ-043: a surfaced divergence leaves no uncommitted ledger write, and the close-out switch never crashes on a dirty tree

Covers **REQ-043**. Finishes REQ-037 Decision 2 for the two abort paths it never reached:
the divergence-surface refusal and the topology close-out's pre-switch tree.

## The bug, confirmed against the code

1. **Seam 1 — `prepare_branch` (executor.py:270) appends-but-never-commits.** On a diverged
   feature branch it does `self.ledger.append_event("branch_diverged", …)` then returns a
   surface message. Because it only runs while HEAD is the integration branch, that append
   dirties the integration tree's *tracked* `.devsteward/events.jsonl` and leaves it dirty —
   the lone abort path that appends without committing (its REQ-037 siblings
   `reconcile_aborted` / `merge_aborted` commit their record). `_drive_step` then appends a
   *second* uncommitted event, `branch_surfaced`, on the REFUSED return.

2. **Seam 2 — the close-out switch crashes on that dirt.** A *later* step's green land →
   `_merge_after_land` → `_return_main_tree_to_integration` (executor.py:217) runs
   `clean_untracked_ledger()` (`git clean -fdq`, untracked only — never the modified-tracked
   file), drops the worktree, then `switch(integration)` = `git checkout` with `check=True`.
   Git refuses to clobber the dirty tracked `events.jsonl` → uncaught `CalledProcessError` in
   a half-state (worktree already removed, land checkpoint already committed) that no
   `steward` verb targets. Hand-surgery to recover.

Scope is **prevention only** — close both seams so the half-state is unreachable. No
`steward recover --resume-merge`.

## Decision 1 — the divergence surface commits its diagnostic on the integration branch

- `prepare_branch`: after `append_event("branch_diverged", …)`, `_bind_ledger()` (we are on
  the integration branch — main tree, no worktree) and `_commit_ledger_close(step, …)` so the
  `branch_diverged` breadcrumb is **committed** and the tree is **clean** before the surface
  message returns. Mirrors the committing shape of its `reconcile_aborted` / `merge_aborted`
  siblings.
- `_drive_step` REFUSED branch: after `append_event("branch_surfaced", …)`, also
  `_commit_ledger_close(step, …)` so the *whole* terminal REFUSED outcome (both `branch_*`
  events) leaves a clean tree (REQ-032) — no uncommitted tracked write survives for a later
  land to crash on.

## Decision 2 — the close-out switch is atomic on a dirty tree (defense-in-depth floor)

- New `GitCli.dirty_tracked_ledger()` → the tracked (committed-then-modified) `.devsteward/`
  paths with an uncommitted change in the main tree, **excluding** untracked (`??`) entries
  (those are swept by `clean_untracked_ledger`; only a *tracked* modification makes
  `git checkout` refuse). Empty string when clean.
- `_return_main_tree_to_integration(step=None, *, unattended=False) -> str | None`: before the
  destructive `clean`/`remove-worktree`/`switch`, if `dirty_tracked_ledger()` is non-empty,
  **abort-and-surface** via a new `_record_aborted_switch` — append a `switch_aborted` event,
  park a decision when `unattended`, commit the record on the integration branch (the worktree
  is still present, so the record lands cleanly without touching the dirty main-tree file), and
  return the recovery instruction. The repo is left intact (same HEAD, worktree present, dirty
  file preserved) and `git checkout` is never reached.
- Thread the return up: `_merge_after_land` captures
  `recovery = _return_main_tree_to_integration(step, unattended=unattended)` and returns it on
  abort (the validate routine already turns a non-None `_merge_after_land` return into a
  `PARKED` StepResult, executor.py:158-160; the develop merge path likewise records/parks).
  `return_to_integration` (the park-cleanup caller) keeps ignoring the return — its guard call
  now simply no-ops the switch instead of crashing if dirt is somehow still present.

## Files

- `devsteward/core/git.py` — add `dirty_tracked_ledger()`.
- `devsteward/core/executor.py` — `prepare_branch` commit (Seam 1a); `_drive_step` REFUSED
  commit (Seam 1b); `_return_main_tree_to_integration` guard + new `_record_aborted_switch`;
  `_merge_after_land` propagates the recovery (Seam 2).
- `tests/test_plane_split.py` — AC1/AC2/AC3, all real-git (`_init_git`), only `claude` faked.

## Tests (real-git teeth — the REQ-037 / plan 0021 lesson)

- **AC2** `test_diverged_surface_commits_diagnostic_clean_tree_realgit` — pre-create a diverged
  feature branch for REQ-001, call `prepare_branch` directly: it returns the surface message,
  `git status --porcelain -- .devsteward` is empty, and `branch_diverged` is on dev's
  committed `events.jsonl`.
- **AC1** `test_diverged_surface_then_later_land_no_crash_realgit` — REQ-001 diverged surfaces
  (REFUSED, clean tree); REQ-002 then develops + lands; the close-out switch completes (no
  `CalledProcessError`), REQ-002's merge lands, dev is clean at rest.
- **AC3** `test_close_out_switch_dirty_tree_surfaces_not_crash_realgit` — a deferred-validate
  REQ on a feature branch; inject a dirty *tracked* `.devsteward/` change into the main tree;
  the validate land's close-out detects it, parks (unattended), leaves the repo intact (same
  HEAD, change preserved, still on the feature branch), and never raises.
