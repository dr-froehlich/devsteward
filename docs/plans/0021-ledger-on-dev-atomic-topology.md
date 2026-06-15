# Plan 0021 — REQ-037: the ledger lives on `dev` only; topology ops are atomic & recoverable

Covers **REQ-037**. Finishes plan 0017 (ledger-always-committed) for *all* code-carrying
paths, not just the park, and adds the crash-proof topology floor that plan 0017 explicitly
left out ("the green path is fine — it converges via the `--no-ff` merge"; the live
FlowSteward crash disproved that).

## The defect, restated mechanically

`events.jsonl` + `state.yaml` currently ride the **feature branch** during develop/validate
and are carried home by the feature→`dev` `--no-ff` merge. The moment `dev` *and* the
feature branch have each appended to the ledger since the branch was cut — **guaranteed** in
a deferred-validate world (`dev` keeps advancing while a validation parks) — git faces two
independent histories of the same append-only file and **cannot auto-merge** them. The merge
conflicts; the unguarded `check=True` subprocess turns that into an uncaught
`CalledProcessError` and a split repo.

## Real-git findings that ground the design (verified, git 2.43)

1. **If the feature branch makes _no_ change to `.devsteward/`, an advanced-`dev` ←
   feature `--no-ff` merge has zero conflict** (the three-way merge takes `dev`'s side; the
   feature side is unchanged from the merge base). → *the entire crash class dissolves if the
   feature branch never commits the ledger.*
2. **`git checkout dev` refuses when `root/.devsteward` has working modifications** that
   differ from the feature HEAD (even when the content equals `dev`'s). → *the engine must
   never leave `root/.devsteward` dirty on a feature branch; it must not write the ledger
   into the main working tree at all while on a feature branch.*
3. A linked **worktree on `dev`** (`git worktree add <path> dev`) lets the engine append to
   and commit the ledger on `dev` while `root` stays on the feature branch and **clean**.
4. **`git merge --abort` restores HEAD and tree byte-identical** and leaves a clean tree →
   the atomic-recover primitive for AC3.
5. **`git fetch` + `merge --ff-only origin/<feature>`** incorporates a remote-pushed feature
   commit; `git rev-list --count <feature>..origin/<feature>` detects behind-remote → AC4.

## Design

### D1 — the ledger is a `dev` artifact; the engine writes it through a `dev` worktree

- The `GitTopology` seam grows an **integration worktree**: when `root`'s HEAD is the
  integration branch the ledger home is `root` itself (unchanged); when `root` is on a
  feature branch the engine lazily creates a linked worktree checked out on the integration
  branch and **binds the live `Ledger` to it**. Every ledger write of the step (the
  `step_started`/`branch_*` events, the develop/validate events, the cursor, the parked
  decision, captured evidence under `.devsteward/evidence/`) therefore lands on `dev`, and
  the `.devsteward/` commit is made *in the worktree* on `dev`.
- `root`'s working tree, on the feature branch, is **never** touched under `.devsteward/`, so
  it stays clean and `git diff dev...feature -- .devsteward/` is empty (AC2). Code +
  `REQUIREMENTS_INDEX.md` + the REQ frontmatter `done`-flip ride the feature branch as before
  (implementation plane, same-commit discipline) — only the ledger moves.
- **Mechanism choice:** worktree over a `merge=union` driver (rejected by the REQ: it
  mis-merges the cursor) and over commit-tree/merge-tree plumbing (the worktree lets the
  existing `Ledger` read/write real files unchanged and `merge --abort` already gives the
  byte-identical atomicity AC3 wants — finding 4 — so the extra plumbing buys nothing here).

### D2 — every topology mutation is atomic and recoverable

- `fetch`-first on the feature ref; a behind-remote feature is fast-forwarded
  (`--ff-only`) and incorporated before the merge (AC4), not crashed on.
- The merge / reconcile run **without `check=True`**: on a residual conflict the engine
  `git merge --abort`s (repo byte-identical — finding 4), then **surfaces** an actionable
  recovery instruction (attended) or **parks** a decision (`DEVSTEWARD_UNATTENDED=1`). No
  uncaught `CalledProcessError` ever strands the repo mid-merge (AC3).

### D3 — the no-ledger-on-feature invariant is guarded

- The engine refuses to commit `.devsteward/` while `root`'s HEAD is a feature branch
  (the code-commit path stages everything **except** `.devsteward/`; the ledger commit is
  routed to the `dev` worktree).
- `steward lint` flags a feature branch whose `git diff <integration>...HEAD -- .devsteward/`
  is non-empty — a statically-detectable regression of this design.

## Files

- `devsteward/core/seams.py` — extend `GitTopology`: `integration_worktree`,
  `remove_integration_worktree`, `fetch`, `behind_remote`, `incorporate_remote`,
  `try_merge_no_ff` (returns `None` on success, a conflict detail on aborted conflict),
  `commit_all(..., exclude=...)`.
- `devsteward/core/git.py` — real `GitCli` impls of the above (real worktree + abort).
- `devsteward/core/executor.py` — `_rebind_ledger()` binds the live `Ledger`/ledger-git to
  the integration tree by current branch; call after every branch move; code commits exclude
  `.devsteward/`; ledger commits go to the integration tree; `_merge_after_land` /
  `ready_validate_branch` use the atomic merge with surface/park; at land remove the worktree,
  switch `root` to `dev`, merge (root ends on `dev`, matching the REQ-032 contract).
- `tests/conftest.py` — `FakeGitTopology` no-op impls (worktree == root; the fake never
  modelled file placement — the REQ's point — so unit suites are unaffected and the new
  behaviour is certified only by the real-git ACs).
- `devsteward/lint.py` (+ cli wiring) — the feature-branch ledger-diff rule.
- `tests/test_plane_split.py` — AC1–AC5 on a real `git init` repo (+ a bare remote for AC4),
  `FakeRunner` over real `GitCli` (the plan-0017 real-git precedent).
- `tests/test_ledger_close.py` — update the deferred-develop assertion to the new contract
  (the trailing ledger checkpoint lands on `dev`, the feature tip is the pure-code work
  commit) — REQ-037 supersedes plan 0017's ledger-on-feature placement.

## Acceptance (REQ-037 AC1–AC5)

All five run against a real repo (`tests/test_plane_split.py`); only `claude` and the
interactive bring-up are faked. AC1 green deferred land has no `.devsteward/` conflict; AC2
empty `dev...feature` ledger diff + events on `dev`; AC3 forced conflict aborts byte-identical
+ parks under unattended; AC4 fetch-first incorporates a remote feature commit; AC5 the guard
refuses a feature-branch ledger commit and `steward lint` reports the static violation.

## Out of scope

The cross-host deploy channel (Finding 90) = **REQ-038** (depends on this). Concept-phase =
REQ-039. No devsteward lab — synthetic real-git repos in a temp dir; REQ-034's own AC6 is the
live witness, scheduled **after** this lands.
