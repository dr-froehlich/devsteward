# Defect — an interrupted run strands a step in `RUNNING`, and `--only` misreports it as a dependency block

- **Date:** 2026-06-20
- **Author:** Claude (Opus 4.8), at Peter's request
- **Severity:** Medium — no data loss, but the engine wedges a REQ with a *false*
  diagnosis that sends the operator to debug the wrong thing (dependencies) instead of
  the real one (a stranded ledger status). No clean CLI verb recovers it.
- **Component:** `devsteward/core/executor.py` (`run_step`, `eligible_steps`,
  `only_ineligibility_reason`)
- **Reproduced on:** FlowSteward, `dev`, ledger at REQ-039 done / REQ-040 next.

## Summary

After a green REQ-039 develop checkpoint, `steward run REQ-040` was issued while both
cswap accounts were saturated. The command set `REQ-040:develop → RUNNING`, wrote a
`step_started` event, and then **blocked inside the runner** waiting out the quota window
(`⊟ all saturated … waiting for #1 to reset`). The operator `Ctrl-C`'d. The next
`steward run REQ-040` then failed with:

```
Error: REQ-040 has no eligible step — it is blocked on an unfinished dependency.
```

That diagnosis is **wrong**. All five of REQ-040's dependencies
(`REQ-016, REQ-021, REQ-028, REQ-032, REQ-037`) are `done` in both frontmatter and the
ledger. The actual cause is that `REQ-040:develop` was left stranded in `RUNNING`.

## Root cause

Two independent defects compound.

### 1. The interrupt window leaves the step `RUNNING` (no terminal event)

`run_step` (executor.py:270–304) orders its work as:

```python
led.set_status(step.id, StepStatus.RUNNING)      # 270
led.save()
led.append_event("step_started", ...)            # 272
requeue = StepStatus.RECOVER if recovering else StepStatus.PENDING
ok, reason = self.accounts.precheck()            # 278
if not ok:
    led.set_status(step.id, requeue)             # 280  ← requeue path
    ...
result = self.runner(...)                         # 286  ← BLOCKS here on a saturated quota
if result.outcome is ...USAGE_LIMIT:
    led.set_status(step.id, requeue)             # 301  ← the only other requeue path
```

The requeue-to-`PENDING` only runs if `precheck()` fails *up front* (280) or if the
runner returns a clean `USAGE_LIMIT` (301). When cswap's saturation manifests as the
runner **blocking** (waiting for the window to reset) rather than returning, a `SIGINT`
during that block kills the process between line 272 and line 301. The status set at
line 270 is already persisted; the compensating requeue never runs. The step is left
`RUNNING` with no `done` / `failed` / `usage_limit` / `quota_block` terminal event —
an inconsistent ledger state that nothing later reconciles.

There is no stale-`RUNNING` sweep anywhere in the run loop, so the inconsistency is
permanent until hand-fixed.

### 2. `only_ineligibility_reason` fabricates a dependency cause

`eligible_steps` only treats `PENDING`/`RECOVER` as runnable (executor.py:199, 213), so a
`RUNNING` step is silently skipped. When `--only REQ-040` then selects nothing,
`only_ineligibility_reason` (executor.py:226–240) classifies the miss:

```python
if not steps:                       return "... not active ..."
if all(st is DONE for st in ...):   return "... already done."
return "... blocked on an unfinished dependency."   # ← unconditional fallback
```

The third branch is an **unconditional else** — it never checks whether any dependency is
actually unfinished. Any non-runnable, non-DONE status (here, `RUNNING`) falls through to
a confident, incorrect "unfinished dependency" message. This is the part that actively
misleads: it names a cause that is provably false and points debugging at the wrong layer.

## Impact

- The REQ is wedged: `repeat` only re-arms `FAILED` steps (`lifecycle.repeat` refuses with
  "no failed step"); `rework` only handles a red `validate`; `checkpoint` would re-run
  acceptance tests against work that was never done. No verb resets a stranded `RUNNING`.
- Recovery requires a hand-edit of `.devsteward/state.yaml` — the exact class of manual
  ledger surgery DevSteward's discipline is meant to avoid.
- The false "unfinished dependency" text costs operator time chasing a non-existent
  dependency problem.

A second step on the same ledger, `REQ-019:develop` (started 08:24:18, never finished),
was stranded `RUNNING` the same way in the same morning's run — so this is not a one-off.

## Suggested fixes

1. **Make `RUNNING` recoverable.** On `steward run`/`advance` startup, sweep for steps in
   `RUNNING` with no matching terminal event and requeue them (`PENDING`, or `RECOVER` if
   the prior attempt was a recovery) — equivalent to the line-280 compensation, applied at
   load. Optionally emit an `interrupted` event for the audit trail. Alternatively, install
   a `SIGINT`/`finally` guard in `run_step` that requeues before exit.
2. **Stop fabricating the dependency cause.** `only_ineligibility_reason` should branch on
   the *actual* statuses: name a `RUNNING`/stranded step explicitly ("an interrupted run
   left REQ-NNN:phase RUNNING — recover with `steward <verb>`"), and only say
   "blocked on an unfinished dependency" after confirming a `depends_on` entry is in fact
   not `DONE`. As written it should compute the offending dependency and name it.
3. **Give `repeat` (or a new verb) authority over a stranded `RUNNING` step**, so there is
   a sanctioned recovery path that is not hand-editing YAML.

## Workaround applied (FlowSteward, 2026-06-20)

Hand-reset `REQ-019:develop` and `REQ-040:develop` from `RUNNING → PENDING` in
`.devsteward/state.yaml` and appended `quota_block` events (with `reconciled: true`)
mirroring the line-282 compensation the interrupt skipped. `steward run` then proceeds
normally once a quota window reopens.
