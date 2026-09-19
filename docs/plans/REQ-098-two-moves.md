# REQ-098 — Two moves, not four

Plan for `REQ-098:develop`. Requirement: `docs/requirements/REQ-098.md` (10 decisions,
6 regression ACs, no concept phase, no System-Test phase).

## The shape of the change

Four recovery verbs (`repeat`, `rework`, `revalidate`, `reland`) collapse to two
(`repeat`, `rework`). No behaviour is deleted — every body survives; what is deleted is
the operator's obligation to name which body applies. The engine reads the ledger instead.

- **`rework`** loses a precondition (the "real red"). It returns a validate step to develop
  from *any* unfinished state, and gains `--reason`.
- **`repeat`** gains a dispatch. It re-arms whatever stopped the REQ: a failed step, a red
  validate park, a manual hold, or a land refusal after a green.

Ledger event names are untouched (Decision 5) — `step_recover`, `revalidate`, `reland`,
`rework` keep writing and replaying as they do.

## Data shapes

`devsteward/lifecycle.py`:

```python
@dataclass
class RepeatPlan:          # a pure read of the ledger — what `repeat` would do
    req_id: str
    failed: list[str]      # FAILED steps to re-arm (never the land-replay validate step)
    validate: str | None   # the validate step this plan touches
    mode: str | None       # "revalidate" | "unhold" | "reland" | None

@dataclass
class RepeatResult:
    req_id: str
    kinds: list[str]       # what it did, in order: recover | revalidate | unhold | reland
    steps: list[str]       # every step id moved
    evidence / brief / decision / scope / carried   # populated on the red branch only
    land / ex              # populated by verbs.repeat on the land-replay branch only
```

`ReworkResult` keeps its fields; `evidence`/`scope`/`carried` are simply `None` outside the
red case, and `brief` carries the `--reason` or the fixed default text.

## Interfaces

| Function | Before | After |
|---|---|---|
| `lifecycle.repeat` | `(ledger, req_id)` | `(cfg, ledger, req_id)` — needs the REQ for the carry |
| `lifecycle.rework` | `(cfg, ledger, req_id)` | `(cfg, ledger, req_id, *, reason=None)` |
| `lifecycle.revalidate` | public | **deleted** — body moves into `_rearm_red_validate`, shared |
| `lifecycle.plan_repeat` | — | new: the classification, raising when nothing stopped |
| `verbs.repeat` | `(cfg, req_id)` | `(cfg, req_id, *, announce=None, stop=None)` — may land |
| `verbs.revalidate` / `verbs.reland` | public | **deleted** (`reland`'s body is reached through `repeat`) |

`verbs.repeat` classifies *before* choosing the invariant mode, because the two branches
differ: the ledger flips run `allow_any_head=True` (REQ-049 AC3 — a recovery must succeed
regardless of HEAD), while the land replay commits and so keeps the strict
`check_invariants(ex)`.

## Files touched

**Engine**
- `devsteward/lifecycle.py` — `plan_repeat`, the new `repeat`, `rework(--reason)`;
  `_resolve_red_validation` becomes `_resolve_rework_target` (state-shaped, not red-shaped);
  `revalidate` deleted, its body shared as `_rearm_red_validate`.
- `devsteward/verbs.py` — `repeat` dispatches (incl. the land replay); `revalidate`/`reland`
  deleted from `__all__` and the module; the `answer_decision` redirect drops `revalidate`.
- `devsteward/cli.py` — `revalidate` + `reland` commands deleted; `rework --reason`;
  `repeat` prints per branch (`_print_report` on the land replay); `status` hints name the
  two moves on a held/red validate step; `validate-start` routing reworded.
- `devsteward/profiles/req/validate.py` — `_park_red` brief names the two moves;
  `resume_context` routing and `_reland_refusal` reworded. `_SCOPING_EVENTS` unchanged.
- `devsteward/dashboard/model.py` — `_offer` returns the two moves (+ `rework` on a pending
  validate whose develop is done).
- `devsteward/dashboard/app.py` — `STEP_VERBS = ("repeat", "rework", "activate")`; the
  `rework` handler forwards the form's `reason`; the `repeat` handler renders all branches.
- `devsteward/dashboard/templates/project.html` — Backlog above Requirements (Decision 8);
  an inline `reason` input on the rework form.

**Shipped artifacts (same commit — REQ-094)**
- `devsteward/templates/STEWARD.md` — Recovery table collapses to the two moves; the
  command-reference rows for `revalidate`/`reland` go (the derived guard reads this table).
- `devsteward/templates/.claude/skills/advance/SKILL.md` — a `rework` event may carry no
  evidence dir; orient from its `brief` then (AC2). Inode-shared with `.claude/skills/`.
- `devsteward/templates/.claude/skills/{intake,system-test}/SKILL.md` — drop the verb names.
- `devsteward/handbook/_01-format.qmd`, `_02-engine.qmd`, `_03-workflow.qmd`.

**Tests**
- `tests/test_req098_two_moves.py` — the five named AC node-ids.
- `tests/test_revalidate.py` → migrated onto `repeat` (AC6: migrated, not deleted).
- `tests/test_reland.py` → the routine-level tests stand; the verb-level entry becomes
  `repeat`.
- `tests/test_lifecycle.py`, `tests/test_phase_model.py` — the `repeat(cfg, led, …)` signature.
- `tests/test_dashboard.py`, `tests/test_req081_halves.py`, `tests/test_req088_evidence_mint.py`
  — the CLI verb they invoke.

## Test approach

`tests/test_req098_two_moves.py` reuses `test_rework.py::_seed_red` (the in-memory git
topology + real ledger where the red is produced today) and `test_reland.py::_build` for
the land-replay branch, so the new verb runs against exactly the wiring the old ones did.

- **AC1** drives `rework` from each of the four unfinished validate states and asserts the
  event shape per state, then the four refusals with a before/after ledger snapshot.
- **AC2** asserts `--reason` through `CliRunner` and through the Flask test client, and
  greps the shipped `/advance` skill for the no-evidence orientation rule.
- **AC3** drives `repeat` from every stopping state on one seeded project.
- **AC4** is the removal guard: the click registry, the `steward status` output, the
  `_park_red` brief, `resume_context`'s routing, `_offer`, and a grep over the shipped
  artifacts + handbook.
- **AC5** renders `/p/<name>` and compares the two headings' positions.

## Not in this checkpoint

The consumer sweep (Decision 9) — a post-land attended chore, homed in the REQ's Notes.
