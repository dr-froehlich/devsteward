# Postmortem — orienting from a feature branch after REQ-037, and a double `steward checkpoint`

- **Date:** 2026-06-15
- **Project:** DevSteward itself (dogfooding), branch `req-036-sync-skills` / `dev`.
- **Trigger:** an interactive `/advance REQ-036` session, run the day REQ-037 (*the ledger
  lives on `dev` only; feature branches carry pure code*) landed. This was a **live test of
  REQ-037's ledger-on-dev model**, and the first time an operator oriented a fresh `/advance`
  session *from a feature branch* under the new topology.
- **Severity:** low. No code lost, no spec drift, end-state ledger correct. One redundant,
  **unpushed** ledger commit was created on `dev` and then cleanly reverted. The value here
  is what the live test taught us, not the (self-inflicted, recovered) damage.
- **Verdict on REQ-037:** **positive.** The new topology worked end-to-end exactly as
  designed. The defect is in the *orientation surface* the new topology leaves for whoever
  resumes work on a feature branch — not in the topology itself.

---

## What actually happened (corrected timeline)

The prior `/advance REQ-036` session did everything **correctly** under REQ-037:

| Commit | Branch | What |
|--------|--------|------|
| `9cc9197` | `dev` (merge-base) | `REQ-036: activate — draft → open` — declaration on `dev` ✓ |
| `bb5ca1b` | `req-036-sync-skills` | the develop code (cli, `skillsync.py`, plan 0022, tests) — **pure code, no `.devsteward/`** ✓ |
| `3aec3dc` | `dev` (via worktree) | `steward checkpoint REQ-036 develop` ledger close: `develop_committed` → `bb5ca1b`, deferred land (REQ-036 has a `manual` AC5), branch left **unmerged** for `validate` ✓ |

That is the textbook REQ-037 shape: declaration and ledger on `dev`, pure code on the
feature branch, ledger writes routed into the `dev` linked worktree
(`.devsteward.devsteward-dev-wt`), the feature branch carrying **no** ledger.

Then this session (a fresh `/advance REQ-036`) **mis-diagnosed the state and re-ran the
checkpoint**, producing a redundant `be8fbb5` on `dev` with duplicate `verify` +
`develop_committed` events (the second `develop_committed` carrying `commit: null`).

---

## Finding 1 — orientation reads the *stale* feature-branch ledger (the root cause)

### What happened

The `/advance` skill's step 1 says: *"Read `.devsteward/state.yaml` for the cursor."* On a
feature branch under REQ-037 that file is a **frozen snapshot from branch-cut time** — the
live ledger now lives in the `dev` worktree, and the feature branch deliberately never
receives ledger writes. So the main-tree `.devsteward/state.yaml` on `req-036-sync-skills`
still reads:

```
cursor:
  step: REQ-037:develop          # stale — frozen at branch-cut
# ...and has NO REQ-036 step at all
```

`grep REQ-036 .devsteward/events.jsonl` in the main tree likewise returned **nothing**.
From that I concluded "`steward checkpoint` never ran for REQ-036" — when in fact it had
run and its writes were sitting in the `dev` worktree ledger the whole time.

### Why it's a DevSteward defect (not operator error in isolation)

The `/advance` skill is part of DevSteward. REQ-037 moved the live ledger to `dev` but the
skill's orientation instruction still points at the main-tree `.devsteward/state.yaml`,
which is now authoritative **only when you are already on the integration branch**. On a
feature branch it is guaranteed-stale. The skill and the topology disagree — the same class
of promise/mechanism contradiction this project keeps surfacing.

The deeper tension REQ-037 introduces: *feature branches carry pure code* means anyone
working **on** a feature branch has **no local view of the live cursor/status**. They must
know to look in the sibling `dev` worktree — and nothing in the tooling tells them that.

### Fix directions (for a follow-up REQ)

- The `/advance` orientation step must read the **live** ledger (the `dev` worktree's
  `.devsteward/`), not the main tree's, whenever the current branch is not the integration
  branch — or, better, get the cursor/status through a `steward` command that already binds
  the ledger correctly (`steward status` does `_bind_ledger`), rather than by reading the
  file directly.
- Consider a `steward where` / making `steward status` the *only* sanctioned way to read the
  cursor, so no operator (human or Claude) ever hand-reads a branch-local ledger snapshot.

## Finding 2 — `steward checkpoint` is not idempotent on an already-`done` step

### What happened

`steward checkpoint REQ-036 develop` ran a **second** time against a step already at
`status: done`. Instead of refusing, it re-verified (green) and appended a duplicate
`develop_committed` event plus a redundant ledger commit (`be8fbb5`). Because the develop
work was already committed, the second commit found a clean tree and recorded
`develop_committed` with **`commit: null`** (`git.commit_all` correctly returns `None` on a
clean tree — `core/git.py:70`), a strictly worse provenance record shadowing the real
`bb5ca1b` one.

### Why it matters

A guard — *"`REQ-036:develop` is already `done`; nothing to checkpoint"* — would have caught
the mis-diagnosis from Finding 1 *at the mechanism*, turning a wrong belief into a no-op
instead of a duplicate ledger write. Checkpoint is meant to be the single authoritative
bookkeeper; re-running it should be safe.

### Fix direction

`steward checkpoint` should refuse (or no-op with a clear message) when the target step is
already `done`, the same way it refuses a System-Test step and a red gate.

## Note — the `commit: null` provenance shadow

Even on a legitimate single run, a deferred-land develop whose code is *already committed by
the time `commit_deferred` runs* records `develop_committed: commit=null`. In the normal
flow the engine makes that commit itself, so the sha is captured (as `bb5ca1b` was at
`3aec3dc`). It only goes null on a re-run. Worth keeping in mind if any tooling reads the
*latest* `develop_committed` to recover the develop sha.

---

## What I did about it

- **Reverted my duplicate.** Reset the `dev` worktree from `be8fbb5` back to the legitimate
  `3aec3dc` (`git -C <dev-worktree> reset --hard 3aec3dc`). `be8fbb5` was unpushed
  (`origin/dev` is far behind), the tip of `dev`, parented on `3aec3dc`, with nothing
  depending on it — undoing my own seconds-old error, not rewriting shared/landed history.
- **Recovery handle:** the dropped commit is `be8fbb56e5a8e4146054aaecde7b56883f34fd78`
  (in the reflog) if it is ever needed.
- After the reset, REQ-036 has exactly its two legitimate events (`verify` +
  `develop_committed` → `bb5ca1b`); `dev` ends at `3aec3dc`.

## Current state of REQ-036 (unchanged by the incident)

- `REQ-036:develop` — **done** (deferred land). Cursor at `REQ-036:develop`.
- REQ-036 frontmatter still `status: open`, index untouched, feature branch **unmerged** —
  correct: the flip + index sync + `--no-ff` merge fire when `REQ-036:validate` (the
  `manual` AC5 Finding-50 closure on FlowSteward) goes green via `steward validate REQ-036`.
- AC1–AC4 (regression) green; `steward lint` OK; plan `docs/plans/0022-sync-skills-drift.md`
  names the REQ.

## Lessons

1. **Under REQ-037, never orient by reading a feature branch's `.devsteward/`.** It is a
   branch-cut snapshot. The live ledger is the `dev` worktree — read it through a `steward`
   command, not the file. This bit *me*, the most context-rich operator possible; it will
   bite every consumer harder.
2. **The bookkeeper must be idempotent.** Re-running `steward checkpoint` on a `done` step
   should be a guarded no-op, not a duplicate write.
3. **REQ-037's core mechanism is sound.** The ledger-on-dev / pure-code-feature-branch /
   deferred-land topology executed correctly end-to-end. What REQ-037 changed and did *not*
   carry along is the *read* path operators use to orient.
