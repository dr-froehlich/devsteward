# 02 · The engine

The engine is two layers: a **content-agnostic executor core** and a swappable
**profile** on top. This is what lets DevSteward "run any Claude automation" while still
shipping a sharp opinion about requirements.

## The executor core (`devsteward/core/`)

Knows nothing about requirements. For each eligible step it:

1. **resolves** the next step from the ledger in dependency order (status `pending`, all
   `depends_on` `done`);
2. **prechecks** the account/quota gate;
3. invokes `claude -p "<command>"` headless (stream-json, watchdog, limit detection);
4. **park-and-surface:** if the skill raised a fork, leaves the step blocked and moves on;
5. **verifies** — runs the step's named acceptance tests; green is mandatory;
6. **commits** and **advances** the ledger to `done`.

### The four seams (`core/seams.py`)

| Seam | Question | Generic profile | REQ profile |
|------|----------|-----------------|-------------|
| `StepSource` | what are the steps? | explicit list in `state.yaml` | derived from REQ files |
| `Verifier` | did it succeed? | run named tests | run named tests |
| `DecisionGate` | what at a fork? | park-and-surface | park-and-surface |
| `AccountProvider` | which quota? | single-account | claude-swap, degrades |

### Why the engine owns verification and forks

So unattended automation can't be **talked into a false "done"**. The model does the
thinking; the engine holds the guarantees. A step only reaches `done` after the engine
*itself* re-runs the acceptance tests and sees them pass. A fork the model can't resolve
becomes a recorded, surfaced decision — never a guess committed to history.

## The ledger (`.devsteward/`)

- `state.yaml` — round-trip-stable YAML: the profile, the cursor, the per-step status
  overlay, and parked `decisions:`.
- `events.jsonl` — append-only, git-friendly event log: `step_started`, `verify`,
  `checkpoint` (with commit sha), `decision_parked`, `decision_answered`, …

The ledger holds *no requirement content* — only where the cursor is and what happened.

## Account / quota (`core/accounts.py`)

Lifted and generalized from the proven `run_batch*.py` quota machinery. With `cswap` on
PATH, `claude` is routed through claude-swap (two-account, `--use N` pinning, adaptive
gate). Without it, the provider degrades to plain single-account and logs "proceeding
without quota check" — it never hard-fails on a missing tool.

## Park-and-surface

When the engine shells out headless it sets `DEVSTEWARD_UNATTENDED=1`. Skills then *write
a decision request to the ledger and stop* instead of blocking on `AskUserQuestion`. The
engine records it (`state.yaml` + `events.jsonl`), notifies, and advances to the next
independent step. `steward decision answer <id> "<answer>"` unblocks it; the next `run`
resumes. **The interview stays sacred** — a fork is never auto-resolved.
