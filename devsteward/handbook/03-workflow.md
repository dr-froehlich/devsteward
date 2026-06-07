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
  skill verifies, the skill commits (same-commit discipline), and at a fork it asks via
  `AskUserQuestion`. The human reviewing the work is the guarantee — trust comes from the
  person, not the engine.

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
