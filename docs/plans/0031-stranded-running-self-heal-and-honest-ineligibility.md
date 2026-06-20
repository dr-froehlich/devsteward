# Plan 0031 — REQ-059: self-heal a stranded RUNNING step + honest ineligibility

REQ-059 (fix) — *An interrupted run self-heals a stranded RUNNING step, and ineligibility
names the real cause.* Two compounding defects in `devsteward/core/executor.py`:

1. The interrupt window leaves a step `RUNNING` with no terminal event and nothing ever
   reconciles it (no stale-`RUNNING` sweep).
2. `only_ineligibility_reason` ends in an unconditional else that fabricates a
   *"blocked on an unfinished dependency"* cause for any non-runnable, non-`DONE` status.

The owner chose the **subtractive** fix (report suggestion #1 + #2, dropping #3): a
self-healing startup sweep, not a new recovery verb, not a `finally`/SIGINT guard.

## Approach

### 1. Self-healing sweep (`Executor._reconcile_stranded_running`)

New private method, called **after** `check_invariants(self)` and **before** step
selection in both `run()` and `advance_once()`.

- Read every step the ledger holds in `RUNNING` (`ledger.all_statuses()`).
- For each: requeue to `RECOVER` when the interrupted attempt was itself a recovery, else
  `PENDING`; `set_status` + `save`; append an `interrupted` event naming the step and the
  status it was requeued to (`requeued: pending | recover`).
- Single-process, single-writer, synchronous over one ledger (trunk-based): a `RUNNING`
  status observed at the start of a fresh top-level command provably has no live owner, so
  it is stranded by construction — safe to requeue unconditionally.

The recovery signal is read from the ledger's event log, not the status (the status was
already overwritten to `RUNNING`): helper `_was_recovering(step_id)` returns the `recover`
flag of the **last** `step_started` event for the step. This mirrors the existing
line-276 inline compensation (`requeue = RECOVER if recovering else PENDING`), applied at
load instead of inline (Decision 2).

### 2. Honest ineligibility (`Executor.only_ineligibility_reason`)

Replace the unconditional `else` with a per-step diagnosis computed from the actual
status. Keep the two existing early returns (not-active; all-done). Then walk the REQ's
steps and name the obstruction on the first not-yet-`DONE` step:

- `RUNNING` → named as stranded/interrupted (post-sweep this no longer arises from the
  driver path, but `--only` diagnosis is defense in depth).
- `BLOCKED` → named as parked on an open decision (never a dependency block).
- `FAILED` → named as failed, pointing at `steward repeat`.
- `PENDING`/`RECOVER` → the **only** path that may state a dependency block, and only after
  confirming a `depends_on` entry is genuinely not `DONE` — naming that dependency. (A
  cross-REQ dep is how `--only REQ` can select nothing while a real dep is unmet.)

No new verb, no schema change; `repeat`/`rework`/`revalidate`/decisions untouched
(Decision 4).

## Files

- `devsteward/core/executor.py` — add `_reconcile_stranded_running` + `_was_recovering`;
  call the sweep in `run()` and `advance_once()`; rewrite `only_ineligibility_reason`.
- `tests/test_executor.py` — AC1/AC2/AC3 (below).

## Acceptance tests (all `regression`, module-scope over the executor + ledger)

- `test_stranded_running_swept_to_pending_on_run` (AC1) — a `RUNNING`-stranded step with no
  terminal event self-heals: the run appends `interrupted` (before re-starting) and drives
  the requeued step to `DONE`, no hand-edit.
- `test_stranded_running_recover_preserves_signal` (AC2) — a step stranded out of `RECOVER`
  (last `step_started` `recover:true`) requeues to `RECOVER`, and the driven re-run issues
  `--repeat`.
- `test_only_ineligibility_names_real_cause` (AC3) — `RUNNING` named as interrupted,
  `BLOCKED` named as parked (not a dep block), and the dependency message returned only
  when a `depends_on` entry is genuinely not `DONE`, naming it.
