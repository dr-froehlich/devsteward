# FINDING (hard) — no way to complete the `steward validate` close when the Claude→shell handover dies

`steward validate` is a **two-phase** wrapper (REQ-034 Decision 6, and the engine rule
"never spawn Claude from within Claude"): the invoking shell script (phase 1) brings up
an interactive `claude` session that captures the human verdict via the in-session
record; when Claude exits, control returns to the wrapping script (phase 2), which
closes the bookkeeping — commits the ledger close, parks/records the verdict, returns
HEAD to `dev`. The two phases are deliberately split so Claude is never nested.

The defect: **phase 2 only runs if Claude hands control cleanly back to the script.**
If the terminal session crashes, or Claude is quit abnormally, or the process is killed
between the verdict and the script resuming, the handover is lost and phase 2 **never
executes**. There is **no `steward` subcommand to run the close by hand** — nothing like
`steward validate --finish` / `steward close REQ-034` / a resume of the pending
two-phase transaction. The captured verdict is stranded mid-transaction with no operator
verb to land it.

## What it cost (this run)

Peter's terminal crashed during exactly this handover. The verdict was taken but the
script's closing half never ran. Recovering meant **spinning up a separate, expensive
Claude session purely to reconstruct and perform the missing ledger close by hand** —
hand-reasoning which commit/event/status the script would have written, then writing
them. That ad-hoc close is also why the red landed on the feature branch but not on dev
(it was done "manually," not by the script's own reconcile path) — feeding directly
into Findings 60 and 70.

## Why this matters (not a one-off)

- The two-phase split (good, per D6) creates a **distributed transaction** between a
  human-driven Claude session and a shell script. Any distributed transaction needs a
  recovery path for a torn handover; this one has none.
- The only paths available today are: (a) re-run `steward validate`, which **re-parks /
  re-validates** rather than finishing the interrupted close (it starts a fresh session,
  not phase 2 of the old one — and burns another interactive session), or (b) hand-edit
  the ledger, which is exactly the "engine is the bookkeeper" violation the design exists
  to prevent (North-star D3).
- A crash between phases is not exotic — interactive validation sessions are long-lived,
  and WSL/terminal drops are routine.

## Root gap

The pending two-phase validate transaction is not **resumable / completable from a plain
shell**. Needed: a first-class verb that, given a REQ whose verdict was captured but whose
close did not run, performs phase 2 only (read the in-session verdict marker, commit the
ledger close, route to rework/land, return HEAD) — idempotently, without launching a new
Claude session. Equivalently: persist enough of the verdict at capture time that a shell
verb can finish the close deterministically.

## Verdict authorship

None asserted. Reviewable evidence only; AC6 remains Peter's manual decision.
