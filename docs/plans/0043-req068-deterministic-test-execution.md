# Plan 0043 — REQ-068: deterministic acceptance-test execution

**REQ:** REQ-068 — a `check: live` standing-regression lane, develop-gate routing by
`check:`, fail-hard on a missing declared resource, one `python -m pytest` flavor.

**Thesis (REQ-068):** the *engine* — not ambient state, not a marker string, not authoring
whim — decides how an acceptance test runs (which lane, which flavor), and a resource a
declared test requires being absent is a hard red, never a silent skip. This is the
left-shift/runtime completion of REQ-027 (`check:`), REQ-028 (skip≠green), REQ-063 (tolerate
the *unknown* skip), REQ-064 (intake screens env-bound regressions). It extends the **one**
existing `check:` axis — no second "role" attribute.

## Surfaces and changes

### 1. `check:` gains a fourth value `live` (Decision 1) — AC1
- `devsteward/lint.py`: `CHECK_VALUES = ("regression", "live", "artifact", "manual")`;
  update the two enum messages to list `live`.
- `devsteward/core/model.py`: `AcceptanceCheck.check` docstring lists the four values.
- No JSON-schema change (the enum is lint-owned; `check` is not enumerated in
  `req.schema.json`).
- `live` is **not** in `source.py`'s `_VALIDATE_CHECKS` → it stays in `develop_verify`, so
  the develop gate already runs `regression` + `live` as named tests for free.

### 2. Develop gate routes by `check:` — exclude one-time validations (Decision 2) — AC2
- The develop gate already runs `regression`+`live` as named tests (via `develop_verify`)
  and the hermetic full suite. The gap: the **full suite** re-runs every other REQ's
  `artifact` test. Fix: the full-suite run **deselects** every `artifact`/`manual` AC
  pytest node-id **project-wide**.
- `devsteward/core/verify.py`: add `_pytest_targets(cmd)` → the node-id tokens of a pytest
  command (non-flag, non-interpreter, non-`pytest` tokens). Manual ACs (`test: "manual: …"`)
  are not pytest commands → no node-id, nothing to deselect.
- `devsteward/profiles/req/verify.py`: `ReqVerifier.__init__` gains
  `exclude_nodeids: tuple[str, ...] = ()`; `_gate_full_suite` appends
  `--deselect <id>` for each when the full suite is a pytest command (gated on
  `_is_pytest_command`; a non-pytest full suite keeps exit-code semantics, untouched).
- `devsteward/build.py`: `build_verifier` loads all REQs (`load_reqs(cfg.req_dir)`) and
  computes the project-wide artifact/manual node-id set, threading it into `ReqVerifier`.

### 3. Fail-hard on a missing declared resource (Decision 3) — AC3
- Already true: `_gate_named` treats any skip in a named test as red (skip≠green, REQ-028),
  and `live` runs as a named test. The full-suite tolerates an *unknown* skip (returncode 0)
  — unchanged (REQ-063). No code change; AC3 is a proof that the two behaviours coexist.

### 4. One flavor: normalize a leading bare `pytest` (Decision 4) — AC4
- `devsteward/core/verify.py`: add `_PYTEST_PREFIX`; `_rebind_python` (renamed
  `_rebind_interpreter`) rebinds a leading bare `pytest …` → `<interp> -m pytest …` (repo
  root importable), alongside the existing leading `python`/`python3` rebind.
  `_resolve_interpreter` triggers interpreter resolution for either prefix.
- Update imports in `profiles/req/verify.py` and `core/executor.py` (`_rebind_python` →
  `_rebind_interpreter`).
- Update `tests/test_verify_interpreter.py::test_resolve_leaves_other_commands_untouched`
  (the `pytest x::y` line now *is* normalized) and add the AC4 test.

### 5. Degrade is re-classification, not a verb (Decision 5) — AC2/AC5
- Falls out of 1+2 for free: an AC flipped `live → artifact` leaves `develop_verify`
  (excluded from the standing gate, runs at `validate`/`revalidate`). Lint accepts the
  degraded form (it is just a valid enum value). Documented only.

### 6. Docs (Decision 6) — AC5
- `/intake` SKILL.md (repo == template, one inode): add `live` to §2b, the degrade note.
- handbook `_01-format.qmd` (taxonomy + example) and `_03-workflow.qmd` (V-model table):
  add the `live` row/value, the one-flavor rule, degrade.
- `devsteward/templates/STEWARD.md`: document the four lanes, develop-gate routing,
  fail-hard, the one-flavor rule, degrade.

## Tests (acceptance)
- AC1 `tests/test_lint_acceptance_taxonomy.py::test_check_live_accepted_and_enumerated`
- AC2 `tests/test_verify_teeth.py::test_develop_gate_routes_by_check_excludes_validation`
- AC3 `tests/test_verify_teeth.py::test_live_skip_is_hard_red_unknown_skip_tolerated`
- AC4 `tests/test_verify_interpreter.py::test_bare_pytest_normalized_to_python_m`
- AC5 `tests/test_handbook_taxonomy.py::test_docs_document_live_lane_and_one_flavor`
- AC6 manual (validate phase): a human drives a seeded multi-lane fixture.

## Out of scope
No `steward degrade` verb / successor field; validate-phase mechanics unchanged; the
exclusion is pytest-specific (gated on `_is_pytest_command`), tech-agnostic fallback intact.

## Land note
AC6 is `check: manual` → the develop gate **defers the land**; the close commits the work on
`dev` (`develop_committed`) and the flip fires after `steward validate REQ-068` is green.
