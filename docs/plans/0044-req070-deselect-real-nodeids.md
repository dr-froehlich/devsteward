# Plan 0044 — REQ-070: full-suite deselection must use only real node-ids

**REQ:** REQ-070 — a `manual`/`artifact` AC's prose can't poison the develop gate into
deselecting the whole suite.

**Thesis:** REQ-068 Decision 2 deselects every one-time `artifact`/`manual` acceptance
node-id from the standing suite by id. The derivation harvested deselect targets from a
`manual:` AC's *prose* whenever the prose mentioned `pytest`, keeping bare words like
`tests` — and `pytest --deselect tests` deselects the whole `tests/` tree, so the gate
selected 0 tests (a false signal identical to a zero-match `-m regression`). The fix makes
the deselect set what REQ-068 always meant it to be: only genuine, collectible node-ids.
This is the runtime completion of the gating-integrity line (REQ-028/063/068).

## Root cause

- `core/verify.py::_is_pytest_command` returns `True` if **any** token equals `pytest`, so a
  `manual:` AC mentioning the tool is read as a pytest command.
- `core/verify.py::_pytest_targets` then kept **every** non-`-` token as a target — prose
  words (`tests`, `run`, `confirm`), a `-m` marker value (`not live`), etc.
- `build.py::_validation_nodeids` fed those straight into `--deselect`.

Reproduced on FlowSteward (`steward 0.2.0`) the moment its config used the canonical plain
`python -m pytest` (FlowSteward REQ-060): `exclude_nodeids` carried `tests`/`live`/`manual:`
and `--deselect tests` emptied a 539-test suite.

## Surfaces and changes

### 1. `_pytest_targets` emits only real node-ids (Decisions 1 + 2) — AC1, AC2
- `devsteward/core/verify.py::_pytest_targets`:
  - short-circuit: a `test:` string beginning `manual:` is human prose → return `[]`.
  - keep a token only if it `endswith(".py")` or contains `".py::"` (a file, a node-id,
    or a `file.py::Cls::test` selector). This drops bare words, directories, and the
    `-m <marker>` value (the flag was already dropped; now its value is too).

### 2. `_validation_nodeids` guarantee made real (Decision 3) — AC3
- `devsteward/build.py::_validation_nodeids`: no logic change needed once `_pytest_targets`
  is disciplined — the loop over `artifact`/`manual` ACs now yields only real node-ids.
  Docstring updated to state the guarantee is enforced, not incidental (REQ-070).

### 3. Regression coverage
- `tests/test_verify_deselect_nodeids.py`:
  - `test_pytest_targets_emits_only_real_nodeids` (AC2) — unit discipline incl. the `-m`
    value leak and prose.
  - `test_manual_prose_ac_contributes_no_deselect_targets` (AC1) — a prose manual AC
    yields `()`, never `tests`.
  - `test_exclude_set_is_pure_nodeids_no_suite_wipe` (AC3) — a mixed REQ-set yields only
    the real artifact node-ids; no suite-wiping token.

## Scope guard

No consumer change; no change to REQ-068's contract or the `live`/`artifact`/`manual`
taxonomy; `_is_pytest_command`'s separate role in per-test *outcome* parsing is untouched.
