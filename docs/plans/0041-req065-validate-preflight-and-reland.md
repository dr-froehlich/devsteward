# Plan 0041 — REQ-065: validate pre-flight gate + `steward reland`

Covers **REQ-065**. Two engine defects FlowSteward REQ-045 surfaced, plus a doc fix.

## Problem (recap)

1. **Land gate fires after the validate session.** `CompositeLandGate` runs inside
   `mechanical_land`, which only runs *after* the System-Test session and its human
   sign-offs. A formality failure (missing concept doc / plan) therefore wastes a whole
   paid session + every oracle it collected.
2. **No cheap recovery for a gate-refused validate.** REQ-056 sets a refused step `FAILED`
   so `steward repeat` recovers it — but `repeat` re-spawns the session and re-collects
   every sign-off. For a two-minute formality fix that is disproportionate.

## Design

### 1. Pre-flight the gate (validate phase only)

The gate is a cheap grep-shaped existence check; run it *before* spending the session.

- `ReqValidateRoutine` gains `_preflight_gate(ex, step) -> StepResult | None`: calls
  `ex.land_gate(step)`; a refusal becomes a terminal `StepResult(step, REFUSED, refusal)`,
  leaving the **ledger and tree untouched** (no `RUNNING`, no `step_started`, no session).
- Called at the top of both validate entry points that set `RUNNING` + spawn — `start()`
  (attended two-phase, shape A/B) and `__call__` (batch loop) — right after the
  `pending_labs` availability check and **before** `set_cursor`/`set_status(RUNNING)`.
- `mechanical_land` gains a keyword `run_gate: bool = True`. The validate land callers
  (`record`, `_validate`) pass `run_gate=False` because they already pre-flighted — so the
  gate is **never called a second time for the same validate step** (REQ §1). Develop
  landing keeps the default `True` (REQ-056 develop recovery is unchanged).

`revalidate` (done-REQ re-validation) is non-mutating and never lands, so it is not
pre-flighted.

### 2. `steward reland REQ-NNN`

The session already ran; its sign-offs are durable in the green `validation` event.
Once the formality is fixed, replay the land without re-running the session.

- `ReqValidateRoutine.reland(ex, req_id, *, driver)` — narrow, safe preconditions
  (Decision 4):
  - `REQ-NNN:validate` is `FAILED`;
  - the latest `land_refused` event for the step is at-or-after the latest `ok:True`
    `validation` event;
  - that green `validation` event exists.
  Otherwise a hard `REFUSED` with a diagnostic routing to `steward revalidate` (red) /
  `steward repeat` (develop step).
- On success: reconstruct `detail`, `signoffs`, `evidence` from the green validation
  event; re-run the (now-fixed) gate as a final pre-flight (still red → refuse, leave
  `FAILED`); flip the step `RUNNING`; append a `reland` event; re-write `verified_by`
  carrying the recorded sign-offs forward; call `mechanical_land(..., run_gate=False)`
  which commits + advances the cursor to `DONE`.
- CLI `reland` command (parallel to `repeat`/`revalidate`): wraps the call in a
  `transaction` (REQ-049 atomic), maps `REFUSED` → non-zero `ClickException`.

### 3. Concept path convention in `CLAUDE.md.tmpl`

Add a house-conventions note: a `process.concept: true` REQ's concept doc **must** be at
the flat path `docs/concepts/REQ-NNN.md` (not a subdirectory), enforced by the land gate.

## Files

- `devsteward/core/executor.py` — `mechanical_land` gains `run_gate` kw.
- `devsteward/profiles/req/validate.py` — `_preflight_gate`, pre-flight calls in
  `start()`/`__call__`, `run_gate=False` at the two validate land sites, `reland` method.
- `devsteward/cli.py` — `reland` command.
- `devsteward/templates/CLAUDE.md.tmpl` — concept path note.

## Tests

- `tests/test_validate_preflight.py` (AC1) — `start()` fires the composite gate; a missing
  concept doc returns `REFUSED`, ledger PENDING (untouched), no `step_started`, no session.
- `tests/test_reland.py` (AC2) — synthesize `develop` deferred + green `validation` +
  `land_refused` + `FAILED`; fix the formality; `reland` lands without a session, cursor →
  `DONE`, REQ `done`, sign-off carried into `verified_by`.
- `tests/test_reland.py::test_reland_precondition_failures` (AC3) — red validation
  (BLOCKED), no-validate-step REQ, DONE/PENDING/RUNNING, FAILED-without-green all refuse
  with the routing diagnostic.
- AC4 — `grep` for `docs/concepts/REQ-NNN.md` in `CLAUDE.md.tmpl`.
