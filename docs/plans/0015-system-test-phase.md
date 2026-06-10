# Plan 0015 — System-Test phase (REQ-030)

The conditional validation phase between the fused develop step and the mechanical land:
an independent System Tester session, engine-run `artifact` gates, dated evidence events,
`manual` sign-offs, and `steward validate` as the single entry point. Implements REQ-030
(Decisions 1–10); the first real lab evidence stays REQ-031's.

## Shape

**Step model (`profiles/req/source.py`).** Per active REQ the acceptance ACs partition by
the REQ-027 `check:` key:

- `regression` (and undeclared) tests stay on the `develop` step's gate;
- any `artifact` or `manual` AC adds exactly one `REQ-NNN:validate` step (D1) whose
  `verify` carries the `artifact` test commands;
- `validate` depends on `REQ-NNN:develop` **plus** the final step of every `process.lab`
  REQ (D7 — same mechanics as `depends_on`; a not-done lab blocks eligibility, surfaced
  via a `blocked_note` on the step that `steward status` prints);
- a dependent REQ depends on the dep's **final** step (`:validate` when it exists, else
  `:develop`), so done keeps meaning *verified and validated* (D6);
- a develop step with a validate sibling gets `lands=False` — its green gate commits the
  work on the feature branch but defers the land.

**Core (`core/model.py`, `core/executor.py`).** `Step` gains `lands: bool = True` and
`blocked_note: str = ""` (content-opaque). The executor:

- on a green develop gate with `lands=False`: commit the work, mark the step DONE, emit a
  `develop_committed` event — no done-flip, no index touch, no merge (D6);
- routes `phase == "validate"` steps to a new pluggable `validate_runner` seam (the REQ
  profile's routine; the generic profile has none);
- merges `--no-ff` after a green land only for landing steps (`step.lands`), i.e. after
  the validate land when one exists;
- `checkpoint()` (interactive close) honors the same deferral.

**Validate routine (`profiles/req/validate.py`).** One function both `steward validate`
and the executor's batch loop call (D9):

1. refuse (no event, no park) while a `process.lab` REQ is not done (D7);
2. create `.devsteward/evidence/REQ-NNN/<timestamp>/`;
3. with `artifact` ACs, spawn the fresh **System Tester** session (`/system-test REQ-NNN
   --evidence <dir>`; model/effort from `claude.steps.validate`, default opus/high) —
   the session orients, preps the lab, drives the procedure, captures artifacts; it never
   sees develop's diff (a fresh `claude -p`) and cannot talk the gate green (D2);
4. the **engine** runs each `artifact` AC's named test command itself (pytest semantics:
   skip = red, zero-collected = red); an empty evidence dir with artifact ACs is the
   missing-artifact hard red (D3);
5. `manual` ACs: unattended → park a decision naming the pending human oracle (D4);
   attended → the sign-off provider supplies verdict + optional scope, the engine
   composes the full provenance (date, reviewer, scope) mechanically;
6. append the dated `validation` evidence event (per-AC results, artifact relative paths
   + sha256, sign-offs) and write the engine-composed `verified_by` summary (D3);
7. green in-flight → the shared `mechanical_land` (flip + index + commit + ledger) and
   the `--no-ff` merge; green on a done REQ → fresh evidence only, status untouched (D5);
8. red → record the red event, park with the failure brief, **no repair loop** (D8).

**CLI (`cli.py`).** `steward validate REQ-NNN`: executes the pending validate step
in-flight (interactive sign-off prompts; reviewer defaults to git user.name) or appends
fresh evidence on a done REQ. `steward status` prints the lab-wait note.

**Config (`config.py`, `build.py`).** `validate` joins `STEP_CLAUDE_DEFAULTS` (inherits
opus/high); `build_executor` wires the validate runner + step kind for the REQ profile.

**Skill.** `.claude/skills/system-test/SKILL.md` + the identical stamped copy under
`devsteward/templates/.claude/skills/system-test/`.

**Verifier nuance (`profiles/req/verify.py`).** A develop step with no named regression
tests stays red on marker-trust *unless* it defers to a validate step (`lands=False`) —
the REQ's runnable gate then lives at validate (the decoupled oracle), which is the whole
point of the phase; the full-suite gate still runs.

## Tests (`tests/test_system_test_phase.py`)

AC1 `test_phase_conditional_on_check` · AC2 `test_context_independence` · AC3
`test_evidence_event_and_skip_is_red` · AC4 `test_validate_single_entry_point` · AC5
`test_manual_decision_stop` · AC6 `test_red_validation_parks_no_repair` · AC7
`test_lab_dependency_blocks_validation` — wired like `test_phase_model.py` (real
source/verifier/flipper around `FakeRunner`/`FakeGitTopology`; real pytest subprocesses
where skip/zero-collect semantics matter).

AC8 is `manual`: a real engine run drives a scratch REQ (decoupled golden-file artifact
check authored at intake + a manual stop) through develop → validate → decision stop →
land; the human reviews `events.jsonl`, the evidence dir, and the merged commit, and
signs off via `steward validate REQ-030`.

## Out of scope

REQ-031 (the IMAP lab, first real evidence), checkpoint/validate unification beyond the
shared routine, release-gate re-runs (handbook prose, D5), auto-staleness (rejected).
