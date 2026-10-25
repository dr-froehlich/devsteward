# Plan 0019 — REQ-034: human validation as a guided, asynchronous activity

Covers **REQ-034**. Reworks the `manual`-AC half of the System-Test phase (REQ-030) so a
human validation is a *guided interactive session* (the human gets the same orientation tax
the engine oracle already gets), parks as an *async QA-ticket* that never freezes the
project, and *cleanly re-enters* after the integration branch has advanced. Amends REQ-030
D4 (prepare+guide+record, not present+record); the engine still owns the verdict and the
artifact gate.

## What exists today (the baseline this layers on)

- `devsteward/profiles/req/validate.py` — `ReqValidateRoutine`. `__call__` (batch) and
  `revalidate` (done REQ) funnel into `_validate`, which: runs a **headless** System Tester
  (`_run_session`, `claude -p`) for `artifact` ACs, runs the engine artifact gate
  (`_artifact_gate`), handles `manual` ACs (`_park_manual` when unattended/no provider, else
  the synchronous `signoff` provider), appends the evidence event, writes `verified_by`, and
  lands in-flight via `ex.mechanical_land`.
- `Signoff(approved, reviewer, scope)` — two outcomes only (approve / decline).
- `executor.py` — `prepare_branch` *refuses* a diverged feature branch; `mechanical_land`
  / `commit_deferred` / `_merge_after_land`; `_drive_step` commits the ledger close on PARKED
  (batch only).
- `cli.py validate` — in-flight attended path calls `routine(..., unattended=False,
  signoff=_interactive_signoff)` (a click `y/N`); no guided session, no async park.
- `core/claude.py` — only `run_claude` (headless `claude -p`, stream-json, detached
  `start_new_session`).

## The model (Decisions 1–7)

Two launch shapes around a **two-phase** bookkeeping (D6):

- **start half** — lab check, set RUNNING + `step_started`, **ready/reconcile** the feature
  branch (D5), make the evidence dir.
- **end/record half** — run the engine artifact gate on captured artifacts, take the human
  verdict, append the evidence event + `verified_by`, then route the **three outcomes** (D7):
  green → mechanical land; declined → red park pointing at `steward rework`; pending → async
  park. Every park leaves a clean tree, HEAD on the integration branch, the feature branch
  intact and **unmerged** (D3/D4).

- **Shape A (standard, `steward validate` from a plain shell):** start → bring up an
  **interactive** Claude attached to the terminal (the editor pattern — TTY inherited, no
  `-p`, no detach, foreground `wait`) → record. The bring-up **refuses when `CLAUDECODE` is
  set** (already inside Claude) — Claude is never spawned from within Claude (D6).
- **Shape B (mid-session):** a running session's skill calls `start`, runs the guided
  validation *in that session*, then calls `record` — no new Claude.

The verdict is the human's, **engine-recorded**; the engine-run artifact gate + the
engine-captured verdict are what keep the session from self-certifying (D2), regardless of
launch shape.

## Surfaces & changes

### `core/claude.py`
- `run_claude_interactive(command, *, argv_prefix, cwd, env, model, effort) -> int` — the
  editor pattern: `subprocess.run([... command])` inheriting the parent's stdio (TTY), no
  `-p`/`--output-format`, no `start_new_session`, foreground wait; returns the exit code.
- `in_claude_session() -> bool` — `bool(os.environ.get("CLAUDECODE"))`, the nesting guard.

### `core/git.py` + `core/seams.py` + `tests/conftest.py` (FakeGitTopology)
- `reconcile_from_integration(integration, feature, message)` — switch to `feature`, merge
  `integration` `--no-ff` into it (brings a behind-but-merged branch current again; makes
  `integration` an ancestor of `feature` so the deferred land can proceed). Fake: drop
  `feature` from `_diverged`, record a commit/merge.

### `core/executor.py`
- `interactive_runner` ctor param/attr, default `claude_mod.run_claude_interactive`.
- `ready_validate_branch(step) -> str | None` (D5) — on the integration branch with the
  feature branch present, switch to it and, when it has fallen behind
  (`not integration_is_ancestor`), **reconcile** it (record `branch_reconciled`) instead of
  refusing. (In-flight: already on the feature branch → no-op.)
- `bring_up_guided_session(step, evidence_rel, *, on_event) -> int | str` (D6) — refuse
  (return a surface string) when `in_claude_session()`; else spawn the interactive guided
  System Tester via `interactive_runner` and wait.
- `return_to_integration()` — switch HEAD back to the integration branch (idempotent).

### `profiles/req/validate.py`
- `Signoff.deferred: bool = False` + `outcome` property (`approved`/`declined`/`pending`).
- `StartContext` dataclass (req, step, evidence_dir, evidence_rel, in_flight).
- `start(ex, step) -> StartContext | StepResult` — the start half (lab check, RUNNING,
  `ready_validate_branch`, evidence dir).
- `record(ex, ctx, *, signoff, on_event, driver) -> StepResult` — the end half (artifact
  gate, three-outcome verdict routing, evidence event, `verified_by`, land/park). Its parks
  self-commit the ledger close and return HEAD to the integration branch (it is *not*
  wrapped by `_drive_step`).
- `guided_validate(ex, step, *, signoff, on_event, driver) -> StepResult` — shape A:
  `start` → `bring_up_guided_session` → `record`.
- New parks: `_park_pending` (async QA, D3) and a `steward rework` pointer in the declined
  red park (D7). The batch `__call__`/`_validate` path is **unchanged** (still
  `_park_manual`/`_park_red`, committed by `_drive_step`).

### `cli.py`
- `validate`: route the in-flight attended path through `routine.guided_validate` (start →
  bring-up → record). Surface the `CLAUDECODE` refusal. `_interactive_signoff` offers three
  verdicts: approve / decline / **defer (pending)**.

### Skill + handbook
- `system-test/SKILL.md` (repo + template, kept identical — hardlinked): an **attended /
  guided** mode and the two-phase `start`/`record` note (mid-session shape B); never spawn
  Claude from within Claude.
- handbook `02`/`03`: human validation as guided async QA.

## Acceptance tests — `tests/test_guided_validation.py`

A `FakeInteractiveRunner` (records the foreground bring-up, optionally drops a captured
artifact, returns 0) injected as `interactive_runner`; the existing `FakeGitTopology`
extended with reconcile.

- **AC1** `test_shell_validate_wraps_interactive_session_two_phase` — `guided_validate`
  preps, brings the interactive session up (foreground; the headless runner is **not** used
  for the manual session), then gates + records; a declining verdict shows the session
  cannot self-certify.
- **AC2** `test_in_session_start_record_and_nesting_refusal` — `start` then `record` land
  with **no** interactive spawn (shape B); `bring_up_guided_session` refuses when
  `CLAUDECODE` is set, pointing at a plain terminal / the in-session skill.
- **AC3** `test_pending_validation_parks_async_nonblocking` — a deferred verdict parks
  clean (HEAD on `dev`, feature branch intact + unmerged, step BLOCKED); a subsequent
  `run` advances an independent REQ.
- **AC4** `test_parked_validation_resumes_and_reconciles_then_lands` — after `dev` advances
  (branch behind), `start` reconciles the feature branch and a green verdict fires the
  deferred land.
- **AC5** `test_human_validation_terminal_outcomes_clean_tree` — green → land; declined →
  red park whose message names `steward rework`; pending → async park; each leaves a clean
  tree and no merge on any park.
- **AC6** (manual) — live e2e on FlowSteward's parked REQ-024 (out of band).

Plus: the seven REQ-030 tests in `test_system_test_phase.py` stay green (the batch
`__call__`/`_validate`/`revalidate` paths are untouched).
