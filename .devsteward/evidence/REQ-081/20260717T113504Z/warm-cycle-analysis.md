# REQ-081 System-Test — real out-of-band warm cycle (Decision 7)

Per REQ-081 Decision 7, this validation does not nest a second `steward validate REQ-081`
run. Instead it analyzes ledger evidence of a genuine warm cycle that already happened:
FlowSteward's REQ-116 validation, driven for real by the operator on 2026-07-17.

## What the ledger shows

`warm-cycle-events.jsonl` in this dir is a verbatim excerpt of
`flowsteward/.devsteward/events.jsonl` (events at that repo's indices 1134–1147),
capturing the full REQ-116 validate cycle:

- `1137` — first `validation` event, `ok: false` (AC7 manual decline: maintain outcome
  not shown on `/status/`, live-fetch fallback broken).
- `1138` — `rework` event for `REQ-116`.
- develop repaired, re-committed (`1139`–`1140`).
- `1141`–`1142` — re-entry, second `validation` red (same two findings not yet fully
  fixed).
- `1143` — second `rework` event.
- develop repaired again, re-committed (`1144`–`1145`).
- `1146` — `validation` event, `ok: true`, same step (`REQ-116:validate`), reusing the
  same evidence dir (`.devsteward/evidence/REQ-116/20260717T035935Z`) opened at `1141`.
- `1147` — `checkpoint` (mechanical land).

This satisfies the AC6 grading assertion: a red validation, followed by a rework/
revalidate edge on the same REQ, followed by a green validation on the same step.

## Operator corroboration (out-of-band, this session cannot verify the transcript itself
— reported by Peter Froehlich, the operator, during this guided validation)

The event log alone doesn't show *which* process was warm. Peter supplied the terminal
transcript directly:

1. `steward validate record REQ-116` (a standalone process, run from a plain shell)
   graded the captured evidence, prompted the AC7 manual verdict, and Peter declined —
   producing the ledger's red `validation` event. The refusal text it printed
   ("Pick the edge that fits the root cause: if the develop was hollow, return it to
   develop for a fix with `steward rework REQ-116`; ...") matches
   `devsteward/profiles/req/validate.py:1099` verbatim — this really was the REQ-081
   `record` verb, not a legacy path.
2. `steward rework REQ-116` (same or another plain shell) flipped develop back to
   `RECOVER` and validate to `PENDING`.
3. A **separate** `claude` session was opened in `flowsteward` to drive the rework; the
   operator's own first line to it was: *"this is rework, the validation session is warm,
   waiting nearby."* — i.e., the original guided System-Tester session was deliberately
   left running, untouched, elsewhere, rather than exited.
4. Once the rework session's develop checkpoint landed, the operator returned to that
   **original, still-open** session and told it directly: *"I reworked this REQ while
   *this* session was warm."* — the session then re-verified against the live system
   (checked `/status/`, re-tested the live-fetch fallback) using the same evidence dir it
   had opened at the start, and was eventually recorded green via a second
   `steward validate record REQ-116`.

## Assessment

The mechanics match REQ-081's design: the guided session that captured the red evidence
never exited between the red and the green (Decision 4); `record` ran from a separate
process both times (Decision 3); `rework` required no CLAUDECODE guard and accepted the
recorded red immediately (Decision 5, AC3); the warm session resumed and reused its
original evidence dir rather than restarting cold (AC4's warm-cycle premise).

One observation, not a defect: the `step_started` events for this cycle
(flowsteward `1135`, `1136`, `1141`) carry no `evidence` field, meaning the guided
sessions were brought up via bare `steward validate REQ-116` (shape A) rather than
`steward validate start REQ-116`. `record`'s `resume_context()` fallback (any
`RUNNING` step, evidence dir resolved from the latest dated dir if the `step_started`
event carries none) accepted this without complaint — shape A bring-up interoperates
with the new standalone `record` verb, which is a reasonable and probably intentional
interop path, but it means this particular real-world run did not exercise the
`steward validate start` verb itself (AC1). AC1/AC2/AC3/AC4/AC5 are already covered by
the regression suite (`tests/test_req081_halves.py`, 13/13 passing locally); this
real-world run is offered as the AC6/AC7 out-of-band proof, not as AC1 coverage.
