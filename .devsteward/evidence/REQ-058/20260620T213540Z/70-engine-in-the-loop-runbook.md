# REQ-058 AC3 — engine-in-the-loop runbook (operator, plain terminal)

The System Tester cannot launch this part: `CLAUDECODE=1` in this session, so the engine's
`claude -p` spawn is refused (anti-nesting guard), and DevSteward's own ledger is mid-validation
(must not be advanced). Run the engine-in-the-loop observation yourself in a **plain terminal tab**
on a **consumer** project (e.g. FlowSteward), not on devsteward itself.

## Surfaces to have open
- **Shell A** — `clauder monitor --interval 30 --threshold 95` (the out-of-band monitor; engine
  never spawns it).
- **Shell B** — `watch -n 5 'clauder usage --json | jq "{active_slot, combined}"'`.
- **Shell C** — the run: `cd <consumer-repo> && steward run` (or `steward advance` for one step).

## What to confirm (AC3)
1. **Engine calls clauder, never cswap directly.** At each step boundary the engine announces a
   gate decision sourced from `clauder gate`. Cross-check: the engine's announced verdict matches
   what `clauder gate --threshold T --json` returns; no direct `cswap --switch-to` originates from
   the engine (only clauder switches).
2. **Accounts switch as combined budget tightens.** Watch Shell B's `active_slot` change when the
   active account's headroom drops below another account's — the switch is performed by clauder.
3. **No torn switch / corrupted ~/.claude.json.** `jq empty ~/.claude.json` stays exit 0
   throughout; `active_slot` transitions are clean (no oscillation/garbage).
4. **The run proceeds across step boundaries** (gate admits, step launches, advances).

## Live-data caveat (captured this session, 21:44Z)
With the current account state — slot 2 (active) **24% headroom**, slot 1 **12% headroom**,
combined **39%** — `clauder gate` returns:
- `proceed` (exit 0) at threshold ≤ ~24 (admit on the active, already-best account; **no switch**),
- `wait` (exit 75, `wait_seconds≈5700` ≈ 95 min) at thresholds ≥ ~24 (neither account clears it;
  wait for the 5h reset).

So a live run **right now** will exercise the **proceed** path or the **wait** path, but cannot
cleanly demonstrate a **switch** — the active account is already the best, and forcing a switch
would require burning it below slot 1. To observe the switch sub-claim cleanly, run after a 5h
reset opens fresh headroom (slot 1 resets ~01:20, slot 2 ~02:39), or when the active account is the
*worse* of the two. The `switch` (exit 0) and `unsatisfiable` (exit 69) verdict→mapping are already
covered by AC1's regression against a stubbed clauder.
