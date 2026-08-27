# System-test notes — REQ-093 AC9

## Observation surface

- DriveSteward checkout: `../DriveSteward`, branch `dev`, clean working tree.
- Retrofit commit: `c8e2694` "Backlog under the engine — the shipped grammar, take-up on
  REQ-019, and a recorded hold" (parent `40102d1`).
- Ran `steward lint` and `steward backlog-list` from DriveSteward's root using the pipx
  editable `steward` (devsteward 0.2.0, `dev` branch).

## Findings against AC9 (a)-(d)

**(a) All 15 items survive, needs unaltered, provenance correct.**
Confirmed by `03_backlog_diff.txt`: 15 rows in the post-retrofit table, needs text
byte-identical to the pre-retrofit rows, origin column is `proposed` for exactly
`rapid-verdict` and `measured-as-used`, `operator` for the other 13. **Matches.**

**(b) REQ-019 carries `backlog_refs` naming `auto-smart-refresh` and
`drive-true-parameters`, and `backlog-list` shows both `in-progress`.**
`REQ-019.md` frontmatter: `backlog_refs: [auto-smart-refresh, drive-true-parameters]` —
matches. But `steward backlog-list` (`02_steward_backlog_list.txt`) renders both as
`attempted`, not `in-progress`, because REQ-019's own `status:` is `done` (confirmed in
both its frontmatter and `REQUIREMENTS_INDEX.md`). Per the REQ-093 derived-status table
this is the *engine acting correctly* — `in-progress` is defined as "a REQ referencing it
is not yet done"; `attempted` is "every referencing REQ is done, no verdict yet". REQ-019
went to done in the time between AC9 being authored (assuming REQ-019 still open) and this
validation run, so the literal wording of (b) does not match current live state, even
though the underlying take-up link and the derivation logic both appear correct.
**Literal-text mismatch — not a grammar defect. Flagged for the human's sign-off call.**

**(c) The seed prose and the notes section survive the conversion.**
`03_backlog_diff.txt` shows the diff hunk ending at `## Notes on the seed` with no further
changes below it — the notes section is untouched. **Matches.**

**(d) `steward lint` is clean in DriveSteward.**
`01_steward_lint.txt`: `lint: OK`, exit 0. **Matches.**

## Artifacts in this directory

- `01_steward_lint.txt` — `steward lint` output/exit code
- `02_steward_backlog_list.txt` — `steward backlog-list` output/exit code
- `03_backlog_diff.txt` — `git diff 40102d1 HEAD -- docs/BACKLOG.md`
- `04_current_BACKLOG.md` — current `docs/BACKLOG.md` snapshot
- `05_current_backlog.jsonl` — current `.devsteward/backlog.jsonl` snapshot
- `06_REQ-019.md` — current `REQ-019.md` snapshot
- `07_notes.md` — this file
