# 0006 — Branch lifecycle automation (REQ-020)

**Date:** 2026-06-08
**Status:** Design (REQ-020:design). Build + Land pending.
**REQ:** [REQ-020](../requirements/REQ-020.md) — the executor manages the implementation
feature branch end-to-end. `depends_on: REQ-011 (production guard), REQ-019 (integration guard)`.

REQ-011 and REQ-019 drew the branching map but left the human to walk it: every REQ has two
manual git steps bracketing it — create the feature branch before `build`, merge it back
after `land`. This REQ moves that create→merge dance into the engine, gated strictly on
`phase ∈ {build, land}` so it is safe exactly where REQ-019's over-eager auto-branching was
not (it branched on *declaration*).

The REQ's Decisions table settles every *whether*; this design is purely *how*. The two
load-bearing reversals it encodes: REQ-019's integration-branch **refusal** for `build`/`land`
becomes **management** (create+switch), and the executor now mutates git topology (creates
branches, merges) where before it only *read* the current branch through a resolver.

## Approach in one paragraph

Introduce a small **`GitTopology` seam** that owns the mutating git operations
(create+switch, switch, merge `--no-ff`, ancestry check, commit-all) alongside the existing
read of the current branch. The default implementation shells out to `git`; a fake in
`conftest` simulates branch state in memory so the full loop is exercised without a real
checkout (the same goal that made `branch_resolver` injectable today). Replace
`Executor.step_branch_guard` (the REQ-019 refusal) with `Executor.prepare_branch`, called by
both drivers *before* `run_step`: on the integration branch an implementation step now
**creates+switches** to `req-<num>-<slug>` (config-driven) instead of refusing; a `design`
step still stays on the integration branch; a diverged pre-existing branch is **surfaced**,
not silently reused. After a **green `land`** (and only then), `_merge_after_land` commits the
trailing ledger write, switches to the integration branch, and merges the feature branch
`--no-ff` with the co-author trailer — leaving the integration branch's tree and ledger clean
at rest. The REQ-011 production guard (`branch_guard()`) is untouched.

## Why a seam, not more module-level `subprocess` calls

`branch_guard`/`step_branch_guard` only ever *read* the branch, so a single injectable
`branch_resolver` callable sufficed. REQ-020 must *mutate* topology, and the engine's tests
deliberately run without a real git repo (`conftest`'s no-git goal; `test_branch_guard`
injects `branch_resolver=lambda _root: branch`). A callable can't model create/switch/merge.
So the read-only resolver is promoted to a `GitTopology` object with a real (`GitCli`) and a
fake implementation; the fake holds branch state so create→run→merge is assertable in memory.
`branch_resolver` is kept as a thin back-compat shim (if passed, it backs `current_branch`).

## Data shapes & interfaces

### `GitTopology` seam (`devsteward/core/seams.py`)

```python
class GitTopology(Protocol):
    def current_branch(self) -> str: ...
    def branch_exists(self, name: str) -> bool: ...
    def create_and_switch(self, name: str) -> None: ...   # git checkout -b
    def switch(self, name: str) -> None: ...              # git checkout
    def integration_is_ancestor(self, integration: str, feature: str) -> bool: ...
                                                          # git merge-base --is-ancestor
    def commit_all(self, message: str) -> str | None: ...  # stage -A + commit; None if clean
    def merge_no_ff(self, feature: str, message: str) -> None: ...  # git merge --no-ff -m
```

- **`GitCli(root)`** — the real implementation, wrapping the subprocess helpers (folds in
  today's `_git_current_branch` and `_git_commit`).
- **`FakeGitTopology(current, branches=…, integration_tip=…)`** in `conftest` — an in-memory
  model: a set of branch names, the checked-out branch, and a minimal ancestry relation
  (per-branch base tip) sufficient to answer `integration_is_ancestor`. Records the sequence
  of operations (`created`, `switched`, `merged`) for assertions.

### `Step.slug` (`devsteward/core/model.py`)

Add an optional `slug: str = ""` field. The executor is content-agnostic, so it does **not**
derive the slug from the title; `ReqStepSource` (which knows the clean REQ title) populates it
via a `_slugify(title)` helper: take the headline segment before the first ` — ` (em dash),
lowercase, map non-alphanumerics to single hyphens, cap at ~5 words. REQ-020 →
`branch-lifecycle-automation`; REQ-010 → `converter`. Generic-profile steps have no
`req`/`phase`/`slug`; they never trigger branching (it is keyed on `phase ∈ {build, land}`).

### Config (`devsteward/config.py`) — extend the existing `git` section (REQ-011)

Add `feature_branch` template, default `"req-{num}-{slug}"`, exposed as
`Config.feature_branch_template`. `num` = the REQ id with the `REQ-` prefix stripped (keeps a
lettered suffix, e.g. `022a`). The executor formats the name from `step.req`/`step.slug`; no
new config file (decision 8). Threaded through `build_executor` into the `Executor`, and
documented in the stamped `config.yaml.tmpl` + handbook `03-workflow.md`.

## Executor flow

`step_branch_guard` → **`prepare_branch(step) -> str | None`** (returns a *surface* message to
abort, else `None` to proceed):

1. `phase ∉ implementation_phases` → `None` (design/generic run where they are).
2. `current_branch != integration_branch` → `None` (already on a feature branch — resume;
   production is caught earlier by `branch_guard()`).
3. On the integration branch, compute `name = feature_branch_template.format(num, slug, req)`:
   - **exists** → if `integration_is_ancestor(integration, name)` is false the branch has
     **diverged** (integration advanced since it was cut): return a surface message, append
     `branch_diverged`, do **not** switch. Else `switch(name)`, append `branch_reused`.
   - **absent** → `create_and_switch(name)`, append `branch_created`.

Drivers (`advance_once`, `run`) gain a shared **`_drive_step(step)`** helper to avoid
duplicating prepare/run/finalize:

```python
def _drive_step(self, step, *, unattended, on_event):
    surfaced = self.prepare_branch(step)
    if surfaced is not None:
        self.ledger.append_event("branch_surfaced", step=step.id, detail=surfaced)
        return StepResult(step, RunOutcome.REFUSED, surfaced)
    res = self.run_step(step, unattended=unattended, on_event=on_event)
    if res.outcome is RunOutcome.DONE and step.phase == "land":
        self._merge_after_land(step)
    return res
```

`branch_guard()` (production) stays the first check in both drivers, unchanged.

### `_merge_after_land(step)` — decisions 4 & 6

`run_step` for a land step, in order: verify green → `_commit` (land commit on the feature
branch) → `set_status(DONE)` + `save()` → `append_event("checkpoint", commit=sha)`. The last
two writes leave `state.yaml`/`events.jsonl` **dirty on the feature branch** — the "trailing
ledger write." So `_merge_after_land`:

1. `git.commit_all(f"{step.req}: ledger checkpoint\n\n<trailer>")` — a **follow-up** commit,
   never `--amend` (amending would change the land-commit hash that the just-recorded
   `checkpoint` event points at — the exact sharp edge the REQ context calls out).
2. `git.switch(integration_branch)`.
3. `git.merge_no_ff(feature, f"Merge {feature} into {integration} — {step.req} {title}\n\n<trailer>")`.

After this the integration branch's tree and ledger are clean at rest (AC4). The merge commit
records an auditable REQ boundary and succeeds even if `dev` advanced — where `--ff-only`
would hard-error (decision 4). `--no-ff` ≠ a PR: CLAUDE.md's "plain local merge" means no PR.

`_merge_after_land` runs **only** on `RunOutcome.DONE`; on `VERIFY_FAILED` or `PARKED` the
driver returns before it, so the feature branch stays checked out and unmerged for inspection
(AC5, decision 5).

## What changes vs REQ-019 (and why its tests move)

REQ-019's acceptance asserted **refusal** of `build`/`land` on the integration branch. This
REQ deliberately replaces that refusal with management (decision 2), so those specific
REQ-019 tests are updated in this REQ's commit (same-commit discipline) to assert
create+switch instead:
- `test_refuses_implementation_on_integration_branch` → repurposed/covered by REQ-020 AC1
  (create+switch) — the REQ-019 *refusal* assertion is retired with the behavior it guarded.
- `test_design_allowed_on_integration_branch` — the design half stays (AC2); its production
  half stays (AC7).
- `test_implementation_proceeds_on_feature_branch` — stays valid (on a feature branch,
  `prepare_branch` is a no-op and the step runs).
- The `_executor` test helper switches from `branch_resolver=` to a `FakeGitTopology`.

The REQ-011 production-guard tests (`test_refuses_on_production_branch`,
`test_proceeds_off_production_branch`) are untouched (AC7).

## Files touched (Build)

- `devsteward/core/seams.py` — add `GitTopology` protocol.
- `devsteward/core/git.py` *(new)* — `GitCli`, folding in `_git_current_branch`/`_git_commit`.
- `devsteward/core/executor.py` — `prepare_branch`, `_drive_step`, `_merge_after_land`;
  drivers call `_drive_step`; constructor takes `git: GitTopology` (+ `branch_resolver` shim)
  and `feature_branch_template`.
- `devsteward/core/model.py` — `Step.slug`.
- `devsteward/profiles/req/source.py` — populate `slug` via `_slugify`.
- `devsteward/config.py` — `feature_branch` in `git`, `feature_branch_template` property.
- `devsteward/build.py` — thread template + a `GitCli` into `build_executor`.
- `devsteward/templates/.devsteward/config.yaml.tmpl`, `handbook/03-workflow.md`,
  `templates/CLAUDE.md.tmpl` — document management replacing the REQ-019 refusal.

## Tests to write (Land) — `tests/test_branch_lifecycle.py`

AC1 `test_creates_and_switches_branch_on_first_build` · AC2
`test_design_stays_on_integration_no_branch` · AC3 `test_auto_merges_no_ff_after_green_land`
· AC4 `test_ledger_clean_on_integration_at_rest` · AC5
`test_no_merge_on_failed_or_parked_land` · AC6 `test_reuses_existing_feature_branch` (reuse
**and** the diverged→surface case) · AC7 `test_production_guard_unchanged`. All driven through
`FakeGitTopology` (no real git), consistent with `test_branch_guard`.

## Out of scope (carried from the REQ)

PR automation (`dev → main` stays a human PR, REQ-019); concurrent two-REQ implementation
against one cursor; any remote/push; auto-deletion of the merged branch (later, behind
config). Does **not** depend on [[REQ-018]] `steward checkpoint`; the merge does the minimal
in-REQ ledger reconcile itself and may later delegate to `steward checkpoint` if it lands.
