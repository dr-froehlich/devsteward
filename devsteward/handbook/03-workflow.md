# 03 · The REQ workflow

The shipped profile turns every active requirement into a three-checkpoint cycle and
sequences requirements by their dependencies.

## Design → Build → Land

For each active REQ (`open` / `in-progress` / `blocked`) the REQ profile derives three
steps:

| Step | Phase | What happens | Verified? |
|------|-------|--------------|-----------|
| `REQ-NNN:design` | A · Design | Approach, interfaces, files, tests to write | — |
| `REQ-NNN:build`  | B · Build  | Implement + write the acceptance tests | — |
| `REQ-NNN:land`   | C · Land   | Make tests green; flip status to `done` | **yes** |

`build` depends on `design`; `land` depends on `build`. The **land** step carries the
REQ's acceptance `test:` commands as its verification, so the engine re-runs them before
marking the requirement done.

## Sequencing whole requirements

`REQ-B:design` depends on `REQ-A:land` for each `REQ-A` in `REQ-B.depends_on`. So a
requirement only starts once its prerequisites have fully landed, while **independent
requirements interleave freely**. A dependency that is already `done` is satisfied and
dropped; a dependency that is draft, dropped, or missing leaves the dependent correctly
blocked (and `steward lint` flags it).

## Branching model

DevSteward uses a two-line model. `main` is **production** — release tags are cut here and
consumers pin them. `dev` is the **integration** branch: the default working and merge
target. **Declaration lives on `dev`; only implementation branches** — intake (REQ
frontmatter, index row, roadmap), plans, and the ledger are committed directly on `dev` (a
requirement is a registry entry, not behavior; forking the shared registry races id
allocation and conflicts the index/roadmap), while **implementation** (code + acceptance
tests + the status-flip to `done`) goes on a feature branch and merges into `dev` by a plain
local merge (no PR). `dev` is promoted to `main` via a PR.

This is **engine-enforced**, not just convention: before any step runs, the executor checks
the current branch, and if it is the production branch it **refuses** — it invokes no
`claude`, commits nothing, leaves the step pending, and prints a guard message naming the
branch and the fix. Off the production branch it proceeds normally. The branch names are
configurable in `.devsteward/config.yaml`:

```yaml
git:
  production_branch: main      # repos using `master`/`release` set it here
  integration_branch: dev
```

The guard protects the production branch only and has no opt-out — strictness is the point.
It does not create branches or open PRs; git topology stays the human's job.

## Two modes: batch worker vs. interactive pair

`/advance` is one skill run two ways, with **different contracts**. The fork that was once
ambiguous is settled: *the engine commands are a batch worker; the bare skill is an
interactive pair.* The switch is the `DEVSTEWARD_UNATTENDED` environment variable, which the
engine sets when it shells out.

- **Batch worker — `steward advance` / `steward run`.** Both drive `claude -p` headless
  (`DEVSTEWARD_UNATTENDED=1`); there is no human channel. The **engine owns the guarantees**:
  it re-runs the acceptance tests itself (teeth at land), it makes the single commit, and it
  advances the ledger. A fork is never asked — it is **parked** and surfaced. `steward
  advance` does one checkpoint; `steward run` marches every eligible step, parking on forks
  and stopping on a usage limit or hard failure so a human can look.
- **Interactive pair — `/advance` in a live session.** A person runs the skill directly in
  Claude Code. There is no executor in the loop and therefore **no engine guarantees**: the
  skill verifies, the skill commits (same-commit discipline), **the human advances the ledger
  by hand** (mark the step done + record the checkpoint, or the next `/advance` redoes it),
  and at a fork it asks via `AskUserQuestion`. The human reviewing the work is the guarantee —
  trust comes from the person, not the engine. *(That hand-advance of the ledger is the gap
  REQ-018's `steward checkpoint` closes — until it lands, it is a hand-edit of
  `.devsteward/`.)*

**One commit, one owner.** Commit ownership is exclusive by mode: the engine commits in
batch, the skill commits interactively — *never both*. (Earlier the skill committed even
under the engine, which then committed again — a double commit; resolved by keying the
skill's close step off `DEVSTEWARD_UNATTENDED`.)

## The fixed report

Every checkpoint ends the same way, so orientation is instant:

```
Did:       what this checkpoint produced
Cursor:    new ledger position
Review:    one line — what to look at
Decisions: parked forks, or "none"
Next:      the next eligible step
```

## A day in the life

```sh
steward status                       # where are we?
/intake "let users export to CSV"    # interview → draft REQ-014
steward lint                         # green?
steward advance                      # design REQ-014
steward advance                      # build REQ-014 (+ its tests)
steward advance                      # land REQ-014 (engine runs the tests)
# or, hands-off:
steward run                          # march everything eligible; park on forks
steward decision list                # anything parked?
steward decision answer DEC-001 "use RFC 4180 quoting"
steward run                          # resume
```
