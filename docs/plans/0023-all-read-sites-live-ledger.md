# Plan 0023 — Every read-side ledger access resolves the live ledger

Covers **REQ-041**. The read-side follow-up to REQ-040, which added `Executor.live_ledger()`
but only routed `steward status` through it. The live symptom (2026-06-15 dogfood):
`steward checkpoint REQ-036 develop` reported *done* (it binds the ledger), then
`steward validate REQ-036`, run seconds later in the same tree, failed with
*"REQ-036:develop is not closed yet"* — its pre-flight read the unbound feature-branch
snapshot, which has no `REQ-036:develop` entry, while checkpoint had written the live `dev`
ledger where it is done.

## Approach

Finish REQ-040 Decision 1 across the read sites it missed in `cli.py`:

1. **`validate` pre-flight** (`ex.ledger.status_of(f"{req}:develop")`) → `ex.live_ledger()`.
   This is the surface behind the live symptom.
2. **no-arg `checkpoint` cursor read** (`ex.ledger.cursor_step`) → `ex.live_ledger()`.
3. **the checkpoint/validate report** `Cursor:` / parked-decisions lines → a single bound
   `led = ex.live_ledger()`.

## Teeth (AC1)

A real-`git` regression test in `tests/test_orientation.py` drives `steward validate` from a
feature branch whose branch-cut `.devsteward/state.yaml` lacks the develop step while the
integration-branch ledger marks it done. The guided bring-up is short-circuited (force the
`in_claude_session` guard true) so the assertion isolates the pre-flight read: with the bug
the command exits on *"is not closed yet"*; with the fix it gets past the pre-flight to the
in-Claude refusal. The test fails without the fix and passes with it.

## Out of scope

The REQ-037 write topology (correct) and the REQ-040 idempotency guard (correct). The
`steward decision` subcommands also read `Ledger(cfg.root)` unbound — a separate site, left
for a follow-up.
