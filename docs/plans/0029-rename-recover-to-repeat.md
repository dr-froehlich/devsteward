# Plan 0029 — Rename the recovery verb `recover` → `repeat` (REQ-054)

Covers REQ-054. A deliberate, behaviour-preserving rename: the run-it-again recovery
action and its resume flag get honest names. No new machinery; the smallest change that
makes the name match the mental model (REQ-053 audit recommendation #1).

## Scope of the rename (what is user-facing → moves now)

1. **Operator verb** `steward recover` → `steward repeat` (hard rename, no alias — D2).
2. **Library entry points** `lifecycle.recover()` → `repeat()`, `RecoverResult` →
   `RepeatResult` (D1). Behaviour identical: flip the REQ's `FAILED` ledger step(s) to
   `RECOVER`, append the event, touch no git/REQ file, refuse when no failed step.
3. **Resume flag** `--recover` → `--repeat` (D3, two-sided contract):
   - `executor.run_step` appends `--repeat` to a re-armed (`RECOVER`) step's command;
   - the `advance` skill's **functional** flag reference branches on `--repeat`.
4. **Operator messages** (D1/AC4): the `repeat` success line uses the new verb; the
   `rework` refusal's cross-reference points at `steward repeat`. No operator-facing
   string still reads `steward recover`. Inline code docstrings naming the verb move
   with the code.

## What stays unchanged (internal — D4/D5)

- `StepStatus.RECOVER` and the `step_recover` event name — internal symbols, not
  user-facing (status renders as the `↻` icon; the event is append-only history nothing
  reads programmatically). Ledger-history continuity preserved (REQ-029).
- The `step_started` event's `recover=` field (internal append-only field).
- Handbook (`_03-workflow.qmd`) and the skill's *explanatory* prose mentioning the verb —
  deferred to a docs REQ (D5). Only the functional flag reference moves here.

## Files touched

| File | Change |
|------|--------|
| `devsteward/lifecycle.py` | `recover`→`repeat`, `RecoverResult`→`RepeatResult`; refusal text + module/function docstrings renamed; the `rework` refusal cross-reference → `steward repeat`. |
| `devsteward/cli.py` | import alias `lifecycle_recover`→`lifecycle_repeat`; `recover` command → `repeat` (txn label + success line use the new verb); section comment. |
| `devsteward/core/executor.py` | `--recover` → `--repeat` on the re-armed command; comment. |
| `.claude/skills/advance/SKILL.md` (hardlinked to the template) | functional flag reference `--recover` → `--repeat`. Edit once — same inode. |
| `tests/test_lifecycle.py` | `test_recover_flips_failed_step` → `test_repeat_flips_failed_step` (AC1); new `test_messages_name_repeat_not_recover` (AC4). |
| `tests/test_transaction_boundary.py` | `test_decision_and_recover_succeed_on_production_branch` → `..._repeat_...` (AC2). |
| `tests/test_phase_model.py` | new `test_repeat_resume_flag` — executor appends `--repeat`, and the shipped skill's functional reference reads `--repeat` (AC3). |
| `tests/test_executor.py`, `tests/test_rework.py`, `tests/test_system_test_phase.py` | update the incidental `--recover` assertions/fakes to `--repeat` so the suite stays green. |

## Acceptance tests (REQ-054 block)

- AC1 `tests/test_lifecycle.py::test_repeat_flips_failed_step`
- AC2 `tests/test_transaction_boundary.py::test_decision_and_repeat_succeed_on_production_branch`
- AC3 `tests/test_phase_model.py::test_repeat_resume_flag`
- AC4 `tests/test_lifecycle.py::test_messages_name_repeat_not_recover`

Plus `steward lint` green. All `regression` checks (module/CLI scope, coupled oracle) — no
System-Test phase.
