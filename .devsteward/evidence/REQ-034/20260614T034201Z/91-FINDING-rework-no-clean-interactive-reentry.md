# FINDING (note, no code yet) — `rework` leaves a dirty tree + no clean interactive re-entry to develop

Surfaced during the live REQ-024 rework cycle (FlowSteward, 2026-06-14): after a clean
`steward validate REQ-024` red park (Decision 8) and `steward rework REQ-024`, getting back
onto the development branch to hand-fix produced a `.devsteward/` merge-conflict spree — the
exact "branch & ledger fixing spree" the operator fears. Captured as a note for when REQ-024
is green and we revisit the engine; **not a REQ-034 landing blocker**.

## What happened (verbatim shape)

1. `git checkout req-024-production-cutover` →
   `error: Your local changes to ... .devsteward/events.jsonl, .devsteward/state.yaml would
   be overwritten by checkout. Please commit your changes or stash them.`
2. `git stash && git checkout req-024-production-cutover` → switched, but the **dev ledger
   delta is now in the stash**.
3. `git stash pop` → `CONFLICT (content)` in `events.jsonl` **and** `state.yaml`, plus
   `CONFLICT (modify/delete): .devsteward/verdict-REQ-024.json` (deleted on dev by the park's
   `_clear_verdict`, modified in the stash).

## Root gap (two compounding causes)

1. **`rework` touches no git (by design) → dirty tree.** `cli.py` rework is documented
   "Touches no git and no REQ file": it flips `develop→recover` / `validate→pending` in the
   working tree and leaves them **uncommitted** on the integration branch. The very next
   `git checkout <feature>` is then blocked by the uncommitted ledger.
2. **No clean *interactive* re-enter-develop verb.** rework's hint is *"Re-run `steward
   run`"* — the **headless** path (spawns `claude -p`). The operator hand-fixing has no
   blessed verb that moves HEAD to the feature branch and manages the ledger, so they reach
   for hand-`git` — and `git stash pop` drops dev's ledger delta onto the feature branch's
   **deliberately-different Decision-8 lineage** (registry on the integration branch, code on
   the feature branch). That fights `reconcile_from_integration` (which takes the integration
   ledger authoritatively at land) → the conflict, every cycle.

The slug mismatch the operator recalls ("validation slug vs development slug") was **not**
reproduced here and cannot arise from slug derivation (develop and validate share one
`slug = _slugify(r.title)`, `source.py:116`) — likely a one-off artifact of an earlier
broken state, not a standing defect.

## Safe manual workaround (until the engine is revisited)

```
# on dev, right after `steward rework REQ-NNN`
git add .devsteward && git commit -m "REQ-NNN: ledger — rework (V-model return)"
git checkout <feature>          # clean now — no stash
# fix code, commit code
steward checkpoint REQ-NNN develop
```

Never `git stash`/merge `.devsteward/` across branches — the feature and integration ledgers
are *meant* to differ; the engine reconciles them at land. (DevSteward itself commits the
rework as a `REQ-NNN: ledger — rework` commit — the same discipline.)

## Candidate fixes (for the revisit, decoupled from REQ-034)

- `rework` commits its own ledger delta (so the tree is clean and the next checkout just
  works), **or**
- the CLI prints the commit-then-checkout guidance instead of only "Re-run `steward run`",
  **or**
- a first-class **interactive re-develop** path that moves HEAD to the feature branch and
  owns the ledger reconcile for hand-fixing (the engine is the bookkeeper — North-star D3).

## Verdict authorship

None asserted. Reviewable evidence only; the engine adjudication belongs to a later REQ once
REQ-024 is green.
