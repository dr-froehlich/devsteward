# 0008 — Visible quota rotation, fixed gate & graceful stop (REQ-025)

**Date:** 2026-06-09
**Status:** **DESIGN.** Build-ready implementation design for REQ-025. Pins the exact seams,
data shapes, edit sites, and the ten acceptance-test stubs. No production code yet.
**Author:** Peter Fröhlich + Claude (REQ-025 design checkpoint)
**Reference (do not diverge):** `~/Theresa/run_batch.py` — `usage_snapshot`,
`pick_and_ensure_account`, `_interruptible_sleep`, `_sigint`, `stream_claude`. This REQ is
the port REQ-001 always wanted: the **adaptive** gate (`current_gate` / `load_costs` /
`batch_job_costs.json`) is deliberately **left behind** (REQ-025 D4, Notes).

## The change in one line

Turn `CswapAccountProvider` from a status-only switcher into a *numeric, visible,
gate-and-rotate* provider reading cswap's cached `usage.json`; add a `StopController` core
seam the run/advance drivers own; and give `run_claude` `start_new_session=True` +
`--model`/`--effort` — all optional and self-degrading.

## Audit confirmed against the live tree

- `core/accounts.py` `precheck()` today runs `cswap --switch-to N` (when pinned) + a
  throwaway `cswap --status`, then always returns `(True, …)` — **no numbers, no rotation,
  no console output, no wait.** This is the entire surface to replace. (lines 40–76)
- `core/claude.py` `run_claude` spawns `claude` **without** `start_new_session=True`
  (line 181) → carries reference bug (a): a parent SIGINT is forwarded to the child. It has
  **no** `--model`/`--effort` (argv built at lines 170–176) and **no** quota wait.
- `core/executor.py` `run_step` calls `accounts.precheck()` (line 217) and treats
  `ok=False` as `RunOutcome.LIMIT` → sets the step back to `PENDING` and the `run` loop
  **breaks** (lines 406–408). REQ-025 D3 changes the *meaning*: the gate now waits through
  the reset, so `ok=False` happens **only** on a stop-during-wait.
- `cli.py` `run`/`advance` already expose `--use`; they need `--threshold`/`--model`/
  `--effort` and must install the `StopController` SIGINT handler around the drive.
- `build.py` `build_accounts` / `build_executor` and `config.py` thread the new knobs.
- The four seams (`seams.py`) stay as-is; `AccountProvider.precheck()` already returns
  `(ok, reason)`, which is the exact shape the gate-and-rotate loop needs.

## Decisions already settled (REQ-025) — not re-opened

D1 numeric `usage.json` reading · D2 prefer-current / lower-7d rotate · D3 wait-through-reset
(stop is the only early exit) · D4 fixed threshold 70, no adaptive · D5 mandatory visibility
· D6 rotate by default / `--use N` pins · D7 two-level graceful stop owned by drivers · D8
`start_new_session=True` + model/effort defaults Opus/high · D9 optional & self-degrading.
No open forks; nothing parked.

---

## Architecture: three touch-points

```
core/accounts.py   numeric usage + gate-and-rotate loop      (extends CswapAccountProvider)
core/stop.py  NEW  StopController: stop flag + child handle + SIGINT install + interruptible sleep
core/claude.py     start_new_session=True + --model/--effort + on_spawn child registration
                   ↕ threaded by build.py / config.py / cli.py
```

### A. `core/accounts.py` — numeric, visible, gate-and-rotate

**New module constants** (data-dir discovery, ported verbatim from `run_batch.py:72–81`):

```python
_CSWAP_DIRS = [Path.home()/".local"/"share"/"claude-swap",
               Path.home()/".claude-swap-backup"]
def _cswap_data_dir() -> Path:
    return next((d for d in _CSWAP_DIRS if d.exists()), _CSWAP_DIRS[0])
# cache/usage.json (per-slot 5h/7d), sequence.json (activeAccountNumber)
```

**`AccountUsage` dataclass** (mirrors the reference shape exactly):
`slot:int, pct_5h:float, pct_7d:float, minutes_to_5h_reset:int, clock_5h_reset:str`.

**Free helpers** (module-level so tests drive them without a provider):
- `_parse_countdown_to_minutes(s)` — `"1d 2h 30m"` → minutes (ref `:169`).
- `usage_snapshot(data_dir, *, force, run=subprocess.run) -> dict[int, AccountUsage]`:
  optionally `cswap --list` (NO_COLOR, non-fatal) then parse
  `data_dir/cache/usage.json`’s `data[slot].{five_hour,seven_day}.{pct,countdown,clock}`.
  **Missing/unreadable file or bad JSON → `{}`** (the degrade signal). (ref `:191–223`)

**`CswapAccountProvider.__init__`** gains keyword seams (all defaulted so existing
call-sites and `SingleAccountProvider` are untouched):

| param | meaning | default |
|-------|---------|---------|
| `use: int\|None` | pin a slot (D6) | `None` |
| `threshold` | fraction *or* percent; normalised to **percent** internally (`t*100 if t<=1 else t`) | `70` |
| `announce: Callable[[str],None]` | visibility sink (D5) — the run/advance stderr channel | `lambda _: None` |
| `should_stop: Callable[[],bool]` | stop predicate for interruptible waits (D3/D7) | `lambda: False` |
| `poll_seconds` | re-poll cadence while saturated | `60` |
| `data_dir: Path\|None` | test override for the cswap dir | discovered |

**`precheck()` becomes the gate-and-rotate loop** — a faithful port of
`pick_and_ensure_account` (ref `:246–316`) **minus** `current_gate` (the threshold is the
fixed normalised percent), returning `(ok, reason)`:

- `should_stop()` at top → `return (False, "stop requested")` (the **only** not-ok exit, D3).
- `snap = usage_snapshot(...)`; **empty → degrade**: announce "proceeding without quota
  check", `return (True, …)` (D9, AC7).
- **Pinned (`use is not None`, D6/AC4):** switch to `use` if not active (reuse existing
  `_switch_to`, non-fatal); if below threshold announce + return ok; else announce the wait,
  `_interruptible_sleep(minutes_to_5h_reset*60)`, re-poll on `poll_seconds` until below or
  stop — **never swap to another slot**.
- **Rotate (no pin, D2/AC2):** `below = [u for u in snap if u.pct_5h < gate]`; build the
  one-line `#slot: 5h x% / 7d y%` summary (announce it — AC6). If the **current** slot is
  below → **stay** (announce "staying on #N", no flap). Else switch to the **lowest-7d**
  below-threshold slot (announce the switch). If none below → announce "all saturated",
  `_interruptible_sleep` to the **soonest** reset, re-poll until one frees or stop.
- Every announce names slot + 5h/7d% + reset clock/ETA (D5). Active-slot read from
  `sequence.json activeAccountNumber` via `_active_slot()` (ref `:184–188`), default `0`.

`claude_argv()` stays `["claude"]` (cswap 0.11 is a switcher — unchanged).

### B. `core/stop.py` — the `StopController` seam (NEW)

Ports `_sigint` + `_interruptible_sleep` + the `_active`/`_active_lock` globals (ref
`:92–137`) into one object the **drivers** own (D7; the engine, not a skill, owns run
lifecycle — the ledger-contract principle):

```python
class StopController:
    def __init__(self): _flag=Event(); _child=None; _lock=Lock()
    def should_stop(self) -> bool          # _flag.is_set()
    def register_child(self, proc) -> None  # the active claude Popen (under lock)
    def clear_child(self) -> None
    def install(self) -> None               # signal.signal(SIGINT, self._on_sigint)
    def interruptible_sleep(self, secs)     # poll should_stop every <=5s (ref :122)
    def _on_sigint(self, *_):
        if self._flag.is_set():             # 2nd Ctrl-C: kill child PG, exit 130
            os.killpg(os.getpgid(child.pid), SIGKILL); sys.exit(130)
        self._flag.set()                    # 1st Ctrl-C: finish current step (D7)
```

The child is killable by **process group** precisely because `run_claude` now starts a new
session (B↔C dependency). `interruptible_sleep` is what the provider’s `should_stop` +
waits compose with (the provider takes the predicate, the driver owns the controller).

### C. `core/claude.py` — signal isolation + model/effort

- `Popen(..., start_new_session=True)` at line 181 (fixes ref bug (a); AC8).
- New params `model: str = DEFAULT_MODEL` (`"claude-opus-4-8"`), `effort: str =
  DEFAULT_EFFORT` (`"high"`); append `--model <model> --effort <effort>` to argv after the
  permission flags. `None`/empty → omit the flag (tests/attended).
- New `on_spawn: Callable[[Popen],None] | None` — called right after `Popen` so the driver
  registers the child with its `StopController`; `finally` clears it. (Keeps `claude.py`
  ignorant of `StopController` — pure callback, no import cycle.)

### D. Threading (`config.py` → `build.py` → `cli.py` → `executor.py`)

- **config.py:** read `accounts.threshold` (already-present `accounts` dict), `claude.model`,
  `claude.effort`. Defaults: threshold `70`, model `claude-opus-4-8`, effort `high`.
- **build.py:** `build_accounts(cfg, *, use, threshold, announce, should_stop)`;
  `build_executor(..., model, effort, stop)` passes model/effort + stop predicate down.
- **executor.py:** `run_step`/`run`/`advance_once` accept the stop controller; `run` checks
  `stop.should_stop()` at the **top of the loop** → finish nothing new, break (AC9). `run_step`
  forwards `model`/`effort`/`on_spawn=stop.register_child` to the runner. `ok=False` from
  `precheck` (now meaning *stopped during wait*) still maps to `RunOutcome.LIMIT`/stop and
  breaks the loop — the existing wiring at `:217–222`,`:406–408` is reused, only its trigger
  changes.
- **cli.py:** `run`/`advance` gain `--threshold`, `--model`, `--effort`. Each builds a
  `StopController`, calls `.install()`, wires `announce=_stderr_announcer` and
  `should_stop=ctrl.should_stop` into the provider, and threads model/effort. CLI flag >
  config > default.

---

## Exact edit sites (Build)

| File | Edit |
|------|------|
| `core/accounts.py` | + `AccountUsage`, `_cswap_data_dir`, `_parse_countdown_to_minutes`, `usage_snapshot`, `_active_slot`; rewrite `precheck` to the gate-and-rotate loop; widen `__init__` |
| `core/stop.py` **(new)** | `StopController` (flag + child + SIGINT install + interruptible sleep) |
| `core/claude.py` | `start_new_session=True`; `DEFAULT_MODEL`/`DEFAULT_EFFORT`; `model`/`effort`/`on_spawn` params + argv |
| `core/executor.py` | thread `model`/`effort`/`stop`; top-of-loop stop check; `on_spawn=register_child` |
| `config.py` | parse `accounts.threshold`, `claude.model`, `claude.effort` (+ Config props) |
| `build.py` | thread the new knobs through `build_accounts`/`build_executor` |
| `cli.py` | `--threshold`/`--model`/`--effort` on `run`/`advance`; build+install `StopController`; stderr announce sink |

## Acceptance-test stubs (Build writes these; Land makes them green)

| AC | Test (named in REQ frontmatter) | Asserts |
|----|----------------------------------|---------|
| AC1 | `tests/test_accounts.py::test_usage_snapshot_parses_and_degrades` | parses fixture `usage.json` → 5h/7d%/countdown; missing/garbled → `{}` |
| AC2 | `…::test_gate_rotates_when_current_saturates` | current<gate ⇒ stay; current≥gate ⇒ switch to lower-7d below-gate slot (no flap) |
| AC3 | `…::test_threshold_fixed_and_overridable` | `0.70`≡`70`; override honoured; never tightens from cost (no adaptive) |
| AC4 | `…::test_use_pins_and_waits_own_reset` | `use=N` switches to N; saturated ⇒ waits N’s own reset, never swaps |
| AC5 | `…::test_quota_wait_is_interruptible` | all saturated ⇒ `should_stop`-True mid-wait returns promptly `(False, …)` |
| AC6 | `…::test_announces_utilization_and_switches` | injected sink receives active-slot summary + each switch/wait line |
| AC7 | `…::test_degrades_without_cswap` *(exists — keep green)* | cswap/usage absent ⇒ proceed on current, gate skipped, notice logged; `SingleAccountProvider` plain |
| AC8 | `tests/test_claude_stream.py::test_new_session_and_model_effort` | `Popen` got `start_new_session=True`; argv carries `--model claude-opus-4-8 --effort high` |
| AC9 | `tests/test_executor.py::test_graceful_stop_after_current_step` | one stop ⇒ current step completes, next not started; controller 1st-SIGINT sets flag, 2nd kills child |
| AC10 | `tests/test_cli_smoke.py::test_run_account_and_model_options` | `run`/`advance` accept `--threshold/--model/--effort` (+`--use`) and thread them |

**Test-injectability:** `usage_snapshot(data_dir=tmp_path, run=fake_run)` reads a fixture
tree; the provider takes `data_dir=`, `announce=`, `should_stop=` overrides — no real cswap,
no real sleep (inject `should_stop=lambda:True` to make every wait return at once). AC8 uses
a `Popen` spy; AC9 a fake runner + fake `StopController`; AC10 the click `CliRunner`.

## Migration note (existing tests touched at Build)

`test_use_switches_account` and `test_precheck_status_non_fatal` assert the **old**
`cswap --status` gate; precheck no longer calls `--status` (it reads `usage.json`). Build
must update those two to the snapshot gate (still asserting non-fatal degradation), keeping
`test_degrades_without_cswap`/`test_single_account_provider` green as the AC7 anchor.

## Out of scope (unchanged from REQ-025)

Adaptive/cost-history gate, `STOP_BATCH` file marker, configurable cswap binary path, any
rotation policy beyond prefer-current / lower-7d / pin-by-index. All engine console output
is operational English; no German UI strings introduced.
