# Plan 0018 — Rework loop (REQ-033)

`steward rework REQ-NNN`: the human-authorized return edge from a red validation back to
develop. Covers **REQ-033**.

## The gap (from the REQ)

A red validation parks (REQ-030 D8) and then dead-ends: `decision answer` only re-pends
validate against the still-broken code, and `recover` refuses (no `FAILED` step — develop
is `DONE` on the unmerged branch, validate is `BLOCKED`). The expected outcome — *the lab
found a defect, go fix it, revalidate* — has no verb. `rework` is that verb.

## Approach

A new operator verb beside `activate`/`recover` in `lifecycle.py` — a pure ledger
mutation, no git, no REQ-file edit (D1, D5).

### `devsteward/lifecycle.py` — `rework(cfg, ledger, req_id)`

Signature mirrors the pair: `recover` takes only the ledger, but `rework` also needs the
REQ frontmatter status to give the `done`→supersede refusal (D3), so it takes `cfg` like
`activate`. Returns a `ReworkResult` dataclass `{req_id, develop_step, validate_step,
evidence, brief, decision}`.

Refusals (AC2), in order, each a `LifecycleError` the CLI maps to non-zero:
1. unknown id → "not a known requirement";
2. `done` REQ → points at supersede (done is never weakened, REQ-001 / D3);
3. no `REQ-NNN:validate` step in the ledger → "no validate step" (regression-only REQ);
4. no red validation to rework → refuse. The substantive test: the **latest `validation`
   event** for the req has `ok == False` **and** `REQ-NNN:validate` is `BLOCKED`. This
   distinguishes a real red (artifact red or *declined* manual — both write a red
   `validation` event then park) from an *awaiting-oracle* manual park (which writes no
   validation event), and from a green/none validation.

Action on a valid red:
- answer any open decision parked on the validate step (`ledger.answer_decision`,
  recorded as reworked) — this also unblocks validate→`PENDING`;
- flip `REQ-NNN:develop` `DONE → RECOVER` (D-note: `RECOVER` is the runnable
  re-attempt-with-assessment status, REQ-026 D4 — the fix session assesses the branch's
  work, doesn't start blind);
- ensure `REQ-NNN:validate` is `PENDING` (idempotent with the decision answer);
- `save()`, then append a `rework` event carrying `req`, `develop`/`validate` step ids,
  the red validation's `evidence` path, and the failure `brief` (joined `detail`s of the
  not-ok results) — the `/advance` skill orients from this (D2).

### `devsteward/core/ledger.py`

Add `latest_validation(req_id)` → the last `validation` event dict for the req (or None).
The `rework` event is appended via the existing `append_event`; no new persistence shape.

### `devsteward/cli.py` — `steward rework REQ_ID`

A `click` command beside `recover`. Loads cfg + ledger, calls `lifecycle.rework`, maps
`LifecycleError`→`ClickException`, prints a green confirmation naming the reopened steps
and the evidence dir. Also: extend the `recover` help text to point a red-validation case
at `rework` (its help misled once — REQ Notes).

### `/advance` skill (repo `.claude/skills/advance/SKILL.md` + the identical stamped
`devsteward/templates/.claude/skills/advance/SKILL.md`)

Extend the §1 `--recover` clause: when the ledger has a `rework` event for this step (a red
validation was returned to develop), read the evidence dir it names — the System Tester's
`SYSTEM-TEST-FINDINGS.md` and logs — as the repair context (D2: findings travel through the
ledger, not the command line). `rework` reopens develop as `RECOVER`, so the executor
already appends `--recover` to the command.

### Handbook 02/03

A line on the V-model return edge: a red validation parks (D8 stands), and
`steward rework REQ-NNN` is the recorded human verdict that re-arms develop for a
fix-and-revalidate cycle — one explicit verb per cycle is the bound (D4).

## Tests — `tests/test_rework.py`

- **AC1 `test_rework_rearms_develop_and_validate`** — seed an in-flight REQ with a red
  `validation` event, `develop=DONE`, `validate=BLOCKED` + parked decision. `rework` →
  develop `RECOVER`, validate `PENDING`, decision `ANSWERED`, one `rework` event carrying
  the evidence path + brief; the REQ file is untouched (status still `open`, no
  `verified_by`). Cover the declined-manual shape too (D3).
- **AC2 `test_rework_refusals`** — unknown id; `done` REQ (matches /supersed/); a
  regression-only REQ (no validate step); a REQ whose validate is not blocked-red (green
  validation / awaiting-oracle manual park).
- **AC3 `test_rework_cycle_to_green_land`** — drive the full chain on the real executor
  (the `test_system_test_phase` harness): develop (deferred) → validate red park →
  `rework` → develop `--recover` (a fake session creates the marker the artifact AC checks)
  → green re-validation → mechanical land + merge. Assert the event chain in `events.jsonl`:
  red `validation` → `rework` → `step_started recover:true` → `develop_committed` → green
  `validation` → `checkpoint`.
- **AC4** is manual (FlowSteward live first case) — out of automated scope here.

## Out of scope (REQ Notes)

Reworking a **done** REQ's red re-validation (supersede); any engine-spawned repair on red
(D8 stands); rework-count/staleness limits (the explicit verb is the bound); System Tester
skill changes.
