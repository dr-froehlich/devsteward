# REQ-058 AC3 — System Tester findings (guided/attended)

**Date:** 2026-06-20T21:35–21:46Z · **Mode:** `--guided` · AC3 is the `manual` live human oracle.

## Lab / surface that came up
- **cswap 0.13.2**, **2 accounts** configured (slot 1 `peter.froehlich@th-deg.de`, slot 2
  `claude@pfroehlich.de`, slot 2 active). ✅ ≥2-account requirement met.
- **clauder** installed on PATH this session (pipx editable from `/home/peter/projects/clauder`,
  v0.1.0) with operator approval. `gate`/`monitor`/`usage` all functional.
- **clauder REQ-005 (cswap access lock) is DONE** — the race-free serialization of the cswap switch
  that REQ-058's notes flagged as *missing at survey time* now exists. **That caveat is stale.**
- **clauder monitor** ran in a separate background shell (interval 5s) concurrently with gate calls.

## Procedure run + artifacts
- `00-environment.txt` — tools on PATH, CLAUDECODE=1, clauder REQ-005 DONE.
- `10-cswap-accounts.txt` — 2 accounts (slot1 88%/12% headroom, slot2 76%/24% headroom 5h).
- `20-clauder-usage-before.json`, `60-clauder-usage-after.json` — combined-budget snapshots.
- `50-clauder-gate-verdicts.txt` — **the delegation seam the engine shells.** Real verdicts at 6
  thresholds: `proceed`(exit 0) at ≤24% headroom, `wait`(exit 75, wait_seconds=5700) at ≥24%.
  Maps to the provider contract: proceed/switch→ok(0), wait→sleep&re-gate(75), unsatisfiable→stop(69).
- `40-clauder-monitor.log` — 10 concurrent `stay (below-threshold)` polls (monitor + gate coexisting).
- `30-claudejson-integrity.txt` — `~/.claude.json` stayed **valid JSON**, `active_slot` unchanged,
  **no torn switch** across concurrent monitor + gate activity.
- `70-engine-in-the-loop-runbook.md` — operator runbook for the `steward run` part I cannot launch.

## What I could and could not observe
**Observed (artifacts above):** the real delegation seam (`clauder gate --json`) producing the
mapped verdicts; monitor + gate coexisting with **no `~/.claude.json` corruption / no torn switch**
(REQ-005 lock in effect); combined-budget snapshots.

**Not observed here (operator's plain-terminal run — `CLAUDECODE=1` blocks me + can't touch
devsteward's own ledger):**
- the **engine** announcing a per-step gate decision and proceeding across step boundaries in a
  real `steward run` (must run on a *consumer* project, not devsteward);
- a real account **switch** as budget tightens — and with current state clauder correctly *declines*
  to switch (active slot 2 is already the best account; slot 1 has less headroom). A clean switch
  needs the active account to be the worse one, or fresh post-reset headroom. `switch`/`unsatisfiable`
  exit-code mapping is covered by **AC1 regression** (stubbed clauder).

## Anomalies / notes for the human
- REQ-058's "clauder not race-free yet" caveat is **superseded** — clauder REQ-005 landed the lock.
- I left clauder installed on PATH (AC3 needs it; mirrors production). Uninstall with
  `pipx uninstall clauder` if you want the pre-test state back.
- No fixtures were written/improvised; no code/REQ/ledger touched. Verdict is the engine's + yours.
