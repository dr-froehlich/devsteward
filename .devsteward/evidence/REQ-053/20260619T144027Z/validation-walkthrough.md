# REQ-053 — System-Test validation walkthrough (guided/attended)

**REQ:** REQ-053 — Process resilience: every red step has an available forward path;
audit the rework-vs-repeat model
**Mode:** guided (`--guided`), attended. AC1 `check: manual` — human verdict, engine-recorded.
**System Tester:** independent session; did NOT read the develop diff, the develop session
plan, or `git log -p` of the builder's commits. Validated the deliverable + its mechanical
claims against the live engine source only.

## Validation surface

- **Deliverable:** `docs/reports/2026-06-19-process-resilience-forward-path-audit.md`
  - sha256 `e3f2c40652117cf8dcde69343842d7961399223102323ec38809a0202e0b235d`
  - 206 lines.

## AC1 clause-by-clause coverage check (presence, not verdict)

| AC1 clause | Where in report | Present |
|---|---|---|
| Enumerate every red/failed/parked terminal state → available forward verb or flagged dead-end | "Forward-path map" table, states A–J (10 rows) + refusals para | yes |
| Assess rework-vs-repeat model vs current `recover`/`rework` verbs, incl. whether `recover` should become `repeat` | "The repeat-vs-rework model" §; rec. #1 | yes |
| Cover out-of-tool root-cause case + name a stable continue-path | "Out-of-tool root cause" § (table + usage-limit reference design) | yes |
| Name a follow-on REQ for each recommended change | REQ-054 (rename), REQ-055 (revalidate+brief), REQ-056 (resume signal), REQ-057/docs | yes |

10 terminal-state rows enumerated (A–J). 4 follow-on REQs named (REQ-054, 055, 056, 057).

## Independent verification of the report's load-bearing mechanical claims

The report's argument hangs on specific engine-code facts. Each was spot-checked against the
live source (not the builder's diff). All held:

| Report claim | Source checked | Result |
|---|---|---|
| `StepStatus` vocabulary = PENDING/RUNNING/DONE/BLOCKED/FAILED/RECOVER | `core/model.py:17-22` | confirmed exact |
| Only PENDING & RECOVER are runnable (`_RUNNABLE`) — the single definition of "available path" | `core/executor.py:199,213` | confirmed `_RUNNABLE = (PENDING, RECOVER)` |
| Usage-limit re-queues to PENDING (or stays RECOVER); `--recover` appended only when RECOVER | `core/executor.py:267-280` | confirmed (`requeue = RECOVER if recovering else PENDING`; `command + (" --recover" if recovering …)`) |
| `decision answer` flips only the decision's own step BLOCKED→PENDING; won't resurrect a done step (→ re-validate-without-redo path) | `core/ledger.py:153-169` | confirmed (explicit "don't resurrect a done step" guard) |
| `recover`: all FAILED steps → RECOVER; refuses when no FAILED step | `lifecycle.py:108-128` | confirmed |
| `rework`: develop DONE→RECOVER, validate BLOCKED→PENDING, answers parked decision; refuses on done (→supersede), no validate step, or no real red | `lifecycle.py:130-175` | confirmed |
| No `steward revalidate` **CLI verb** exists today (the "missing external cell" gap) | `cli.py` (`@main.command` scan) | confirmed — `revalidate` appears only as `rework`'s docstring + the internal `routine.revalidate` method, never a registered command |

Note for the reviewer: `profiles/req/validate.py:160` defines a `revalidate` *method* (internal
routine that re-runs a validation while preserving the event log). That is distinct from the
proposed `steward revalidate` **CLI verb** in recommendation #2 — the gap claim is about the
operator-facing verb, which genuinely does not exist.

## Anomalies observed

- None material. Line-number citations in the report (e.g. "executor.py:276") are approximate
  by a few lines against the current tree but the cited behaviour matches exactly at the named
  region. Not a defect — flagged only for precision.

## Disposition

This is a `manual` acceptance criterion. The System Tester does not pass or fail it. The
deliverable is present, complete against all four AC1 clauses, and its mechanical foundation is
accurate. The verdict — that the enumeration is complete and REQ-054…057 are actionable without
re-litigating the model — is **Peter's**, recorded by the engine at `steward validate REQ-053`.
