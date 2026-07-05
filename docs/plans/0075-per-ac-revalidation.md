# Plan 0075 — Per-AC revalidation + engine-owned evidence handoff

Covers **REQ-075**. Fixed by three independent mechanisms, all headless / fixture-ledger
testable (acceptance is `regression` only, Decision 5).

## AC1 — red-only re-open is the `revalidate` default

`lifecycle.revalidate` already resolves the red validation and records a `revalidate` event.
Extend it to **scope** the re-run from the red validation's per-AC results:

- red or unrecorded `artifact`/`manual` ACs → the **scoped** set (re-open for capture);
- green ones → **carried** (kept, no re-capture).
- Degenerate — no per-AC results, or *every* declared AC red → no green set → write the
  event exactly as today (no `scope`/`carry` keys): a full re-run, today's behavior.

When there is a green set, the event carries:
- `scope`: the red/unrecorded AC ids (the set to capture),
- `carry`: per carried AC `{ac, check, source_evidence, source_event, [signoff]}`
  (`source_evidence` = the red validation's evidence dir; `source_event` = its `ts`).

The validation run reads the *pending* revalidate (latest `revalidate` newer than the
latest `validation`) via `_pending_revalidate(led, req_id)` and:
- appends ` --ac AC1,AC3` to the System-Tester command (both the batch `_run_session`
  path and the attended `bring_up_guided_session` path) so the session captures only the
  scoped ACs;
- carries evidence forward before grading (AC2).

## AC2 — carry-forward with provenance

`ReqValidateRoutine._carry_forward(ex, plan, evidence_dir)` runs before `_artifact_gate`
on a scoped run:
- copies every file from `source_evidence` into the new run's evidence dir (the green ACs'
  artifacts) — so the uniform artifact gate re-grades them against present files;
- for a carried `manual` AC, synthesizes its result row (`ok:True`) + signoff record from
  the recorded sign-off — **no new decision stop**;
- for a carried `artifact` AC whose source produced **no files**, emits an explicit
  hard-red row (never a silent pass);
- returns the `carry` provenance records; the new `validation` event records them under a
  `carried` field (source evidence path + originating event per carried AC).

Threaded through both record paths (`_validate` for batch/done-revalidate, `record` for the
attended guided path).

## AC3 — evidence handoff (`DEVSTEWARD_EVIDENCE_DIR`)

Every engine-run `artifact` grading command gets `DEVSTEWARD_EVIDENCE_DIR` set to the
current run's evidence dir in that subprocess's environment, **overriding** any inherited
value. Threaded `env` param: `_artifact_gate` → `ReqVerifier._gate_named` →
`_pytest_outcome` / `_exit_code` (core `verify.py`). Independent of AC1/AC2 — fires on
every validation. Documented in `STEWARD.md`.

## Files

- `devsteward/lifecycle.py` — scope computation in `revalidate`.
- `devsteward/profiles/req/validate.py` — `_pending_revalidate`, `_carry_forward`, scope
  threading into the session command + record paths, `env` into `_artifact_gate`.
- `devsteward/profiles/req/verify.py` + `devsteward/core/verify.py` — `env` param on the
  grading subprocess.
- `devsteward/templates/STEWARD.md` — document `DEVSTEWARD_EVIDENCE_DIR`.
- `tests/test_req075_scoped_revalidate.py`, `tests/test_req075_carry_forward.py`,
  `tests/test_req075_evidence_env.py`.
