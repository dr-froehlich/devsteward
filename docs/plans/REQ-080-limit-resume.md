# REQ-080 — `steward run` rides through a budget limit

Covers REQ-080. Plan-first artifact for the fused develop checkpoint.

## Shape of the fix

Subtraction-shaped, per the REQ's Context §2: the wait/re-gate/switch machinery **already
exists** and is already trusted — `ClauderAccountProvider.precheck` loops on a `wait`
verdict, sleeps `wait_seconds` interruptibly, re-gates, and honors the stop signal. It only
runs at *step start*. So the fix is not "add a backoff loop"; it is **stop treating LIMIT as
run-terminating** and let the next loop iteration's existing gate own the waiting.

Three seams change; no new machinery, no new topology.

## 1. The budget oracle becomes readable (`core/accounts.py`)

`precheck()` collapses clauder's verdict to `(ok, reason)` — enough to gate a step start,
not enough to (a) corroborate an ambiguous session death or (b) tell a *degraded* gate
(clauder absent / call failed) from a genuine `proceed`. Today `_gate()` fabricates
`(0, {"decision": "proceed", …})` on a launch failure, which is indistinguishable from a
real proceed at the call site.

- `_gate()` marks its fail-open body `degraded: True`. `precheck` is unchanged by this
  (rc 0 still admits) — only the new probe reads the flag.
- New `BudgetVerdict` enum + `budget_verdict() -> (BudgetVerdict, reason)`: **one
  non-waiting gate probe**.
  - `EXHAUSTED` — rc 75 (wait) or 69 (unsatisfiable): clauder says the budget is out.
  - `AVAILABLE` — rc 0 proceed/switch.
  - `NO_ORACLE` — clauder absent from PATH, or the gate call failed/timed out (`degraded`).
- `wait_count` increments each time `precheck` actually sleeps on a `wait` verdict — the
  guard's "intervening gate wait" signal (below).

`SingleAccountProvider` grows nothing: it has no `budget_verdict`, so the executor reads
`NO_ORACLE` from its absence via `getattr` — the same fail-open seam pattern as
`dirty_paths` / `write_code_tree`.

## 2. Classify honestly, requeue with the recovery signal (`core/executor.py`)

- **Corroboration (D2, AC1).** `Outcome.ERROR` probes `budget_verdict()` *immediately*.
  `EXHAUSTED` → handle as a limit interruption (requeue, `usage_limit` event with
  `corroborated: true`), never `step_failed`/`FAILED`. Anything else → today's FAILED path.
  Scoped to **ERROR only** — the REQ names `Outcome.ERROR` (AC1) and a `TIMEOUT` (a
  watchdog kill after silence) is not a budget-death shape. `LAUNCH_FAILURE` keeps its own
  diagnosed path (the fictional-cswap fingerprint).
- **RECOVER, not PENDING (D4, AC3).** One shared `_requeue_limit` for every limit *death*
  (classified `USAGE_LIMIT`, corroborated ERROR, and the repair loop's `USAGE_LIMIT`) sets
  `StepStatus.RECOVER` unconditionally — the killed session left partial edits, so the
  relaunch must carry `--repeat` (which `run_step` already derives from RECOVER). The
  *precheck-gate* paths keep today's `requeue` semantics: no session ran, so there is
  nothing to recover.
- **Resumability rides on `StepResult`.** New field `resumable: bool = False` rather than a
  new `RunOutcome` — the outcome is still LIMIT; only the run loop's reaction varies.
  Resumable iff the oracle **answered** (`verdict is not NO_ORACLE`, D6/AC5) **and** the
  guard has not tripped (D5/AC4). Precheck-failure LIMITs (unsatisfiable / stop requested)
  are never resumable — that is the REQ's own stop list.
  - `AVAILABLE` + a classified limit = clauder disagrees with the runtime (its usage view
    lags). Resume anyway, bounded by the guard — that mismatch spin is *precisely* what
    D5 exists for, so treating it as non-resumable would make D5 dead code.

## 3. The guard + the run loop (`core/executor.py`)

- `max_consecutive_limits = 3` (class attr) over `_limit_streak` / `_limit_streak_step`.
  Bump on each limit death; a different step id resets it. Reset on **an intervening gate
  wait** (`wait_count` grew across `precheck` — the window genuinely moved, so this is not
  a tight spin) and on **a step completion** (`RunOutcome.DONE` in `run`; a *different*
  step's progress must reset the streak, which the step-id check alone does not do).
  Tripped → `limit_guard` event + non-resumable → stop, step requeued (today's behavior).
- `run()`: `if res.outcome is RunOutcome.LIMIT: break` becomes
  `if res.outcome is RunOutcome.LIMIT and not res.resumable: break`. A resumable limit just
  loops: `next_eligible` re-selects the same (RECOVER) step, `run_step` calls `precheck`,
  and **the existing gate loop waits / re-gates / lets clauder switch**. The loop-top stop
  check and `max_steps` still bound it. That one word is the whole resume (AC2).
- AC6 needs no new code: a stop during the gate wait returns `(False, "stop requested")`
  from `precheck` → the precheck LIMIT path → non-resumable → break, *before* the runner is
  ever called. Asserting it is the point.

## Files

| File | Change |
|------|--------|
| `devsteward/core/accounts.py` | `BudgetVerdict`, `budget_verdict()`, `wait_count`, `degraded` marker |
| `devsteward/core/executor.py` | `StepResult.resumable`, `_budget_verdict`, `_requeue_limit`, streak guard, ERROR corroboration, `run()` loop condition |
| `devsteward/core/seams.py` | document the optional `budget_verdict` on `AccountProvider` |
| `tests/test_limit_resume.py` | new — AC1…AC6 |

## Tests (all `check: regression`, fake runner + fake clauder seams — no network, no real limit)

`tests/test_limit_resume.py`, node-ids matching the REQ's `-k` selectors:

- `-k corroborat` → AC1: ERROR + `EXHAUSTED` gate → requeued, `usage_limit` event with
  `corroborated: true`, **no** `step_failed`, status never FAILED. Plus the negative: ERROR
  + `AVAILABLE` gate → still FAILED (a genuine error is not laundered into a limit).
- `-k resume` → AC2: limit death then OK on relaunch → `run()` does not stop, both sessions
  ran, the gate waited between them, the step lands DONE. An account switch during the
  re-gate is honored transparently (the provider owns it; the engine just re-prechecks).
- `-k recover_signal` → AC3: the relaunch command carries `--repeat`; a step already
  RECOVER stays RECOVER.
- `-k guard` → AC4: 3 limit deaths with a `proceed` gate throughout → stop, step requeued;
  an intervening gate wait resets the streak (a 4th death still resumes).
- `-k no_clauder` → AC5: `SingleAccountProvider` (no oracle) and a *degraded* clauder gate
  → requeue + stop, exactly one session, no sleep entered.
- `-k stop_signal` → AC6: stop set during the gate wait → run ends, no session launched,
  step left requeued.
