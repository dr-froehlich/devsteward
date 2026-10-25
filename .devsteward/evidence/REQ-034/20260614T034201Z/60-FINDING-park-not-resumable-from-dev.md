# FINDING (hard) — async-QA park is not resumable from the integration branch

REQ-034's own engine logic (AC3 + AC4 / Decisions 3 & 5). Surfaced by the live e2e:
Peter chose `p` (defer/pending) on REQ-024's AC6, then followed the park's printed
instruction — `steward validate REQ-024` from a plain shell on `dev` — and got:

    Error: REQ-024 has no validate step — it declares no artifact/manual
    acceptance criterion, or it is not active

`steward status` (on dev) does not list REQ-024 at all (cursor REQ-016:validate;
eligible REQ-019/022/023). The pending validation is invisible and unresumable.

## What works (the park's clean exit — D3/D4/REQ-032)

- The verdict prompt was the new guided one: `[a]pprove / [d]ecline / [p]ending`,
  engine-recorded (not session-asserted). Park message correct per Decision 3.
- After `p`: HEAD returned to `dev`; working tree clean; feature branch
  `req-024-production-cutover` intact and UNMERGED into dev (Decision 4 holds).
- Pipeline NOT frozen: REQ-019/022 develop steps remain eligible (Decision 3, half).

## What breaks (ledger reality after the park, HEAD on dev)

| Check | dev (HEAD) | feature branch |
|---|---|---|
| REQ-024 status | **draft** | open/in-flight |
| REQ-024 in state.yaml | **absent** | REQ-024:validate = blocked-on-decision (DEC-017 open) |
| park event in events.jsonl | **absent** | present (updated 2026-06-14T04:35:25Z) |

The park wrote ALL its bookkeeping to the feature branch's ledger, then switched
HEAD to dev, leaving NO trace on dev. From dev the engine sees a `draft` REQ with
no validate step → errors "not active". It never discovers there is a feature
branch to reconcile.

## ACs broken

- AC4 / Decision 5 (clean resume): "steward validate REQ-NNN cleanly resumes a
  parked validation ... reconciling the feature branch from current dev." Does not
  resume — errors. Failure mode merely CHANGED from the old diverged-branch refusal
  (Finding 1) to "not active"; the resume is still broken.
- AC3 (standing work-item, not a blocked pipeline): pipeline isn't frozen, but the
  waiting validation is invisible (status omits it) and unresumable. A standing
  work-item you cannot see or resume is a lost ticket, not a standing item.
- The park's OWN printed instruction ("Run `steward validate REQ-024` from a plain
  shell when ready") errors when followed verbatim — a self-broken promise.

## Root gap

For an async park that returns HEAD to dev to be resumable, the pending-validation
marker must live where dev can see it (recorded on dev's ledger with a pointer to
the feature branch) OR the resume must scan branches for it. Currently neither
happens. North-star D3 ("the engine is the bookkeeper") + Decision 5 say the user
should not have to hand-checkout the feature branch; today they get an error with
no path forward.

## Interaction with Finding 1 (50-...md)

Peter refreshed FlowSteward's stamped skill from the template (system-test now
5123 B, Jun 14 06:38 — updated). The disambiguation re-run that would show whether
guided AC6 now works is BLOCKED by this resume defect — you cannot get back into the
validation to see the updated skill drive AC6.

## Verdict authorship

None asserted. AC6 of REQ-034 is Peter's manual decision against Decisions 1-7; the
engine records his verdict. This file is reviewable evidence only.
