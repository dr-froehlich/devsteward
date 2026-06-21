# Plan 0035 — REQ-061: re-wire the account pin (`--use` → `--pin`, forward `clauder gate --pin N`)

REQ-058 delegated the budget gate to `clauder gate` and, on the way out, dropped the old
slot-pin: `build_accounts` still accepts `use` but silently never forwards it (a dead seam).
clauder REQ-006 (done) added `clauder gate --pin N`, which judges admission on account N
alone. REQ-061 reconnects the dead seam to that capability and renames the operator flag
`--use` → `--pin` so the word agrees with clauder (whose own `--use` means burn-percent).

## Approach (smallest wiring that satisfies the three regression ACs)

The pin is a *pure argv pass-through*: `pin=N` ⇒ the gate argv carries `--pin N`; `pin=None`
⇒ argv is byte-for-byte today's REQ-058 invocation. No account selection, no usage read, no
fallback — all of that is clauder's (Decisions 3, 4; `[[clauder-owns-budget-policy]]`).

### 1. `devsteward/core/accounts.py` — `ClauderAccountProvider`
- Add `pin: int | None = None` to `__init__` (keyword-only block), store `self.pin = pin`.
- In `_gate()`, build the base argv `[clauder, gate, --threshold, T, --json]` and insert
  `--pin <N>` **only when** `self.pin is not None`. When `None`, argv is unchanged from
  REQ-058 (AC2). Verdict handling (exit 0/75/69) is untouched — clauder's `wait`/
  `unsatisfiable` already reflect N alone under a pin (AC1).
- Docstring: note the optional pin forwards to clauder; DevSteward interprets nothing.

### 2. `devsteward/build.py`
- `build_accounts`: rename param `use` → `pin`; forward `pin=pin` to `ClauderAccountProvider`.
  Replace the REQ-058 "use is dropped" comment with a "REQ-061: opt-in pin forwarded to
  clauder" note.
- `build_executor`: rename keyword param `use` → `pin`; pass `pin=pin` to `build_accounts`.

### 3. `devsteward/cli.py` — `advance` and `run`
- Rename option `--use` → `--pin` (no alias; hard rename per Decision 2). Help text:
  "Pin one clauder account (drain its 7d budget); forwards `clauder gate --pin N`."
- Rename the function param `use` → `pin`; pass `pin=pin` to `build_executor`.

### 4. Handbook `devsteward/handbook/_02-engine.qmd` — "Account / quota" (Decision 6)
- Add a sentence: the per-step gate optionally forwards `--pin N` (`clauder gate --pin N`)
  to judge admission on **one** account and drain its 7-day window before reset; without it
  the gate is the combined-budget default. Moves in this same commit.
- STEWARD.md is deliberately **not** touched (Decision 7 — operator batch flags are out of
  the agent manual's scope).

## Tests (the three named acceptance tests, all `regression`)
- `tests/test_accounts.py::test_pin_forwards_to_clauder_gate` (AC1) — provider with `pin=3`
  and an injected gate runner: the recorded argv carries `--pin 3` alongside
  `--threshold T --json`; a proceed verdict (exit 0) returns `ok=True`.
- `tests/test_accounts.py::test_no_pin_omits_flag_default_unchanged` (AC2) — default
  (no pin): argv contains no `--pin` and equals the REQ-058 combined-budget invocation
  `[clauder, gate, --threshold, T, --json]`.
- `tests/test_cli_smoke.py::test_run_advance_thread_pin` (AC3) — `advance`/`run --pin 2`
  thread `pin=2` through `build_executor`; and `--use` is now an unknown option (exit != 0).
- Update the legacy `test_run_account_and_model_options` to the renamed flag (it asserted
  `--use`/`captured["use"]`).

## Out of scope
Account *selection* (auto-picking the soonest-to-reset account from `clauder usage` 7d
figures) — a possible future REQ; this honours an operator-supplied index only.
