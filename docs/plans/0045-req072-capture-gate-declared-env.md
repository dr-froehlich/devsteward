# Plan 0045 — REQ-072: capture gate runs in the operator's declared environment

Covers **REQ-072** (depends on REQ-063, REQ-068).

## Problem

The capture gate (`Executor._capture_gap` → `_green_gap_at`) re-runs a develop step's named
acceptance tests against a `git archive` extract of the staged tree. The extract holds only
tracked content, so the gitignored `.env` the consumer's test bootstrap reads from CWD is
dropped — the gate re-verifies in a *different environment* than the develop gate used. When
the missing environment makes a test **fail** (not skip — e.g. FlowSteward's Postgres-only
lookups on the SQLite fallback), REQ-063's skip exemption doesn't apply and certification is
withheld with a misleading "track the uncaptured file" diagnosis.

## Approach

Carry the operator's **declared env-file** into the extract (honor-when-present, never
require), and make the withheld-certification diagnosis honest about the two possible causes
(source/test **or** environment). Engine + docs only; fused develop; all-`regression` ACs
proven with synthetic env-gated fixtures (no real DB).

## Changes

### `devsteward/config.py`
- New property `Config.verify_env_file` → `(self.verify or {}).get("env_file", ".env")`.
  Default `.env`; a project overrides via `verify.env_file`; explicit `null` disables the
  carry. Matches the existing `verify:` block (`full_suite`, `python`).

### `devsteward/core/executor.py`
- `Executor.__init__` gains `verify_env_file: str | None = ".env"`.
- New `_carry_env_file(dest)` — if `verify_env_file` names a file that exists under the repo
  root, copy it (`shutil.copy2`) into the extract dir at the same relative path; absent /
  disabled → no-op; `OSError` → fail-open like the rest of the self-check. Called from
  `_green_gap_at` right after `_extract_commit` succeeds, so every named-test re-run sees it.
  `os.environ` inheritance by the pytest subprocess is unchanged (already the default).
- `_capture_gap_message` rewritten (Decision 4): still names the preserved work-commit SHA
  and `steward repeat`, but frames the cause as *a source/test file the commit can't hold
  **or** a runtime environment the capture run lacked* — pointing at the env-file carry
  (`verify.env_file`), never "fix .gitignore", never values from the env-file, and keeps the
  explicit "never a secret". (REQ-063's AC4 substrings `source/test file` / `never a secret`
  are preserved.)

### `devsteward/build.py`
- `build_executor` passes `verify_env_file=cfg.verify_env_file` through.

### Docs
- `STEWARD.md` + `devsteward/templates/STEWARD.md` (kept identical): note the
  "same declared environment" guarantee — the land's reproduce-your-own-green self-check
  carries the declared env-file (`verify.env_file`, default `.env`) into its ephemeral
  extract when present and inherits `os.environ`; honor-when-present; the honest recovery
  path on a withheld certification (source/test *or* environment — never commit a secret).
- `devsteward/handbook/_02-engine.qmd`: same note in the land-gate section.
- `devsteward/templates/.devsteward/config.yaml.tmpl`: document `verify.env_file`.

## Secrets

The env-file is copied only into the `TemporaryDirectory` extract (0700, deleted after the
run). Its contents never enter the gap message, the event log, or any persisted artifact —
the diagnosis names the *file* and the *cause category* only.

## Tests (`tests/test_commit_integrity.py`, extending the REQ-063 suite)

Same real-git throwaway-repo teeth; new env-gated fixture: a named test that reads
`DB_ENGINE` from a `./.env` file and **fails** (not skips) on the hermetic fallback.

- AC1 `test_declared_env_file_is_carried_into_extract` — gitignored `.env` present, test
  fails without it → capture reproduces green, land certifies `DONE`, no shell exports.
- AC2 `test_no_env_file_keeps_hermetic_capture_path` — no env-file: a self-sufficient green
  certifies; a genuine source gap is still refused (REQ-063 intact).
- AC3 `test_configured_env_file_name_is_honored` — `verify.env_file: steward.env` carries
  that file; default is `.env` when unset; declared-but-absent is a no-op; `build_executor`
  wires `cfg.verify_env_file` through.
- AC4 `test_capture_gap_message_is_environment_honest` — withheld message names the SHA,
  offers source/test **or** environment, drops the "track it / fix .gitignore" single-cause
  text, never instructs committing a secret.
- AC5 `test_env_file_contents_never_leak` — a distinctive secret value in the carried `.env`
  appears nowhere in the surfaced message, `events.jsonl`, `state.yaml`, or git history; the
  extract dir is gone after the run (tempdir pinned via monkeypatch and asserted empty).

## Out of scope

FlowSteward's real-Postgres end-to-end (consumer-owned), an env-key allowlist (rejected at
intake), any intake/taxonomy change, the validate-phase exemption (unchanged).
