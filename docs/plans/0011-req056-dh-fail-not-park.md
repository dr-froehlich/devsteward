# Plan 0011 — REQ-056: states D/H fail to a repeatable step, not a decision park

Covers REQ-056.

## Goal

Take the two non-choice stops — **state D** (repair budget exhausted, gate still red) and
**state H** (land gate refused: no plan names the REQ) — off the park-and-surface *decision*
mechanism and route them to the existing `steward repeat` recovery verb. Have the `FAILED`-step
surface name that verb. `answer_decision` / `park_decision` are **untouched** — the parks simply
stop *calling* the decision machinery and set the step `FAILED`, converging on the path the
no-budget red gate (state A) already uses.

## The shape today (and why it stalemates)

- **State D** — `executor.py` `_repair_loop`, budget-exhausted tail (≈585-601): parks a
  `Decision`, sets `BLOCKED`, returns `RunOutcome.PARKED`.
- **State H** — `executor.py` `mechanical_land`, land-gate refusal (≈434-448): parks a
  `Decision`, sets `BLOCKED`, commits the ledger close, returns `RunOutcome.PARKED`.

Answering a decision flips the step back to `PENDING` (a clean restart that abandons the partial
work in the tree). For a non-choice, that just re-hits the same wall. `steward repeat` already
does the right thing: flips `FAILED → RECOVER`, and the next driven run carries `--repeat` so the
resuming session assesses the dirty tree.

## Changes

### 1. State D fails, does not park (`_repair_loop`)
Replace the budget-exhausted park block with: `set_status(FAILED)`, `save()`, keep the
`repair_exhausted` event, **no** `park_decision` / `Decision`, and return
`StepResult(step, RunOutcome.VERIFY_FAILED, brief)` — the same non-stopping outcome as the
no-budget red gate (state A, `run_step` ≈340-343). Like state A, it leaves the ledger write
uncommitted (the dirty tree the `repeat` session inherits).

### 2. State H fails, does not park (`mechanical_land`)
Replace the land-refusal park block with: `set_status(FAILED)`, `save()`, keep the `land_refused`
event, **no** decision, **still** `self._commit_ledger_close(step, "ledger close — land refused")`
(REQ-032 — clean tree at rest, exactly as today), and return
`StepResult(step, RunOutcome.VERIFY_FAILED, refusal)`. `VERIFY_FAILED` is non-stopping in `run()`
(only `REFUSED`/`LIMIT`/`FAILED` break the loop), so the batch continues to other REQs — matching
today's PARKED non-stop. Applies in both modes (shared routine); a missing plan is mechanical
regardless of driver, and `repeat` recovers it.

### 3. `steward status` names the forward verb (`cli.py status`)
In the steps loop, annotate a `FAILED` step with `  → steward repeat <REQ>` (red), so D, H, and
the pre-existing `FAILED` states (A/B/G) all name their forward path. The hint that used to live
on the parked-decision line now rides the failure surface.

## Why VERIFY_FAILED and not FAILED
`RunOutcome.FAILED` breaks the `run()` loop (a hard stop for a human). Both D and H must let the
run drain other independent steps (D converges on state A's non-stopping path; H must not let one
missing plan halt unrelated REQs). `VERIFY_FAILED` already carries "step is `FAILED`, run keeps
going" — exactly the converged semantics.

## Out of scope
- `answer_decision` / `park_decision` unchanged (Decision 3). No resume-signal field, no new
  transition.
- State E (red validation: rework vs revalidate) stays a real fork on the decision mechanism.
- No mechanical land-retry for H (a full develop session on `repeat` is cheap with `--repeat`).

## Tests (all `regression`, reuse `test_phase_model.py`'s in-memory git + scripted-claude harness)
- **AC1** `tests/test_phase_model.py::test_repair_exhausted_fails_not_parks` — rewrite of
  `test_repair_budget_then_park`: budget spent, gate red → step `FAILED` (not `BLOCKED`), no
  `decision_parked`/open decision, `repair_exhausted` recorded, run continues (no hard stop),
  outcome `VERIFY_FAILED`. The repair-turns-green sub-case still lands.
- **AC2** `tests/test_phase_model.py::test_land_refused_fails_not_parks` — rewrite of
  `test_land_requires_plan_artifact`: no plan → step `FAILED`, no decision, `land_refused`
  recorded, ledger close committed (clean tree), run continues; with a plan it lands.
- **AC3** `tests/test_phase_model.py::test_repeat_recovers_dirty_fail_with_signal` — after a D/H
  failure, `steward repeat` flips `FAILED → RECOVER`; the next run issues `--repeat`
  (`step_started recover: true`).
- **AC4** `tests/test_cli_smoke.py::test_status_failed_step_names_repeat` — a real scaffolded
  project with a `FAILED` develop step: `steward status` shows `→ steward repeat REQ-001` on the
  ✗ line, and `steward decision list` reports none.
