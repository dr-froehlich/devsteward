# Plan 0026 — REQ-047: single-source-of-truth state model (trunk-based on `dev` + a universal transaction boundary)

Covers **REQ-047**. Implemented **by hand**, not under `steward` — the engine has lost the
right to drive its own repair until it is structurally incapable of diverging or stranding
(the firefighting loop diagnosed in REQ-047). We still write a plan first, as always, and
still keep the REQ corpus honest (same-commit discipline: REQ frontmatter + index row + code
in one commit). We just don't `steward advance`.

## Thesis (restate before building)

Two failure modes, two fixes — and the dominant move is **subtraction**:

1. **Divergence** — ledger-on-`dev`-via-worktree + code-on-feature-branch is two locations
   kept in sync across a destructive `git checkout`. You cannot enumerate every precondition;
   you *delete the second location*. → **trunk-based: one branch, one co-located ledger, no
   switching.** The whole REQ-037/040/041/043/044 table stops *existing*.
2. **Stranding** — an un-enumerated precondition lets a raw `CalledProcessError` escape and
   leaves a half-state with no recovery verb. → **a universal transaction boundary:** every
   mutation is fully applied or fully rolled back; an unanticipated edge becomes a clean abort
   + one-line recovery, never a stalemate.

Net effect target: **less engine code**, not more. Stage A is mostly deletions.

## The split — four sub-REQs, shipped independently (REQ-047 Notes a–d)

REQ-047 stays the parent **design** REQ. Each stage below is a real, independently-landable
sub-REQ that `depends_on: [REQ-047]`; each lands under same-commit discipline (its REQ file +
`REQUIREMENTS_INDEX.md` row + code + tests in one commit on `dev`). REQ-047 flips `done` when
Stage D lands. Recommended ids (highest existing is REQ-047):

| Stage | sub-REQ | Title | REQ-047 ACs | Depends on |
|-------|---------|-------|-------------|------------|
| A | **REQ-048** | Trunk-based model — delete the worktree/switch/branch machinery | AC1, (enables AC3) | REQ-047 |
| B | **REQ-049** | Universal transaction boundary + central invariants | AC2, AC3 | REQ-048 |
| C | **REQ-050** | Commit integrity — land refuses a green the commit doesn't capture | AC4 | REQ-048 |
| D | **REQ-051** | Lab fixtures upstream; the System Tester never improvises | AC5 | REQ-048 |

**Sequencing.** A is the foundation (it removes the surface B/C/D would otherwise have to
account for). B layers on the simplified A. C and D are independent of each other and depend
only on A; do C then D (or in parallel) after B. Land A on `dev`, prove green, then B, C, D.

> **One bookkeeping decision to confirm before Stage A** (recommended answer in parentheses):
> materialise REQ-048–051 as four real REQ files vs. keep REQ-047 as a single REQ landed in
> four commits. *Recommend four real sub-REQs* — REQ-047 itself predicts the split and says
> they ship independently, and same-commit discipline wants each independently-shipped stage
> to satisfy its own REQ + index row. The rest of this plan assumes that.

---

## Stage A — REQ-048: trunk-based, delete the machinery

**The new per-step flow (what replaces `_drive_step`'s bracket):** resolve the single live
ledger in the repo root → run the step on `dev` → commit code (+ REQ flip + index) on `dev`,
excluding `.devsteward/` → commit the ledger advance as a trailing `.devsteward/`-only commit
on `dev`. **No branch create, no switch, no worktree, no merge.** A park commits the ledger
close on `dev` and stops — there is nowhere to "return" to.

**Commit shape (decision, stated):** keep **two commits** per landed step — the work commit
(code + frontmatter `done`-flip + index `DONE`-sync, same-commit discipline, *excluding*
`.devsteward/`) and a trailing `.devsteward/`-only ledger commit. Rationale: clean code
history independent of the cursor, and it is the precondition Stage C (commit integrity)
checks against. This is the *minimal* change from today — we drop the worktree indirection and
commit the ledger directly in the main tree; we do **not** restructure the commit count.

### Delete (the subtraction)

- **`core/git.py`** — remove the entire REQ-037 worktree/atomic-topology block:
  `_wt_path`, `_worktree_for_branch`, `integration_worktree`, `remove_integration_worktree`,
  `clean_untracked_ledger`, `dirty_tracked_ledger`, `commit_ledger_at`, `ledger_diff_against`,
  `fetch`*, `feature_behind_remote`, `branch_exists_remote`, `incorporate_remote`,
  `try_merge_no_ff`, `try_reconcile_from_integration`, `reconcile_from_integration`,
  `create_and_switch`, `switch`, `integration_is_ancestor`, `branch_exists`. (*`fetch` +
  `merge_no_ff` are **kept** — but only for the `dev → main` release merge, Decision 2.)
  Replace `commit_all(..., exclude_ledger=...)` with two small methods: `commit_code(message)`
  (stage `-A` except `:(exclude).devsteward`, commit) and `commit_ledger(message)` (stage only
  `.devsteward/`, commit) — both on the main tree, no worktree.
- **`core/seams.py`** — collapse `GitTopology` to its trunk-based surface: `current_branch`,
  `commit_code`, `commit_ledger`, and the release-only `fetch`/`merge_no_ff`. Delete every
  worktree/branch/reconcile method from the Protocol.
- **`core/executor.py`** — delete `_bind_ledger`, `_commit_ledger`, `_sync_evidence_to_worktree`,
  `_return_main_tree_to_integration`, `_record_aborted_switch`, `feature_branch_name`,
  `prepare_branch`, `ready_validate_branch`, `return_to_integration`, `_merge_after_land`,
  `_record_aborted_merge`, the `self._worktree` attr, `feature_branch_template`,
  `integration_phases`-driven merge logic in `_merges_after`, and `_ResolverShim`/
  `branch_resolver` (back-compat for a seam that no longer mutates). `live_ledger()` becomes a
  trivial `return self.ledger` (kept as a stable read entry point).
- **`config.py`** — drop `feature_branch` / `feature_branch_template`. **`build.py`** — drop
  the `feature_branch_template=` wiring.
- **`lint.py`** — delete rule 8 (the feature-branch ledger-diff check) — it asserts an
  invariant that trunk-based makes structurally impossible.

### Simplify

- **`executor.py` `_drive_step`** → `self.run_step(step, ...)` then, on `PARKED`,
  `self._commit_ledger_close(step, "ledger close — parked")` (no `return_to_integration`).
  Drop the `prepare_branch` surface path and the post-land merge bracket entirely.
- **`_commit`** → `self.git.commit_code(message)` (always excludes `.devsteward/`); drop the
  `exclude_ledger=bool(self._worktree)` branch.
- **`mechanical_land` / `commit_deferred` / `_commit_ledger_close`** → commit on `dev`
  directly via `commit_ledger`; remove all worktree routing.
- **`profiles/req/validate.py`** → remove `ex._merge_after_land(...)` calls (3 sites),
  `ex.ready_validate_branch(...)` (the `start` half just sets RUNNING + preps evidence), and
  `ex.return_to_integration()` (2 sites). `_park_pending` / `_park_red` keep their
  `_commit_ledger_close` (now a plain `dev` commit). Evidence is captured in the main tree and
  committed in place — drop the worktree sync comment.
- **`cli.py`** — keep `branch_guard()` (still refuse a commit on `main`). The release path
  (`dev → main`) is the only remaining `merge_no_ff` caller (wrapped by Stage B's boundary).

### Decision 2 stays: the `dev → main` release merge

Keep `fetch` + `merge_no_ff` for the one human-gated release merge. Under Stage B it is
wrapped by the transaction boundary like every other mutation. It is *not* per-step topology.

### Stage A tests

- **Delete** `tests/test_branch_lifecycle.py`, `tests/test_plane_split.py` (they certify the
  deleted machinery). Slim `tests/test_branch_guard.py` to just the `main`-refusal.
- **`tests/conftest.py`** — gut `FakeGitTopology` down to `current_branch`/`commit_code`/
  `commit_ledger` no-ops; remove worktree/branch state modelling.
- **Rewrite** `tests/test_ledger_close.py` to the trunk-based contract: a landed step leaves
  two commits on `dev` (work commit with no `.devsteward/`, then the ledger commit), tree
  clean at rest, **no branch created**, **no `git switch`/`worktree` invoked**. Audit
  `test_req_profile.py`, `test_phase_model.py`, `test_system_test_phase.py`,
  `test_rework.py`, `test_checkpoint.py`, `test_guided_validation.py`, `test_orientation.py`,
  `test_revalidate_provenance.py`, `test_reality_harness.py` for `integration_branch`/branch
  assumptions and update.
- **AC1** (`test_dev_only_cycle_realgit`): a full develop→land cycle on a real `git init` repo
  completes with every commit on `dev`, **no feature branch ref created**, and **no
  `checkout`/`switch`/`worktree`** in the git trace (assert via a recording `GitCli` subclass
  or a `GIT_TRACE`-style spy).

---

## Stage B — REQ-049: universal transaction boundary + central invariants

Layered on the simplified Stage-A code. This is the *resilience* guarantee guards alone can't
give (REQ-047 Decision 3/4).

### New: typed errors

- **`core/errors.py`** — `class PreconditionError(Exception)` and
  `class RecoverableError(Exception)`, each carrying `.recovery: str` (the one-line operator
  instruction). No raw `CalledProcessError` ever reaches the CLI.

### New: the boundary

- **`core/transaction.py`** — `@contextmanager transaction(git, *, label)`:
  1. snapshot `orig = git.head_sha()` (and note whether `.git/MERGE_HEAD` etc. exist);
  2. `yield`;
  3. on any escaping exception: restore the captured snapshot
     (`git reset --hard {orig}` — undoes commits *and* tracked-file mutations back to the
     pre-command commit), then `raise RecoverableError(recovery=…) from exc`.
  - Untracked files created mid-command are left in place (visible, not "applied" state);
    `reset --hard` already restores all committed/tracked state byte-identically (plan-0021
    finding 4 is the precedent that `git` gives us byte-identical restore cheaply).
  - The boundary owns INV-3 (atomic) by construction.

### New: central invariants

- **`core/invariants.py`** — `check_invariants(ex) -> None`, raising `PreconditionError(recovery=…)`
  *before* any mutation:
  - **INV-1 (single source of truth):** the ledger resolves to the one `.devsteward/` at the
    repo root; assert no stray linked worktree and no second ledger. Enforced for **writes**
    *and* reads — the `steward decision` stranding bug was INV-1 unenforced on a write path.
  - **INV-2 (no mutation on an unexpected tree):** refuse to start a mutation mid-merge/
    mid-rebase (`MERGE_HEAD`/`rebase-merge` present) or on `main` (folds in `branch_guard`).
    The *expected* dirty work-tree (the session's own edits) is allowed; an unexpected
    conflicted state is a typed precondition with recovery text, not a crash.
  - INV-3 is the boundary itself (above).

### Wiring

- Every mutating command path — `advance_once`, `run`, `checkpoint`, validate's land/park,
  `rework`, `recover`, `activate`, `decision`, the release merge — calls `check_invariants(ex)`
  then runs its body inside `transaction(...)`.
- **`cli.py`** — one top-level handler catches `PreconditionError` / `RecoverableError`, prints
  `.recovery`, exits non-zero. A bare `CalledProcessError` reaching this layer is itself a bug
  (a mutation that escaped the boundary) — log it loudly.

### Stage B tests

- **AC2** (`test_injected_failure_rolls_back_byte_identical`): wrap a step; force a `git`
  error mid-mutation (a `GitCli` that raises on the Nth call); assert the repo + ledger are
  byte-identical to the pre-command snapshot (same HEAD, same `events.jsonl` bytes) and a
  `RecoverableError` with recovery text surfaced — **no** `CalledProcessError`, **no**
  half-state.
- **AC3** (`test_decision_recovers_regardless_of_head`): `steward decision` and the recovery
  commands succeed from any HEAD/working-tree state; no command is left unrecoverable by a
  parked decision (the historical stalemate is unreachable — INV-1 on writes).

### Stage B — as built (REQ-049, landed on `dev`)

Three faithful refinements surfaced while building, all *implementing* the plan's intent:

- **`check_invariants(ex, *, allow_any_head=False)`.** AC3 (decision/recovery succeed
  *regardless of HEAD*) requires the recovery verbs to be exempt from INV-2's branch/tree
  gate while still INV-1-checked — exactly the plan's note that "the decision-stranding bug
  was INV-1 unenforced on a write." So the four recovery/decision verbs pass
  `allow_any_head=True` (INV-1 only); the committing paths run the full set. INV-2 folding in
  `branch_guard` means an on-`main` mutation now *raises* `PreconditionError` (was a returned
  `RunOutcome.REFUSED`); two REFUSED-on-production tests updated, graceful REFUSEDs unchanged.
- **`transaction(..., pass_through=(...))`.** A lifecycle verb's `LifecycleError` is a
  graceful refusal raised *before* any mutation — a `reset --hard` on it would wrongly
  discard the uncommitted work those verbs exist to leave (`recover` must *preserve* the
  failed attempt's edits). So the boundary passes caller-declared refusals straight through
  without rollback. Wrapping the non-committing recovery verbs would otherwise contradict
  their own contract — flagged and resolved this way.
- **`reset_hard` rejoins the `GitTopology` seam.** The boundary's restore needs it; it is the
  one method Stage A's collapse has to give back — a read-restore, not topology.

Boundary placement: `transaction` wraps `_drive_step` (covers `advance_once`/`run` and, via
`run_step`, the batch validate path), `checkpoint`, and the guided-validate `record`. The
`_commit`/`_commit_ledger_close` git-error swallows are removed so failures reach the
boundary; unit loop suites moved onto the in-memory `FakeGitTopology` seam so that removal
does not regress them (real-git teeth live in `test_transaction_boundary.py`).

---

## Stage C — REQ-050: commit integrity (absorbs REQ-046-F2)

A recorded commit must reproduce its own green. The land step refuses to certify a develop
green whose passing state the recorded commit does not capture.

- In `mechanical_land` / `commit_deferred`, **after** the work commit: assert the committed
  tree is self-sufficient for the green — `git status --porcelain` shows nothing under the
  project's source/test paths left modified/untracked/ignored that the just-passed tests could
  depend on. (Tightest form: re-run the verifier against a clean checkout of the new commit;
  cheapest form: refuse on a non-clean tracked/untracked source tree post-commit.) On failure,
  raise `PreconditionError(recovery="the green depends on uncaptured files X — commit them or
  fix .gitignore, then re-run")` — nothing certified, nothing advanced.
- **AC4** (`test_land_refuses_uncaptured_green`): a develop whose pass depends on a
  `.gitignore`d / never-staged file is refused at land with the gap named; the REQ does **not**
  flip `done`.

### Stage C — as built (REQ-050, landed on `dev`)

Built the **tightest form** (re-run the named gate against a clean extract of the commit),
with two faithful refinements forced by the Stage-B boundary:

- **Placement & rollback (the critical Stage-B interaction).** The plan's literal "raise
  `PreconditionError` after the work commit" would *strand* the commit: a `PreconditionError`
  passes **through** `transaction(...)` without a rollback (REQ-049), so the boundary won't
  undo the work commit for it — the exact half-state Stage C forbids. Resolution (the plan's
  "tightest form needs (b)"): `Executor._assert_green_captured` snapshots `HEAD` *before* the
  work commit, and on a gap does the `git reset --hard <snapshot>` **itself**, *then* raises
  the (now pass-through) `PreconditionError`. That buys both a clean tree (work commit undone,
  REQ flip reverted, the RUNNING/step_started ledger writes wiped) **and** the gap-specific
  recovery line — a non-typed exception would roll back via the boundary but lose the precise
  recovery; a bare pass-through precondition would keep the recovery but strand the commit.
- **Tightest, not cheapest — no path heuristic, no worktree.** The extract is
  `git archive <sha> | tar -x` into a tempdir (only the commit's tracked content). This avoids
  the cheapest form's "source/test paths" heuristic (which would false-positive on
  `__pycache__`/`.venv`) and avoids `git worktree add` (forbidden by trunk-based; INV-1
  actively refuses a stray linked worktree). The interpreter is resolved against the **real**
  repo (the venv is environment, not commit content); only `step.verify` re-runs (not the full
  suite). Real-git only and **fail-open**: no-op with no repo (the in-memory fake), no named
  tests, an unusable env, or no extraction tooling — a safety net must not brick a legit land.
- **Caveat flagged:** the archive re-run imports the package-under-test from the extract
  *unless* an editable install shadows it on `sys.path` (`[[req-test-command-python-m]]`).
  That only bites a project testing its own editable-installed code (DevSteward dogfooding
  itself); consumer projects (FlowSteward) aren't editable-installed, so the extract is
  authoritative there, and AC4's synthetic repo isn't editable-installed either.

Wiring: the check sits in **both** `mechanical_land` (the landing path) and `commit_deferred`
(the deferred-develop path), immediately after the work commit and before any ledger write,
so a refusal's rollback also discards the not-yet-committed ledger mutations.

---

## Stage D — REQ-051: lab fixtures upstream; the tester never improvises (absorbs REQ-045)

A missing lab fixture is a hard-red-and-stop, never create-and-don't-commit (an uncommitted
improvised fixture is exactly the divergence this whole REQ forbids).

- **`devsteward/handbook/` + the `system-test` SKILL.md** (repo `.claude/skills/system-test/`
  and its hardlinked template — see `[[skills-hardlinked-to-templates]]`, edit once): the
  System Tester treats a missing fixture as a hard red and **stops**; it must never write a
  fixture the lab lacks.
- **`profiles/req/validate.py`** — after the session, before the artifact gate certifies green:
  if the tester left **untracked** files under the lab fixtures path, refuse (the tester
  improvised). A missing fixture surfaces as a hard red with the gap captured in the evidence
  event (the `_artifact_gate` "no artifact captured → hard red" is the existing teeth; extend
  it to name a missing committed fixture). No uncommitted fixture is left in the tree.
- **AC5** (`test_missing_fixture_hard_red_no_uncommitted`): a validation whose lab fixture is
  missing stops as a hard red with the gap captured; the tree carries no uncommitted fixture
  afterwards.

### Stage D — as built (REQ-051, landed on `dev`)

Built as the plan specifies; three faithful refinements:

- **The fixtures path is a declaration, not a convention.** The engine is generic and cannot
  know a consumer's `labs/imap/` by name, so a REQ names the committed inputs its validation
  rests on in **`process.fixtures`** (repo-relative paths), alongside `process.lab` — schema
  widened (defaulting `[]`, so every existing REQ is untouched), `ReqFile.process` defaults it.
  References are paths, not REQ ids, so the linter needs no new resolution rule.
- **The improvised file is discarded by the engine, not left for the operator.** REQ-049's
  rollback (`reset --hard`) restores *tracked* state only — an untracked improvised fixture
  would survive it. So `_check_fixtures` unlinks the untracked file itself (scoped to the
  declared fixtures pathspec) before recording the red, so "no uncommitted fixture is left in
  the tree" holds by construction. The check folds into `_artifact_gate` (the existing
  "no artifact captured → hard red" teeth, which already record into the evidence event) and is
  real-git, fail-open (a no-op with no declared fixtures or no repo), like the REQ-050
  self-check. It covers both faces: *untracked under the path* → improvised; *no tracked file*
  → missing.
- **Id collision resolved by renumbering the later stub, not this stage.** The plan reserved
  REQ-051 for Stage D and the landed REQ-049/050 already reference "REQ-051 (lab fixtures)" as
  the remaining stage; a raw "review after migration" stub had since taken the REQ-051 id. To
  keep those cross-refs honest, the stub was renumbered to **REQ-052** (draft, given valid
  frontmatter + an index row) and this stage keeps REQ-051. **REQ-047 flips `done`** with this
  stage (Stages A–D all landed).

---

## Cross-cutting (land with the stage that first contradicts the old text)

- **`CLAUDE.md`** — rewrite the **Branching model** house-convention bullet to trunk-based
  (all work on `dev`; no feature branches/worktrees/switching; `dev → main` release via PR
  only) and retire the "⚠️ Under replacement by REQ-047" note. Lands with Stage A.
- **Memory** — rewrite `[[branching-model]]` to the trunk-based regime; update
  `[[trunk-based-pivot-req047]]` to "landed". (Do via the memory files, not steward.)
- **Schema `supersedes`** (`devsteward/schema/req.schema.json:55`, scalar string-or-null) —
  widen to accept a scalar **or a list** so REQ-047 can name 037/040/041/043/044 directly, and
  loosen `lint.py:102` to iterate. Small, self-contained; land it with Stage A so the four
  retired REQs can be marked `superseded` honestly. (Alternative kept on the table: leave
  scalar + name the root only + prose — but the list is cleaner and the change is tiny.)
- **Retire the superseded REQs** — flip REQ-037/040/041/043/044 (and the 044 stub) to
  `superseded` with their index rows synced, in the Stage-A commit that removes their code.
  REQ-045/046 stubs were already absorbed into REQ-047 (Decisions 5/6, 1/5) — confirm they are
  removed.

## Migration (devsteward's own repo)

Trivial: we are already on `dev`, clean, with no in-flight feature branch in *this* repo. Land
each stage directly on `dev`. **FlowSteward is explicitly out of scope** for this work (owner
decision — do not touch it or reconcile its ledger here).

## Honest scope

This buys *no divergent state* (one source of truth, by construction) and *no unrecoverable
state* (fail-safe boundary). It does **not** buy "no bugs" — it changes the failure mode from
"stalemate + new REQ" to "clean abort + recover + continue," which is the exit from the
firefighting loop.

## Test posture

Real-git teeth for the five ACs (the plan-0021 lesson: fakes can't certify topology behaviour) —
synthetic `git init` repos in a temp dir, only `claude` faked. Unit suites keep running over the
gutted `FakeGitTopology`. `python -m pytest` must stay green at the end of **each** stage before
the next begins (`[[req-test-command-python-m]]`).
