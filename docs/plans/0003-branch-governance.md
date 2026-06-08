# 0003 — Branch governance (REQ-011)

**Date:** 2026-06-08
**Status:** Design (REQ-011:design). Build + Land pending.
**REQ:** [REQ-011](../requirements/REQ-011.md) — engine enforces branch-before-main;
config-driven branch names. `depends_on: REQ-003 (executor core), REQ-007 (scaffolding)`.

Closes the doc/reality gap: today "branch before main" is asserted in four consumer-facing
docs and `handbook/00-method.md` even claims *"the linter and the engine enforce them"* —
but `Executor._commit` runs `git add -A && git commit` on whatever branch is checked out,
so `steward run` on `main` commits straight to production. This REQ makes the engine
actually refuse, and makes the branch names configuration.

The REQ's Decisions table settles every fork, so this design is purely *how*, not *whether*:
guard-only (refuse, don't branch-manage), a **precheck refusal** that is a distinct run
outcome (not a park, not a step FAILED), protect the **production branch only**, **no
opt-out**, and branch names live in config with `main`/`dev` defaults.

## Approach in one paragraph

Add a `git` section to `Config` (`production_branch` default `main`, `integration_branch`
default `dev`). Thread `production_branch` through `build_executor` into the `Executor`. The
executor gains a **branch guard** consulted once up front in each driver (`advance_once`,
`run`) *before* any `claude` invocation: if the current git branch equals the production
branch it returns a new `RunOutcome.REFUSED` result — no claude, no commit, the step stays
`PENDING` — with a message naming the branch and the fix. Off the production branch
everything proceeds unchanged. Then update the four consumer-facing docs + the stamped
`config.yaml` so migrated/new projects inherit the model and the "engine enforces" claim
becomes true for branching.

## Why a precheck, not a park or a mid-run fail (REQ decision 2)

The engine never switches branches, so the branch is a **whole-run precondition**, not a
per-step content fork. Park-and-surface is for content forks a human resolves with
`steward decision answer` — but answering a decision can't switch a branch, so parking would
be a dead end. A step `FAILED` implies the work was attempted and broke; here nothing is
attempted. Hence a third, distinct outcome checked once before the loop.

## Data shapes & interfaces

### `devsteward/config.py`
- Add field `git: dict = field(default_factory=lambda: {"production_branch": "main",
  "integration_branch": "dev"})` and convenience properties:
  ```python
  @property
  def production_branch(self) -> str:
      return (self.git or {}).get("production_branch", "main")
  @property
  def integration_branch(self) -> str:
      return (self.git or {}).get("integration_branch", "dev")
  ```
- `load_config`: read `git=data.get("git", {})`. Absent `git`, or absent keys, yield the
  defaults via the properties' `.get(..., default)`.

### `devsteward/core/executor.py`
- New outcome: `class RunOutcome(...): REFUSED = "refused"`.
- Module helper (the default branch resolver — a real-git seam, mirroring how `_git_commit`
  is the real-git side that tests bypass with an injected `committer`):
  ```python
  def _git_current_branch(root: Path) -> str:
      res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                           cwd=root, capture_output=True, text=True)
      return res.stdout.strip()   # detached HEAD -> "HEAD" (never the production branch)
  ```
- `Executor.__init__` gains `production_branch: str = "main"` and
  `branch_resolver: Callable[[Path], str] | None = None`; stores `self.production_branch`
  and `self._branch_resolver = branch_resolver or _git_current_branch`.
- `current_branch(self) -> str: return self._branch_resolver(self.root)`.
- `branch_guard(self) -> str | None`: returns a refusal message if
  `self.current_branch() == self.production_branch`, else `None`. Message names the branch
  and the fix, e.g.
  *"refusing to autocommit on the production branch 'main' — DevSteward never commits to
  production; switch to the integration branch (dev) or a feature branch and re-run."*
- `advance_once`: first line consults the guard. On refusal: append a `branch_refused`
  event, then `return StepResult(self.next_eligible(), RunOutcome.REFUSED, msg)` — no
  status mutation, so the eligible step stays `PENDING`. Else proceed as today.
- `run`: same guard up front; on refusal return `[StepResult(self.next_eligible(),
  RunOutcome.REFUSED, msg)]` without entering the loop.
- `StepResult.step` becomes `Step | None` (refusal can occur with nothing eligible).

`run_step` itself is **unchanged** — keeping the guard in the drivers honours "check once up
front" and avoids re-checking per step inside a `run` loop (the branch can't change mid-run).

### `devsteward/build.py`
- `build_executor(...)` passes `production_branch=cfg.production_branch` to `Executor(...)`.

### `devsteward/cli.py`
- `_echo_result`: add `RunOutcome.REFUSED: "red"` to the colour map; tolerate `res.step is
  None` (print `—`).
- `_print_report` / `advance`: when `res.outcome is RunOutcome.REFUSED`, print the guard
  message prominently (red) instead of the normal Did/commit lines; tolerate `step is None`.
- `run`: a `[REFUSED]` result list prints the guard message in red.

## Files to touch (Build)

**Engine:** `config.py`, `core/executor.py`, `build.py`, `cli.py`.
**Scaffolding / docs (AC4):**
- `devsteward/templates/.devsteward/config.yaml.tmpl` — add a `git:` section with
  `production_branch: main` / `integration_branch: dev` + a one-line comment.
- `devsteward/templates/CLAUDE.md.tmpl` — upgrade the "Branch before main" bullet to the
  full two-line model (production `main` vs integration `dev`, feature-branch-per-REQ → PR
  into integration), now engine-enforced & config-driven.
- `devsteward/handbook/00-method.md` — same upgrade to the "Branch before main" bullet; the
  existing "the linter and the engine enforce them" line is now *true* for branching.
- `devsteward/handbook/03-workflow.md` — add a short **Branching model** subsection (it
  currently says nothing about branches).
- `devsteward/templates/.claude/skills/bootstrap/SKILL.md` — its "first commit on a branch
  (not `main`)" step gains the `dev` integration-branch wording (4th consumer-facing doc).

**Tests:** new `tests/test_branch_guard.py`.

## The four acceptance tests (`tests/test_branch_guard.py`)

- **AC1 `test_config_branch_names`** — defaults: a project with no `git` section yields
  `production_branch == "main"`, `integration_branch == "dev"`; a written `config.yaml`
  with `git: {production_branch: master, integration_branch: release}` is read back.
- **AC2 `test_refuses_on_production_branch`** — `Executor(..., production_branch="main",
  branch_resolver=lambda root: "main")` with a `FakeRunner`, a `RecordingCommitter`, and one
  eligible step. `advance_once()` ⇒ outcome `REFUSED`; `runner.calls == []` (no claude);
  `committer.committed == []`; step status still `PENDING`; message mentions `main`.
- **AC3 `test_proceeds_off_production_branch`** — same wiring but
  `branch_resolver=lambda root: "dev"`. `advance_once()` ⇒ `DONE`; runner called once;
  committed; status `DONE`.
- **AC4 `test_scaffolding_documents_model`** — read the packaged files and assert the
  stamped `config.yaml.tmpl` carries `git:`/`production_branch`/`integration_branch`, and
  that `CLAUDE.md.tmpl`, `handbook/00-method.md`, and `handbook/03-workflow.md` state the
  `main`/`dev` model (e.g. mention both branch names + "integration").

The branch seam keeps AC2/AC3 fast and git-free, consistent with conftest's stated goal of
driving the full loop "without a real `claude`… and without committing to git." (Detached
HEAD = "HEAD" ≠ production is covered by the resolver's contract; an optional real-git smoke
of `_git_current_branch` could be added but is not an AC.)

## Non-goals (REQ Notes — unchanged)

No auto-creating feature branches, no opening PRs, no guarding the integration branch, no
remote/push, no config opt-out for the guard. Detached HEAD is allowed. Branch-management
(REQ decision 1) is future work behind its own REQ.

## Open questions

None — the REQ's Decisions table resolves every fork. Nothing to park.
