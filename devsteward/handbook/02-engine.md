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
5. **verifies** — runs the step's named acceptance tests; green is mandatory (a step with
   no tests marker-trusts, which a profile may forbid where it matters — see below);
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
thinking; the engine holds the guarantees. A fork the model can't resolve becomes a
recorded, surfaced decision — never a guess committed to history. The engine also owns the
**single commit** (the skill leaves the working tree dirty and does not commit), so each
checkpoint lands as one authoritative commit rather than a skill commit plus an engine one.

These guarantees exist only in the **batch** mode (`steward advance` / `steward run`, driving
`claude -p` headless). A human running `/advance` directly in a live session has no executor
in the loop and so gets none of them: they verify and commit themselves, and may ask at a
fork. See the two-mode contract in `03-workflow.md`.

Verification has teeth **where the work is delivered**. In the REQ profile, `design` and
`build` advance the cursor (they carry no per-phase tests), but a REQ is not done until it
**lands**, and a `land` step must run at least one named acceptance test the engine re-runs
itself — a land step that declares none is *refused*, not trusted (`ReqVerifier`). So a
no-op `build` is caught at land when its acceptance tests fail: the guarantee holds for the
"done" that matters. (Earlier this was only true by accident — every phase marker-trusted,
so a REQ with no tests at all could reach `done`. That false-done path is now closed.)

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
