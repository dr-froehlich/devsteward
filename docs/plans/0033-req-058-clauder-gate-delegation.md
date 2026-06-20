# Plan 0033 — REQ-058: engine budget gate delegates to `clauder`

**REQ:** REQ-058 — *Engine budget gate delegates to clauder — per-step `clauder gate`, no
direct cswap, race-free with a background monitor.*

## Goal

Replace the engine's hand-rolled, per-account cswap budget gate (`CswapAccountProvider`,
`core/accounts.py`) with a provider that **delegates** to the sibling tool `clauder`'s
combined-budget `gate` CLI at every step boundary. Treat `clauder` as an optional external
black-box tool (the `[[devsteward-is-a-black-box-to-agents]]` principle applied the other
way): shell its CLI, read its JSON + exit code, never touch cswap or `usage.json` directly,
and add **no second account switcher** (Decision 3 — the race can only be serialised inside
clauder).

## The clauder contract (verified against `/home/peter/projects/clauder`)

`clauder gate --threshold T [--use U] --json` emits one verdict and exits with a code:

| decision | exit | JSON fields used |
|----------|------|------------------|
| `proceed` | 0 | `decision`, `reason`, `account` |
| `switch`  | 0 | `decision`, `reason`, `account` (clauder already switched cswap) |
| `wait`    | 75 | `wait_seconds` (may be `null`), `reason` |
| `unsatisfiable` | 69 | `reason` |

JSON keys: `{decision, account, reason, wait_seconds, partial}`. `--threshold` is **percent**.

## Design

### `ClauderAccountProvider` (new, replaces `CswapAccountProvider`)

`precheck()` loops:

1. `should_stop()` at the top → `(False, "stop requested")`.
2. Shell `clauder gate --threshold <pct> --json` (subprocess, 30s timeout).
3. Map by **exit code** (the documented seam), reading the JSON for `wait_seconds`/`reason`/label:
   - `0` (`proceed`/`switch`) → `(True, …)`; clauder has already performed any switch.
   - `75` (`wait`) → announce, `_interruptible_sleep(wait_seconds or poll_seconds)`, **re-gate**.
     A stop during the wait is caught by the top-of-loop `should_stop` → `(False, …)`.
   - `69` (`unsatisfiable`) → `(False, …)` — the run stops.
   - launch failure / timeout / any other code → **degrade open** (`proceed`), never fatal
     (the cswap-absent spirit — a flaky external tool must not hard-fail a run).
4. `clauder` not on PATH → `(True, "clauder absent — proceeding without quota check")`.

No direct cswap call, no `usage.json` read: the single `clauder gate` invocation is the only
account interaction (Decision 3). The engine never starts/stops `clauder monitor` (Decision 2).

`claude_argv()` → `["claude"]` (clauder, like cswap, is a switcher; the launch is plain claude).

### Subtraction (Decision 4)

Delete `usage_snapshot`, `AccountUsage`, `_parse_countdown_to_minutes`, `_cache_stale`,
`_cswap_data_dir`, the `_CSWAP_DIRS`/`_USAGE_CACHE_TTL` constants, and the whole
`CswapAccountProvider` (per-account precheck loop, pin, rotate). Keep `_normalize_threshold`
and `SingleAccountProvider`.

### Slot-pin dropped (Decision 5, flagged-for-owner)

clauder selects the entry account from the **combined** budget, so the old `use=N` slot-pin
is gone. The CLI `--use` flag and its threading through `build_executor`/`build_accounts` are
**kept but inert** (removing owner-facing CLI surface unattended is not mine to decide — D5 is
flagged for the owner to revisit). `build_accounts` no longer forwards `use` to the provider.

### Wiring

- `build.py`: import `ClauderAccountProvider`; `build_accounts` constructs it for any non-`single`
  provider (legacy `cswap` value maps here too).
- `config.py`: default provider `cswap` → `clauder` (two spots).
- `templates/.devsteward/config.yaml.tmpl`, `.devsteward/config.yaml`: provider comment + default.
- `core/seams.py`: `claude_argv` docstring example → `["claude"]`.
- `handbook/_02-engine.qmd`: the account-provider paragraph → clauder delegation.

## Files

- `devsteward/core/accounts.py` — rewrite (delete cswap machinery, add `ClauderAccountProvider`).
- `devsteward/build.py`, `devsteward/config.py` — wiring + defaults.
- `devsteward/templates/.devsteward/config.yaml.tmpl`, `.devsteward/config.yaml` — config docs.
- `devsteward/core/seams.py`, `devsteward/handbook/_02-engine.qmd` — doc refresh.
- `tests/test_accounts.py` — rewrite for AC1/AC2 + keep the single-account test.

## Acceptance

- **AC1** `tests/test_accounts.py::test_clauder_gate_delegation` (regression) — verdict mapping:
  proceed/switch→ok, wait(75)→sleep N interruptibly + re-gate + stop-during-wait→ok=False,
  unsatisfiable(69)→ok=False with reason; `--threshold` passed through.
- **AC2** `tests/test_accounts.py::test_no_direct_cswap_and_degrades_without_clauder` (regression) —
  single chokepoint (no `cswap` subprocess, no `usage.json` read; cswap machinery removed) and
  PATH-absent degrade to `(True, proceeding-without-quota-check)`.
- **AC3** manual — live cswap + ≥2 accounts + `clauder monitor`; deferred to `REQ-058:validate`.
