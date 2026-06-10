# Plan 0014 — `steward checkpoint`: the engine is the verifying bookkeeper for interactive work

Covers **REQ-018** (plan-0011 step 3). REQ-029 built the shared tail
(`Executor.checkpoint()` → REQ-028 gate → `mechanical_land`); this plan finishes the
interactive path: full topology close-out, driver provenance, the cursor-default CLI
argument, the interactive-first handbook flip, and dedicated acceptance tests.

## What exists (REQ-029) and what is missing

| Piece | Status |
|-------|--------|
| `Executor.checkpoint()` — branch guard → verify → `mechanical_land` | shipped |
| `steward checkpoint REQ-NNN [PHASE]` CLI | shipped (REQ id mandatory) |
| `/advance` interactive close via `steward checkpoint` (repo + template) | shipped |
| Close-out: trailing-ledger follow-up commit + `--no-ff` merge on the interactive path | **missing** (D4) |
| `driver:` provenance on the `checkpoint` event | **missing** (D5) |
| CLI target defaulting to the cursor step | **missing** (REQ text) |
| Handbook interactive-first; "no engine guarantees" framing removed | **missing** (D6) |
| `tests/test_checkpoint.py` | **missing** |

## Changes

### `devsteward/core/executor.py`

- `mechanical_land(step, detail="", driver="headless")` — the `checkpoint` event gains
  `driver=<driver>`. The batch path (`run_step`) keeps the default `headless`.
- `Executor.checkpoint(step)` — passes `driver="interactive"`; after a `DONE` land of a
  `develop` step it runs the shared `_merge_after_land(step)` (follow-up commit of the
  trailing ledger write, `--no-ff` merge, `branch_merged` event). On the integration
  branch `_merge_after_land` already no-ops (D4). Red path unchanged: red `verify` event
  + step `FAILED`, zero land-side writes (D3) — a re-run needs no `recover`.
- Module docstring: the interactive mode is no longer "no engine guarantees" — the engine
  is the verifying bookkeeper in both modes; only the driver varies.

### `devsteward/cli.py`

- `checkpoint`: `REQ_ID` becomes optional. Absent → resolve the target from
  `ledger.cursor_step`; `PHASE` defaults to `develop`. No cursor and no argument is a
  clear error naming the fix.

### Handbook + skill + templates (D6/D7)

- `00-method.md` item 4, `02-engine.md` guarantees section + events list,
  `03-workflow.md` two-modes section + day-in-the-life, `04-skills.md` `/advance` +
  park contract: interactive driving with `steward checkpoint` is the **default**;
  `steward run`/`steward advance` are the **batch lane** for queues of well-specified,
  low-fork REQs; the engine certifies in both modes (the "no engine guarantees" /
  "human is the guarantee" framing is removed). 02-engine documents the standing rule
  that engine REQs originate from consumer postmortems.
- `.claude/skills/advance/SKILL.md` and
  `devsteward/templates/.claude/skills/advance/SKILL.md` (kept byte-identical): the mode
  framing flips the trust model; the interactive close documents the full close-out
  (verify → land → follow-up → merge).
- `devsteward/templates/CLAUDE.md.tmpl`: same reframing of the two-mode paragraph;
  `steward checkpoint` joins the command list.

### Tests — `tests/test_checkpoint.py`

Profile-wired executor (ReqStepSource/ReqVerifier/ReqDoneFlipper/PlanArtifactGate) over
`FakeGitTopology` + `FakeRunner`, the `test_phase_model.py` pattern:

- AC1 `test_green_checkpoint_verifies_and_advances` — CLI `steward checkpoint` (no args,
  cursor default) on a green develop step: flip + index sync + `checkpoint` event with
  commit sha and `driver: interactive`, ledger advanced, zero claude calls.
- AC2 `test_red_gate_no_land_writes` — red gate: red `verify` event, step `FAILED`,
  non-zero exit, no flip/index/commit/cursor/checkpoint-event; the re-run after a fix
  lands with no `recover`.
- AC3 `test_no_step_redo_after_checkpoint` — the next eligible step after a green
  checkpoint is the successor REQ, not a redo.
- AC4 `test_full_close_out_merges` — on a feature branch: trailing-ledger follow-up
  commit + `--no-ff` merge + `branch_merged` event; on the integration branch no merge.
- AC5 `test_driver_provenance_both_modes` — batch land writes `driver: headless`,
  interactive checkpoint `driver: interactive`, same event shape.
- AC6 `test_handbook_and_skill_interactive_first` — shipped handbook chapters carry the
  interactive-first framing and no "no engine guarantee(s)" phrase; both `/advance`
  copies are identical and close via `steward checkpoint`.

## Landing REQ-018 itself (AC7 interim convention)

REQ-018 carries a `manual` AC, and until REQ-030 routes validation-side criteria out of
the develop gate, `steward checkpoint` on REQ-018 itself goes red by design (the gate
runs every named AC command — it must not fake validation). So this REQ lands by the
REQ-029 AC8 precedent: implementation commit on `req-018-*` → `--no-ff` merge into
`dev` now; the `done` flip is a follow-up hand-commit after the human reviews the AC7
proof run (scratch stamp: a trivial REQ driven interactively, closed by the new
`steward checkpoint`, evidence: `events.jsonl` with `driver: interactive`, the synced
index, the merge) with provenance in `verified_by` (REQ-027 D12 interim convention).
**No `steward checkpoint` is run against REQ-018's own ledger** — a red row would make
the later hand-flip a lint contradiction.
