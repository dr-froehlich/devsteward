# REQ-034 AC6 — guided procedure for Peter (plain FlowSteward terminal)

Run these in a **plain terminal tab** (NOT inside a Claude session). Each step maps to the
Decisions it exercises; sign off the `manual` verdict against Decisions 1–7. The **engine**
records the verdict — you give it, this session does not.

```sh
cd /home/peter/projects/flowsteward
```

## Step 1 — Guided session + engine-recorded verdict (Decisions 1, 2, 6, 7)

```sh
steward validate REQ-024
```

Observe and judge:
- It **preps** (evidence dir, RUNNING, branch made ready) then brings up an **interactive
  Claude session in the foreground**, attached to this terminal — the *editor pattern*
  (TTY inherited), **not** `claude -p`, **not** detached.
- That session **prepares REQ-024's cutover surfaces** (the served console / worker /
  deploy surface AC6 of REQ-024 names) and **walks you through the procedure, answering
  questions** — **not** a bare `y/N`. *(This is the heart of Decision 1: the human gets the
  same orientation tax the engine oracle gets.)*
- When you give a verdict, the **engine records it** — the session cannot turn the gate
  green (Decision 2).

## Step 2 — Pending park does not freeze the project (Decision 3, AC3)

Pick **defer / pending** at the verdict, then confirm:
- working tree **clean**; **HEAD back on `dev`** (integration branch); feature branch
  **intact and unmerged**;
- the park is **visible from `dev`** (develop-done, validate blocked, the decision, the
  evidence — *not* stranded on the feature branch):
  ```sh
  git checkout dev && grep -c 'REQ-024:validate' .devsteward/events.jsonl
  ```
- a subsequent `steward run` (or `steward status`) **advances other eligible REQs** — the
  waiting human is a work-item, not a blocked pipeline.
  *(Note anomaly 2: to also exercise the reconcile-from-advanced-dev path in Step 3, this
  is where dev should genuinely advance.)*

## Step 3 — Clean resume + land on green (Decision 5, AC4)

Later, **from `dev`**:
```sh
steward validate REQ-024
```
Confirm it **finds the in-flight validate step** recorded on dev, **reconciles** the
behind-but-merged feature branch by taking dev's ledger lineage authoritatively (no
append-only collision) — **not** an "diverged branch" refusal — and on a **green** verdict
**fires the deferred mechanical land + merge** (REQ-024 → done, branch merged to dev, clean
tree).

## Step 4 — Declined verdict is reworkable from the integration branch (Decision 7, AC5)

For the declined edge (your prior 2026-06-13 decline is the realistic case): confirm a
**declined** verdict → **red park whose message points at `steward rework`**, and that it
is **reworkable from `dev`** (the red is recorded on dev, not stranded on the feature
branch — finding 70):
```sh
git checkout dev && steward rework REQ-024   # should find the red, not error
```

## Sign-off

Sign off the AC6 `manual` verdict against **Decisions 1–7**: was the human **guided** (not
handed a bare `y/N`), the **verdict engine-recorded**, the **pipeline not frozen** while
pending, the **resume clean and the land green**, and a **declined verdict reworkable from
dev**. The engine records your verdict; end this guided session first.
