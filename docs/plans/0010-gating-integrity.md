# Plan 0010 — Gating integrity (REQ-028)

**Design checkpoint for REQ-028.** The engine must refuse to call a `land` step `DONE`
unless its named behaviour observably *ran and passed*, and `steward lint` must refuse a
`done` the ledger contradicts. Four runtime holes (AC1–AC4) live in the verifier; one
(AC5) lives in lint. Runtime/lint enforcement only — no System-Test phase, no taxonomy
(REQ-027 and its follow-ons own those).

This is the implementation-strengthening complement to REQ-015 (land has teeth) and
REQ-006/REQ-027; their specs stand, `supersedes` stays null.

## The equation we are sharpening

REQ-015 made `exit-0 ⇒ green` at land. The four runtime holes are all cases where
exit-0 lies:

| AC | Hole | Today | After |
|----|------|-------|-------|
| AC1 | a `pytest.skip` exits 0 | skip lands as a pass | a **skipped** named test fails the gate |
| AC2 | a typo'd / unowned test id collects nothing | empty selection can read as green | **zero collected** fails the gate |
| AC3 | the per-AC gate never runs the rest of the suite | a known-broken behaviour ships green | the **full suite** runs at land; any red fails |
| AC4 | the verifier shells into a context without the venv | `127 pytest: not found` reads as "not yet verified" | the **project env** is resolved; an unusable env is a *hard surfaced* error |
| AC5 | a hand-edited `done` over a `failed`/absent land | lint never inspects the ledger | lint hard-errors when frontmatter `done` contradicts the ledger |

## Surfaces (confirmed by reading the code)

- `devsteward/core/verify.py` — `CommandVerifier` (exit-code per command) +
  `_resolve_interpreter`/`_pick_interpreter`/`_venv_interpreters`/`_has_pytest`
  (the existing env rebinding from REQ-020/025/026). AC1–AC4 land here.
- `devsteward/profiles/req/verify.py` — `ReqVerifier`. Today it adds exactly one rule
  (a `land` step with no tests is refused) and delegates the rest to `CommandVerifier`.
  This is where the *sharpened* land semantics belong (the AC1 test imports `ReqVerifier`).
- `devsteward/build.py` — `build_verifier(cfg)` constructs `ReqVerifier(cwd=...)`; will
  also pass the full-suite command + configured interpreter from config.
- `devsteward/config.py` — `Config`; gains an optional `verify:` block (full-suite
  command, configured interpreter).
- `devsteward/lint.py` — `lint(cfg)`; gains the marker↔ledger rule (AC5), reading the
  `Ledger`.
- `devsteward/core/ledger.py` — read-only: `status_of`, `all_statuses` (AC5).
- `devsteward/handbook/02-engine.md` — state the sharpened guarantee.
- `devsteward/templates/.devsteward/config.yaml.tmpl` — document the new `verify:` block.

## Core mechanism — read per-test outcomes, don't trust exit-0

Exit codes cannot distinguish a pass from a skip (both exit 0). The robust, **built-in**
machine-readable signal is pytest's JUnit XML (`--junitxml=`), no plugin/dependency added.
Add to `verify.py`:

```python
def _pytest_outcome(cmd, cwd, interpreter, timeout) -> Outcome:
    """Run a pytest command with an injected --junitxml, parse per-test counts.
    Returns (collected, passed, skipped, failed, errors, returncode, raw_tail)."""
```

- Inject `--junitxml=<tmpfile>` (+ `-o junit_family=xunit2`) into the resolved command,
  run under `interpreter`, then parse the `<testsuite tests= failures= errors= skipped=>`
  attributes (and per-`<testcase>` for the detail line).
- Only injected for **pytest** commands (the house convention: acceptance `test:` strings
  are `python -m pytest …`). A non-pytest command falls back to exit-code semantics with a
  note that per-test outcomes are unavailable.
- If the XML is missing/empty *and* the run exited non-zero on a usage/collection error
  (pytest exit 4/5), treat as **zero collected** (AC2).

### AC1 — a skip is not green
`ReqVerifier`, land phase, per named test: require `collected > 0 and skipped == 0 and
failed == 0 and errors == 0`. Decision 1 is broad — *any* skipped named test fails (a skip
and a pass stop being the same signal), so an all-skipped run is the strong case but a
mixed pass+skip also fails. A named acceptance test is load-bearing by definition; if it
may legitimately skip, it should not be in the acceptance block (that is REQ-027's intake
job, out of scope here).

### AC2 — zero collected is not green
Same path: `collected == 0` → FAILED, with a message naming the test id ("collected 0
tests — non-existent, renamed, or unowned id"). Covers pytest exit 4 (bad node id) and
exit 5 (empty selection) uniformly, *and* the rarer exit-0-empty-selection case the
post-mortem flagged.

### AC3 — the full suite runs at land
After the named tests pass, `ReqVerifier` (land only) runs the **project's full suite**
once and requires it clean. The suite command comes from config (`verify.full_suite`,
default `python -m pytest` at the repo root). Mechanism: plain **exit-code** check — a
failure/error → non-zero → FAILED; **skips in the full suite stay legal** (a clean
checkout may skip a network test). Run through the same resolved interpreter as the named
tests (AC4). design/build never run the suite.

*No recursion risk:* the AC3 test (`test_land_full_suite_red_fails_step`) builds an
isolated temp project (one passing named test + one failing other test) and asserts the
land fails; it does not invoke the real dogfood suite.

### AC4 — run in the project's configured environment, surface an unusable one
Extend the existing resolution:
- Candidate order: `verify.python` from config (if set) → `.venv`/`venv` discovery →
  `sys.executable`, first that can `import pytest` (existing `_pick_interpreter`).
- New: when **no** candidate can import pytest, the verifier returns a **hard surfaced
  error** ("no usable test environment: pytest not importable under <candidates>") instead
  of silently returning `sys.executable` and letting the command die with `127`/`No module
  named pytest` — so an env failure is distinguishable from a test failure and a `done`
  can never become reachable *because* the suite could not be run.
- If `verify.python` is configured but missing/unusable, that is the hard error too
  (configured-but-unusable ≠ silent skip-ahead).

`test_verifier_uses_project_env_no_127`: (a) with a venv that has pytest, the command runs
under it (no exit 127); (b) with a configured-but-unusable env, `verify` returns
`(False, <env-error message>)` distinct from a test-failure message.

### AC5 — lint reconciles the marker against the ledger
Add a rule to `lint(cfg)`: load `Ledger(cfg.root)`. A REQ is **ledger-tracked** if any of
its steps appears in `state.yaml` (`all_statuses()` keys). For a ledger-tracked REQ whose
frontmatter `status: done`, require its `REQ-NNN:land` step status to be `DONE`; otherwise
hard-error naming the contradiction (e.g. "frontmatter done but ledger land is failed").

**Why ledger-tracked, not every done REQ:** this repo has 21 `done` REQs but only 6 land
steps in the ledger — 15 are pre-ledger/imported `done`s (REQ-010-style governance
imports) the engine never drove. Flagging *those* would break the green dogfood lint and
is not the hole. Decision 5's "failed, open, or absent" is read as *absent-within-a-tracked
REQ* (the FlowSteward shape: a `failed` terminal land event under a `done` marker), exactly
mirroring how lint rule 5 already exempts terminal/imported REQs. A REQ with **no** ledger
footprint is outside the ledger's purview and untouched here.

`test_lint_fails_on_done_contradicted_by_ledger`: a temp project with a REQ marked `done`
in frontmatter+index whose ledger land step is `failed` (or design/build present, land
absent) → lint reports the contradiction; the agreeing case (land `done`) passes clean.

## Config additions (`Config`, template)

```yaml
verify:
  full_suite: python -m pytest      # AC3; default if unset
  python: .venv/bin/python          # AC4; optional explicit interpreter
```

Both optional with the documented defaults. `build_verifier(cfg)` threads them into
`ReqVerifier(cwd, full_suite=..., python=...)`.

## Files / tests to write at Build

- `devsteward/core/verify.py` — `_pytest_outcome` + env-resolution hard-error.
- `devsteward/profiles/req/verify.py` — `ReqVerifier` land: per-test outcome gate (AC1/AC2),
  full-suite gate (AC3), env-error surfacing (AC4). Constructor gains `full_suite`/`python`.
- `devsteward/lint.py` — marker↔ledger rule (AC5).
- `devsteward/config.py` + `templates/.devsteward/config.yaml.tmpl` — `verify:` block.
- `devsteward/build.py` — thread config → `ReqVerifier`.
- `devsteward/handbook/02-engine.md` — sharpened-guarantee paragraph.
- Tests (the acceptance ids, exactly as named in REQ-028):
  - `tests/test_verify_teeth.py::test_land_skip_is_not_green` (AC1)
  - `tests/test_verify_teeth.py::test_land_zero_collected_is_not_green` (AC2)
  - `tests/test_verify_teeth.py::test_land_full_suite_red_fails_step` (AC3)
  - `tests/test_verify_venv.py::test_verifier_uses_project_env_no_127` (AC4)
  - `tests/test_lint_marker_ledger.py::test_lint_fails_on_done_contradicted_by_ledger` (AC5)

## Invariants preserved
- design/build still pass on marker-trust (REQ-015 D2) — the sharpened semantics are
  land-only.
- A clean checkout that *legitimately skips* a network test in the **full suite** stays
  green (AC3 allows suite skips); only a **named acceptance test** that skips fails (AC1).
- English-only technical text; no localized UI strings introduced.
- The engine still owns verify→flip→commit; this plan only sharpens what "verified" means.

## Forks
None — every fork (the full-suite source, the ledger-tracked scoping of AC5, JUnit-XML as
the per-test signal) resolves from the REQ's decisions + the repo as documented above.
