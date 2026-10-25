# Plan 0028 — REQ-053: process-resilience forward-path audit

**REQ:** REQ-053 (`design`, audit-and-recommend) · **Depends on:** REQ-047

## Goal

Produce the audit report REQ-053 requires:
`docs/reports/2026-06-19-process-resilience-forward-path-audit.md`. It must (AC1):

1. Enumerate **every** red / failed / parked terminal state a REQ can reach in the
   post-REQ-047 flow, and for each name the **available** forward verb that adopts a fix and
   continues — or flag it as a dead-end.
2. Classify the **repeat** (external root cause; work sound) vs **rework** (internal root
   cause; work insufficient) intents and assess whether the current
   `recover` / `rework` / `decision answer` verbs map cleanly onto them — including whether
   `recover` should become `repeat`.
3. Cover the **out-of-tool root-cause** case (rate limit, API timeout, account swap,
   lab/host setup the human fixes) and name the stable path that adopts the external fix and
   continues.
4. Name a follow-on REQ for each recommended change.

This REQ ships **no code change** — the deliverable is the report; the verdict is Peter's
`manual` sign-off at `steward validate REQ-053`.

## Method (grounded, not from memory)

Walked the actual recovery surface in the engine, not the prose:

- `core/model.py` — `StepStatus` enum (the state space).
- `core/executor.py` — `run_step` (develop gate, crash/limit/launch-failure handling),
  `_repair_loop` (repair budget → exhaustion park), `mechanical_land` (land gate refusal),
  `commit_deferred`, `_park_attended`, eligibility (`_RUNNABLE`).
- `profiles/req/validate.py` — `_park_red`, `_park_manual`, `_park_pending`, the artifact
  gate, the manual sign-off verdicts (`approved` / `declined` / `deferred`).
- `lifecycle.py` — `recover`, `rework` (exact status transitions + refusal conditions).
- `core/ledger.py` — `answer_decision` (BLOCKED → PENDING), `park_decision`.
- `cli.py` — `recover`, `rework`, `validate`, `checkpoint`, `decision answer` surfaces.

Two mechanical facts confirmed against the code (load-bearing for the findings):

- usage-limit / quota-block re-queues a step to **PENDING** (or keeps **RECOVER** if it was
  already recovering) → auto-eligible next run; the `--recover` resume signal rides **only**
  on `RECOVER` status.
- `decision answer` flips **only the decision's step** BLOCKED → PENDING. On a red-validation
  decision that means validate → PENDING while develop stays **DONE** — i.e. a
  re-validate-without-rework path already exists, but is undocumented and the red brief steers
  to `rework` instead.

## Deliverable shape

The report (markdown, English) carries:

- A **state-space table**: each terminal red/failed/parked state → status it lands in →
  available forward verb → resulting status → whether the resume carries `--recover` →
  internal/external cause → verdict (available / seam / gap).
- A **repeat-vs-rework** section with the 2×2 (layer × cause) and the verdict on the verb
  naming, including the `recover → repeat` question.
- An **out-of-tool root-cause** section naming the stable continue-path per external cause.
- A **recommendations** section, each with a named proposed follow-on REQ.

## Files touched

- `docs/plans/0028-process-resilience-forward-path-audit.md` (this file).
- `docs/reports/2026-06-19-process-resilience-forward-path-audit.md` (the deliverable).
- `docs/requirements/REQ-053.md` + `REQUIREMENTS_INDEX.md` — already promoted `draft → open`
  at intake; the engine owns the `done` flip after `steward validate REQ-053`.

## Tests

No automated test — AC1 is `check: manual`. The develop gate has no regression AC, so it is
trivially green; the close **defers the land** to `steward validate REQ-053` (Peter's
sign-off). `steward lint` must stay green.
