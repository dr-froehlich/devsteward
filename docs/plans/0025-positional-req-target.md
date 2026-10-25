# Plan 0025 — Positional REQ target for advance/run (REQ-042)

## Goal

Let a human name the REQ they mean: `steward advance REQ-027` / `steward run REQ-027`,
mapping onto the existing `--only` resolution. Pure ergonomics on the proven
`eligible_steps(only=…)` machinery — no new resolution path.

## Approach

All four ACs are CLI-surface only (`devsteward/cli.py`); the executor already takes
`only=` everywhere. Two small shared helpers plus a positional argument on each command.

### Helpers (cli.py)

- `_resolve_target(req_id, only)` → the effective target. Raises `ClickException`
  ("not both") when both the positional and `--only` are supplied (Decision 2 / AC3).
  Returns `req_id or only`. Called *before* `_load_or_die` so the conflict fails fast.
- `_print_steer_hint(ex, command)` → when no target was named and more than one REQ is
  eligible, echo the eligible REQ ids, the lowest-id pick, and the
  `steward <command> REQ-NNN` steer syntax (Decision 4 / AC4). `command` is "advance"
  or "run". No-op when ≤1 REQ eligible (current silent behaviour preserved).

### `advance` / `run` commands

- Add `@click.argument("req_id", required=False, default=None)`.
- `target = _resolve_target(req_id, only)`.
- When `target is None`, call `_print_steer_hint(ex, "advance"|"run")` before driving.
- Pass `only=target` into `advance_once` / `run`.
- The existing `res is None` / empty-results branch already raises
  `only_ineligibility_reason(target)` when a target was named (AC2 — reuses the verbatim
  message; never auto-activates).

### Interactions

- Decision 1: positional reuses `eligible_steps(only=…)` — no parallel logic.
- Decision 3: ineligible named REQ → existing reason message, exit non-zero, no activation
  (the positional path never calls `activate`).

## Files touched

- `devsteward/cli.py` — `advance`, `run`, two helpers.
- `tests/test_cli_smoke.py` — the four acceptance tests below.

## Tests (the `acceptance` block)

- `test_positional_target_scopes_like_only` (AC1) — `advance REQ-X` / `run REQ-X` accepted
  and thread `only="REQ-X"`, identical to `--only REQ-X`.
- `test_positional_ineligible_errors` (AC2) — named REQ with no eligible step exits
  non-zero with the `only_ineligibility_reason` text; no activation.
- `test_positional_and_only_conflict` (AC3) — positional + `--only` together exits
  non-zero.
- `test_multi_eligible_prints_steer_hint` (AC4) — >1 eligible REQ still picks lowest id;
  output lists the eligible ids and the `steward advance REQ-NNN` steer syntax.

All via `CliRunner` with `_FakeExecutor` stand-ins (no real ledger), matching the existing
`test_cli_smoke.py` style.
