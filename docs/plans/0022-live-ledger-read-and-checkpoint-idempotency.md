# Plan 0022 — Live integration-branch ledger reads + idempotent checkpoint

Covers **REQ-040**. The read-side and idempotency follow-up to REQ-037 (which bound only the
*write* paths). Two defects from the 2026-06-15 double-checkpoint postmortem:

1. **Stale-snapshot read.** `steward status` reads `ex.ledger` unbound; on a feature branch
   that returns the branch-cut `.devsteward/state.yaml`, not the live `dev` cursor. The
   `/advance` skill's step-1 *"Read `.devsteward/state.yaml`"* has the same footgun.
2. **No idempotency guard.** `steward checkpoint` re-run on an already-`done` step appends a
   duplicate `develop_committed` (with `commit: null`) plus a redundant ledger commit.

## Approach

### Decision 1 — bind the ledger on the read path (AC1)

Add a public read accessor on `Executor`:

```python
def live_ledger(self) -> Ledger:
    self._bind_ledger()
    return self.ledger
```

It reuses REQ-037's `_bind_ledger` (worktree resolution, idempotent), so a read from any
branch resolves the live integration-branch ledger. `cli.status()` switches from
`led = ex.ledger` to `led = ex.live_ledger()`. No `status` output reformatting.

### Decision 2 — `/advance` orients from `steward status` (skill text)

Step-1 of `.claude/skills/advance/SKILL.md` (hard-linked to the stamped template — one
inode, edit once) changes *"Read `.devsteward/state.yaml`"* to orient from
`steward status` (the sanctioned binding read), keeping the `cursor.step` semantics.

### Decision 3 — checkpoint refuses an already-`done` step (AC2, AC3)

In `Executor.checkpoint`, immediately after `self._bind_ledger()` binds the live ledger
(so the status read is the integration-branch one, not the feature snapshot) and **before**
the first `verify` append, guard:

```python
if led.status_of(step.id) is StepStatus.DONE:
    return StepResult(step, RunOutcome.REFUSED, <actionable message>)
```

`RunOutcome.REFUSED` is already mapped by `cli.checkpoint` to a non-zero `ClickException`.
Returning before any `append_event`/`save`/`_commit` guarantees **zero** ledger writes —
`events.jsonl` byte-unchanged, no new integration-branch commit. The guard fires for the
deferred-land develop case (REQ stays `open`, develop step `done`) — the exact incident
shape — because the step is still derivable while its `validate` sibling is pending.

## Files

- `devsteward/core/executor.py` — add `live_ledger()`; add the done-guard in `checkpoint()`.
- `devsteward/cli.py` — `status()` reads via `ex.live_ledger()`.
- `.claude/skills/advance/SKILL.md` (+ stamped template, same inode) — step-1 orientation.
- `tests/test_orientation.py` — new, real-git (REQ-037 plane-split precedent):
  - `test_status_reads_live_ledger_from_feature_branch_realgit` (AC1)
  - `test_checkpoint_refuses_already_done_step_realgit` (AC2)
  - `test_incident_no_duplicate_checkpoint_realgit` (AC3)

## Out of scope

The REQ-037 write topology (correct); a `steward where`/`cursor` command; `status` output
reformatting. No lab, no validate phase — the ACs reproduce the defect headless on synthetic
real-git repos.
