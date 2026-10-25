# Plan 0039 — REQ-063: non-destructive capture gate

Covers **REQ-063**. The REQ-050 commit-integrity gate `git reset --hard`'d a green,
paid-for develop session away (FlowSteward REQ-043 postmortem). This re-architects the land
path so verified work is never destroyed, and an environment skip is no longer mistaken for a
capture gap.

## The design (attended review — `develop: split`)

The conflation REQ-050 made: it treated a *failed post-commit quality judgment* as a *failed
mutation* and `reset --hard`'d the work away. The fix reframes the atomicity: **certification
is the atomic unit; the work commit is durable the moment `verify` is green.**

Two candidate mechanisms were weighed:

1. **commit pure code → check the commit → `amend` the flip in on clean.** Needs a new
   `amend_code` seam method on `GitTopology` + `GitCli` + the in-memory fake, and the fake's
   commit-count fidelity gets fiddly (an amend must *replace*, not append).
2. **check the staged tree *before* committing (chosen).** Stage the code (exactly what
   `commit_code` stages — tracked/staged only, gitignored/untracked excluded), `git
   write-tree` to a tree object, run the named tests against a clean `git archive` extract of
   that tree. On clean → flip (`on_verified`) + commit once (code + frontmatter `done` + index
   — same-commit discipline intact). On a gap → commit the pure code only (no false `done`
   claim) and surface the SHA. **No `reset --hard`, no new seam method.**

Mechanism 2 wins on subtraction (no new seam, no fake-fidelity trap) and is strictly more
correct (the check runs on pure code, not code+flip). The check moving *before* the commit is
what removes the rollback entirely: there is nothing to undo because nothing was over-committed.

## Files

- `devsteward/core/executor.py`
  - `mechanical_land` / `commit_deferred` → both delegate to a shared `_land_checked(step,
    detail, driver, *, certify)`: run `_capture_gap(step)`; on a gap, **commit pure code**,
    set the step `FAILED`, append a `capture_gap` event naming the commit, commit the ledger
    close, and return a **non-stopping `VERIFY_FAILED`** (mirrors REQ-056's land-refusal — a
    repeatable mechanical failure, not a destructive exception). On clean, certify: `on_verified`
    (only when `certify`), the one `_commit`, cursor + `DONE` + the `checkpoint`/`develop_committed`
    event, ledger close.
  - Replace `_assert_green_captured` (post-commit reset+raise) with `_capture_gap(step) -> str
    | None` (pre-commit, non-destructive) + `_stage_and_write_tree() -> str | None` (`git add
    -A -- :(exclude).devsteward` then `git write-tree`). Keep `_green_gap_at` (now takes a
    tree-ish) and `_extract_commit` (accepts a commit *or* tree ref).
  - `_reproduces_green`: **a skip is no longer a gap** — only `fail` / `error` /
    zero-collection is. (`verify` already forbids skips, REQ-028, so a test that passed verify
    but skips in the bare extract is missing a *runtime environment*, not a source file.)
  - Remove the now-unused `PreconditionError` import / `snapshot` plumbing in the land tail.
  - The **validate phase stays exempt** (`step.phase == "validate"` → no gap), unchanged.

- `tests/test_commit_integrity.py` — rework to the four REQ-063 ACs (below) + keep the two
  validate controls (`test_validate_land_certifies_despite_live_lab_skip`, and the develop
  control now inverted).

## Acceptance tests (real-git teeth; the in-memory fake has no `.git`, so the check is a no-op there)

- **AC1** `test_capture_gap_preserves_work_and_surfaces_sha` — a develop green that depends on
  a gitignored *source* file (it FAILS from the bare extract) is **not destroyed**: the
  pure-code work commit is reachable on `dev`, the REQ stays `open`, the step is `FAILED`
  (repeatable), the result is `VERIFY_FAILED` naming the commit, and HEAD advanced by exactly
  the work commit (no reset).
- **AC2** `test_environment_skip_is_not_a_capture_gap` — the all-skip shape (a test that passes
  in verify with its env present, then only *skips* from the bare extract) **certifies** `DONE`
  on a develop land.
- **AC3** `test_self_sufficient_green_certifies` — a green depending only on committed source
  lands `DONE` (no false positive); the landed commit carries the `done` flip (same-commit
  discipline) and the tree is clean.
- **AC4** `test_withhold_recovery_is_honest_and_names_sha` — the withheld-certification message
  names the preserved commit SHA and frames the cause as an uncaptured *source/test* file
  (explicitly *never a secret*), not the postmortem's blanket "commit them / fix .gitignore".

## Out of scope

The intake-side prevention (REQ-064, sibling) and the FlowSteward AC fix (theirs).
