# REQ-034 — guided System-Tester session (attended)

- **Mode:** `--guided` (attended), in-session two-phase path (Decision 6, path B).
- **Date:** 2026-06-16
- **Tester role:** System Tester for REQ-034; did not read the develop diff or feature-branch history (decoupling preserved).

## What was exercised

Human (Peter) attests this guided human-validation behaviour has been driven to ground
across **repeated** prior validate runs in this repo and in FlowSteward — the iterations
that found and fixed the rework-era defects (ledger-on-integration-branch, captured-verdict
marker, clean re-entry, nesting refusal). The guided session prepares surfaces and answers
questions rather than handing a bare `y/N` (Decisions 1–7).

## Note on AC6's literal subject

AC6's literal procedure names `steward validate REQ-024` on FlowSteward's parked
production-cutover branch. That parked branch **no longer exists** — FlowSteward's REQ-024
landed long ago, so the consumer no longer offers it for validation. The *behaviour* AC6
exercises (guided session → engine-recorded verdict → non-freezing pending park → clean
resume-and-land) was observed across the prior successful validate runs in this repo and in
FlowSteward; the specific REQ-024 fixture is stale.

## Verdict

Not written here. The human verdict is engine-recorded; this artifact only records the
session and the human's attestation.
