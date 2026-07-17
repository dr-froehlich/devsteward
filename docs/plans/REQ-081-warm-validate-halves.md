# REQ-081 — warm validation cycle: `steward validate start/record` as real CLI verbs

The REQ-034 two-phase halves get CLI entrypoints so the System-Tester session survives a
red: `start` runs warm in the session (spawns nothing), the operator records the verdict
from a second plain shell, rework/revalidate run from that shell, and the still-warm
session re-runs `start` scoped per REQ-075. Shape A (`steward validate REQ-NNN`) unchanged.

## Engine changes

### `devsteward/profiles/req/validate.py`

1. **`start()`** — record the evidence dir on the start event: create the dated evidence
   dir first, then `append_event("step_started", …, evidence=<rel>)`. This is the
   cross-process handoff channel (REQ-081 Decision 6): the record half resolves the dir
   from the latest start event, never from a second state file.
2. **`resume_context(ex, req_id) -> StartContext | StepResult`** (new) — rebuild the
   `StartContext` for a standalone record half:
   - REQ file exists; `REQ-NNN:validate` step exists; step status is **RUNNING** (started,
     not yet recorded). Anything else refuses with a routing diagnostic: PENDING → "run
     `steward validate start` first"; BLOCKED → rework/revalidate; DONE → the bare
     re-run route; FAILED → repeat/reland.
   - Evidence dir: the latest `step_started` event for the step carrying `evidence`;
     fallback = the latest dated dir under `.devsteward/evidence/REQ-NNN/`. Missing → refuse.
   - `reval = _pending_revalidate(...)` (REQ-075 scope rides through), `in_flight=True`.

### `devsteward/cli.py`

3. **`validate` command dispatch** — `@click.argument("words", nargs=-1)`:
   - `steward validate REQ-NNN [--quiet]` → shape A, byte-for-byte today's behavior.
   - `steward validate start REQ-NNN` → the start half.
   - `steward validate record REQ-NNN` → the record half.
   - Anything else → usage error naming the three forms.
4. **`_validate_start`** — develop-done pre-flight (live ledger) + `check_invariants` as
   shape A; **no CLAUDECODE guard** (start spawns nothing — the calling session *is* the
   System Tester); status gate: PENDING or RUNNING (re-entry mints a fresh dated dir,
   mirroring shape A's clean re-entry), refusals route DONE/BLOCKED/FAILED. Calls
   `routine.start()` (which owns the REQ-065 pre-flight gate + lab check), prints the
   evidence dir and the handoff hint (capture → `steward validate record` from a plain shell).
5. **`_validate_record`** — refuses when a fresh `manual` AC needs a verdict and stdin is
   not a TTY (the second-shell mandate: the engine's interactive prompt is the only verdict
   channel; a Claude session cannot host it). Otherwise: `resume_context` →
   `check_invariants` → `transaction`-wrapped `routine.record(..., signoff=_interactive_signoff,
   driver="interactive")` → same outcome routing as shape A (green lands mechanically; red
   parks naming rework/revalidate, exit 1; defer parks pending).
6. **CLAUDECODE refusal messages** (cli.py bring-up guard + `Executor.bring_up_guided_session`)
   now name the real commands: `steward validate start REQ-NNN` here, then record from a
   plain shell — instead of pointing at skill "steps" that had no entrypoint.

## Doctrine surfaces (hardlink/symlink — edit once)

- `.claude/skills/system-test/SKILL.md` (hardlinked to templates): guided-mode step 4 and
  the "Two-phase, mid-session" paragraph describe the warm cycle and the real verbs.
- `devsteward/templates/STEWARD.md` (symlinked as `STEWARD.md`): System-Test section gains
  the warm-cycle flow (start warm → record in a second shell → rework → start again).
- `devsteward/handbook/_03-workflow.qmd`: same, in the validation/rework narrative.

## Tests — `tests/test_req081_halves.py`

Reuses `test_system_test_phase` fixtures (fake runners, `_write_req`, `_project`) +
`test_transaction_boundary`'s `_init_git`/`_scaffold` + `CliRunner` for CLI-level ACs.
`-k` tokens (`start_half`, `record_green`, `record_red`, `full_cycle`, `shape_a`) are
distinct from the module name (REQ-080's selector lesson).

- AC1 `start_half`: RUNNING + evidence dir printed, no session spawned, works with
  CLAUDECODE set; develop-not-done / pending-lab / REQ-065 formality each refuse.
- AC2 `record_green`: separate CliRunner invocation resolves step + evidence dir from the
  ledger, artifact gate runs, interactive prompt (fed via CliRunner input) approves →
  mechanical land (flip + index + commits).
- AC3 `record_red`: decline parks red, ledger close committed; `steward rework` and
  `steward revalidate` accept immediately; defer parks pending.
- AC4 `full_cycle`: start → record-decline → rework → fix + checkpoint develop → start →
  record-approve → land, across separate CLI invocations; REQ-075 scope/carry honored.
- AC5 `shape_a`: bare `steward validate` unchanged incl. CLAUDECODE refusal (message now
  names the halves); `record` with no started step refuses pointing at `start`.
- AC6 `test_evidence_warm_cycle_sequence` (**artifact**, engine-run under
  `steward validate REQ-081` with `DEVSTEWARD_EVIDENCE_DIR` injected per REQ-075): parses
  `warm-cycle-events.jsonl` captured into the evidence dir from the real out-of-band run
  and asserts red validation → rework/revalidate → green validation on the same step.
  Without the env var (ad-hoc local pytest) it **skips with a pointer** — it is a declared
  artifact AC, deselected project-wide from every develop gate (REQ-068), and its real
  executions happen under `steward validate`; the skip marks wrong-context, not a
  misclassified validation.
- AC7 is manual (operator attests warmness) — no test file.

## Out of scope (per REQ)

No CLAUDECODE guard on `rework`/`revalidate`; no locks; no changes to the rework verbs;
batch (`__call__`) path untouched.
