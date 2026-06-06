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

## Attended vs unattended

- **`steward advance`** (and the `/advance` skill): do exactly one checkpoint, stop at
  forks, print the fixed report. This is the human-in-the-loop mode.
- **`steward run`:** march every eligible step headless; park on forks; stop on usage
  limits or a hard failure so a human can look.

## The fixed report

Every attended checkpoint ends the same way, so orientation is instant:

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
