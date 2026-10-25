# Plan 0017 — REQ-032: ledger always committed

Covers **REQ-032** — every terminal step outcome leaves a clean working tree: the
ledger writes (`state.yaml`/`events.jsonl`) and any captured evidence are committed
before the executor returns or proceeds to the next step.

## Problem recap

Three engine paths end an operation with the ledger dirty in the working tree, so a
multi-REQ `steward run` lets step N's trailing writes ride inside step N+1's commits
(mixed provenance — the exact audit-boundary leak the `--no-ff` discipline prevents):

1. **Post-merge** (`_merge_after_land`) appends the `branch_merged` event *after* the
   merge and returns without committing it → dirty on the integration branch.
2. **Deferred develop close** (`commit_deferred`, `lands=False`) writes the trailing
   `develop_committed` event + `done` status *after* the work commit → dirty on the
   feature branch.
3. **Park / red-validation outcomes** append the decision/red event (+ evidence files)
   and leave them uncommitted on whatever branch the step ran on.

A red *develop* gate is deliberately **out of scope**: it leaves partial code for
`--recover`/`--repair`, and the run halts on `FAILED` (no continuation), so there is no
boundary leak to plug there.

## Approach

One small committer seam plus three call sites — no new branch semantics, no event-model
change (Decisions 3/5).

### `Executor._commit_ledger_close(step, label) -> str | None`

A follow-up commit of whatever the engine just wrote, on the **active** branch (feature
when one exists, else integration — Decision 3). Delegates to `git.commit_all`, which
stages `-A` and **returns `None` when the tree is clean** — so a no-op path makes no
empty commit (Decision 4). The drivers' up-front `branch_guard` keeps every one of these
paths off the production branch, so no extra guard is needed here. Message shape:
`"{req}: ledger close — {label}\n\n{trailer}"`.

### Call sites

- **`_merge_after_land`** — after `append_event("branch_merged", …)`, commit it as its
  own follow-up on the integration branch with the de-facto message
  `"{req}: ledger close — branch_merged event"` (Decision 2 — never `--amend`, which
  would move the hash the just-recorded events point at). Unchanged early-return when
  `feature == integration` (a land that never branched) → no merge, no follow-up commit.
- **`commit_deferred`** — after `append_event("develop_committed", …)`, commit the
  trailing ledger write as a follow-up (`"{req}: ledger checkpoint"`, matching the
  hand-made precedent 95b01bd).
- **`_drive_step`** — when `run_step` returns `PARKED` (attended park, skill park, land-gate
  refusal, repair-exhausted, **and** an in-flight validate red/manual park — all funnel
  through here), commit the parked decision + red event + any evidence with
  `_commit_ledger_close(step, "parked")`. This is the batch-continuation danger path; a
  `REFUSED` (diverged branch) deliberately halts the run and is left for the human, so it
  is not force-committed.

Interactive `checkpoint` already shares `_merge_after_land` and `commit_deferred`, so the
interactive close (AC2) and an interactive deferred close come along for free.

## Files

- `devsteward/core/executor.py` — the seam + the three call-site edits.
- `tests/test_ledger_close.py` — AC1–AC5, all `regression`, oracle = **real git** state
  in a throwaway repo (the `FakeRunner` + real-`git` pattern: real `GitCli`, real
  `ReqVerifier`, fake `claude`), asserting `git status --porcelain` is empty and the
  expected close commit is at the tip.

## Tests (acceptance)

- **AC1** `test_branch_merged_event_committed_batch` — green batch land on a feature
  branch → integration branch clean, tip is the `branch_merged` ledger-close commit.
- **AC2** `test_branch_merged_event_committed_interactive` — same via `steward checkpoint`.
- **AC3** `test_deferred_develop_close_commits_trailing_ledger` — `lands=False` develop
  leaves the feature branch clean; the trailing write is a follow-up to `develop_committed`.
- **AC4** `test_red_and_parked_outcomes_commit_ledger_and_evidence` — a parked decision and
  a red in-flight validation each leave the tree clean (decision/red event + evidence
  committed).
- **AC5** `test_no_empty_commits_on_no_op_paths` — a land that never branched and a
  production-branch refusal make no new (empty) commit.
