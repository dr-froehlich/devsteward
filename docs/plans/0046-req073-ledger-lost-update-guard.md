# Plan 0046 — REQ-073: ledger lost-update guard + stale-decision recovery

Covers **REQ-073** (depends on REQ-003, REQ-005, REQ-035, REQ-055, REQ-057).

Engine-only; fused develop; no lab; all-`regression` ACs proven with synthetic ledgers in
temp dirs. Two coupled defects from the 2026-07-03 intake brief:

- **D1 — lost update.** `Ledger.save()` is a blind whole-file dump of an in-memory dict. A
  process holding an older snapshot that saves after a newer commit rewinds the newer facts
  by last-write. Fired live in FlowSteward (DEC-044): a long-lived attended-validate parent
  loaded the ledger at `start()`, blocked for the session, and its terminal `save()` at
  `record()` rewound a completed land (`validate → done`, decision → answered, cursor
  advanced) that a second invocation had committed in between. `state.yaml` diverged from the
  append-only `events.jsonl`.
- **D2 — no recovery.** Once `state.yaml` says `DEC-044 = open` while the REQ is `done`, no
  CLI verb closes it: `steward validate` on a done REQ routes to `revalidate` (non-mutating),
  and `steward decision answer` refuses a `:validate` decision (REQ-057) and redirects back to
  `steward validate`. The two remedies point at each other; the only exit was hand-editing
  `state.yaml` — the one thing STEWARD.md forbids.

## Approach

### D1 — a monotonic `seq` guard + per-mutation journal (Decisions 1, 2, 2a, 6)

`state.yaml` carries a monotonic `seq`, bumped on every write. Each `Ledger` instance
remembers the `seq` it last synced with disk (`_loaded_seq`). At `save()` we read the
on-disk `seq`; if it is **newer** than ours, another process saved since we loaded — the
blind whole-file write is refused. Instead:

- **Reconcile** when this process's mutation is expressible as a targeted re-application. The
  four mutating methods (`set_status`, `set_cursor`, `park_decision`, `answer_decision`) each
  record a small **journal** closure describing *only their own* mutation (keyed by
  step-id / decision-id, not by a captured dict reference). On a `seq` conflict, `save()`
  reloads the newer on-disk state and **replays the journal** onto it — re-applying just this
  process's mutation, leaving every unrelated newer fact intact — then writes with a bumped
  `seq`. This is the FlowSteward shape: the stale parent's terminal save re-applies only its
  own step status; the interleaved land's decision/cursor/other-step survive.
- **Fail loudly** when the pending write carries **no** journal entry — a broad, blind dump
  with no recorded targeted mutation. That path is reachable only by an engine code path that
  bypassed the targeted API (an engine defect, Decision 2a). `StaleSaveError` states that
  **nothing was lost**, names both preserved sides (the newer on-disk `state.yaml` and the
  append-only `events.jsonl`), and instructs: re-run; if it recurs, report an engine defect;
  never hand-edit `state.yaml`.

It is a **check, not a lock** (house principle: minimal topology). The journal is only
consulted on a conflict; in normal single-process operation `save()` just bumps `seq` and
writes. A legacy `state.yaml` with no `seq` loads unchanged and acquires `seq` on its first
save (Decision 6) — a missing on-disk `seq` is never a conflict.

### D2 — targeted recovery on the revalidate route (Decisions 3, 4, 5)

`steward validate REQ-NNN` on a **done** REQ, before the (non-mutating) re-validation, first
reconciles any lingering **open** `:validate` decision for that step: a done REQ with an open
validation hold is self-evidently resolvable — the land is already in the event log. The new
`Ledger.reconcile_validation_decision()` closes the decision (status → answered with a
reconciliation note) and appends a `decision_reconciled` event; it touches **only** the
decision record — `verified_by`, `status`, and the frozen landing provenance stay untouched
(REQ-035, Decision 5). When it reconciles something the command reports the recovery and
returns (subtraction: no wasted fresh System-Test session on a diverged ledger); a clean done
REQ still runs the normal fresh-evidence revalidate.

The REQ-057 `decision answer` guard stays **unchanged** (Decision 4) — a `:validate` decision
still refuses free-text answers and redirects to `steward validate` — but the redirect target
now actually resolves the diverged state, so the two remedies terminate instead of looping.
No new `steward reconcile` verb (Decision 3): a general event-log-replay verb is machinery for
a class the `seq` guard removes; it stays a named rejected alternative to re-intake only if a
second divergence shape ever appears.

## Changes

### `devsteward/core/ledger.py`
- `StaleSaveError(StewardError)` — the loud, actionable refusal (carries `.recovery`).
- `__init__`: `self._loaded_seq: int | None = None`, `self._journal: list[callable] = []`.
- `reload()`: pick up `seq` into `_loaded_seq`.
- `save()` → guarded: read on-disk `seq`; on a newer-disk conflict, replay the journal onto
  the reloaded state (or raise `StaleSaveError` if the journal is empty); always bump `seq`,
  write, clear the journal, update `_loaded_seq`.
- `set_status` / `set_cursor` / `park_decision` / `answer_decision`: append a by-id/by-key
  journal closure alongside the in-memory mutation (park/answer keep their own `save()`).
- `reconcile_validation_decision(decision_id)`: close an open decision as reconciled, append
  a `decision_reconciled` event, leave step status untouched.

### `devsteward/profiles/req/validate.py`
- `ReqValidateRoutine.reconcile_stale_validation_decision(led, req_id) -> list[Decision]`:
  reconcile every open decision on `f"{req_id}:validate"`.

### `devsteward/cli.py`
- `validate` done-branch: run `reconcile_stale_validation_decision` inside a transaction
  (`check_invariants(allow_any_head=True)`, HEAD-agnostic like `decision answer`); if it
  reconciled anything, report the recovery and return before revalidate.

### Docs (Decision 7)
- `devsteward/templates/STEWARD.md` (symlinked as `STEWARD.md`) and
  `devsteward/handbook/_02-engine.qmd`: name the recovery — a `done` REQ still surfacing a
  parked `:validate` decision is closed by `steward validate REQ-NNN`, never by hand-editing
  `state.yaml`.

## Tests

- `tests/test_ledger_concurrency.py` — AC1 (stale save never rewinds), AC2 (`seq` monotonic
  and guards), AC2b (targeted mutations always reconcile; broad write refuses actionably),
  AC3 (FlowSteward long-lived interleaved-land shape), AC6 (legacy no-`seq` upgrade).
- `tests/test_validate_recovery.py` — AC4 (`steward validate` on a done REQ closes the stale
  decision, freezes provenance, `steward status` stops surfacing it), AC5 (no mutually
  pointing dead end: `decision answer` refuses+redirects, following the redirect resolves).
