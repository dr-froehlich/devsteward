# Plan 0048 — REQ-074: re-found the `steward decision` surface

Approved concept: `docs/concepts/REQ-074.md` (direction "re-found", Peter 2026-07-05).
Two moves: (1) non-fork producers stop creating `Decision` records and become ledger
**holds**; (2) genuine skill forks get the guided loop — park-with-brief → attended
`steward decide` → answered fork delivered into the resumed step's prompt.

## Data shapes

- `Decision` (core/model.py) gains optional brief/answer fields, all defaulted so legacy
  records load unchanged: `context: str = ""` (what was tried / consequences),
  `recommendation: str = ""`, `rationale: str | None = None` (the operator's reasoning,
  set at answer time).
- Ledger step entry gains an optional `hold` note (string): set with BLOCKED, cleared by
  any later `set_status`. State.yaml only; no REQ-file change.

## Ledger (core/ledger.py)

- `set_hold(step_id, note)` — journaled targeted mutation: status → BLOCKED, `hold` note,
  `updated`. `hold_note(step_id) -> str`.
- `set_status` clears a stale `hold` on any transition.
- `answer_decision(decision_id, answer, rationale=None)` — stores `rationale`; the
  `decision_answered` event carries it.

## Move 1 — holds, not decisions

- `validate._park_manual`, `_park_pending`, `_park_red`: `led.set_hold(step, question)`
  instead of `park_decision`; outcomes/events/commit behavior unchanged.
- `executor._park_attended`: same replacement; keeps the `attended_parked` event.
- `steward status`: a BLOCKED step renders its ledger hold note (takes precedence over the
  static profile `blocked_note`); open decisions section unchanged (genuine forks only).
- `executor.only_ineligibility_reason` BLOCKED branch: name the hold note + its real verb
  when no open decision exists; point at `steward decide` when one does.
- `steward run` close: the "N fork(s) parked — see `steward decision list`" line counts
  open decisions only, not holds.
- Legacy: the REQ-057 `:validate` answer-guard and the REQ-073 reconcile path stay, for
  records that predate this REQ.

## Move 2 — the guided loop

- `executor._detect_park` sentinel parsing: after `[[DEVSTEWARD_PARK]]`, line 1 = question;
  following lines within the block — `- <option>` lines → `options`,
  `recommendation: <text>` → `recommendation`, other non-blank lines → `context`.
  The skill-written path (decision dict in state.yaml) may carry the same fields directly;
  `/advance` SKILL.md §3 documents the brief as required content.
- `steward decision list` renders context/options/recommendation.
- New CLI verb `steward decide DEC-NNN`:
  - refusals: inside a Claude session (CLAUDECODE, mirror `validate`), under
    `DEVSTEWARD_UNATTENDED=1`, no such open decision, `:validate` decision (redirect —
    legacy records only).
  - brings up an interactive guided session (`run_claude_interactive`) with a composed
    briefing prompt (question, context, options, recommendation, the step + REQ pointer);
    the operator interrogates live. Editor pattern: the engine records **after** exit —
    `click.prompt` choice among numbered options (or free text) + one-line rationale, then
    `answer_decision(id, answer, rationale)` inside a git transaction. The session cannot
    self-certify.
- Delivery on resume: `executor.run_step` appends the latest *answered* decision for the
  step to the spawned command — question, chosen option, rationale, "honor this decision;
  do not re-open the fork" (the `--repair` brief pattern).

## Files touched

`devsteward/core/model.py`, `core/ledger.py`, `core/executor.py`,
`profiles/req/validate.py`, `devsteward/cli.py`, `.claude/skills/advance/SKILL.md`
(hardlinked template), `devsteward/templates/STEWARD.md` (symlinked as repo STEWARD.md),
handbook mention if any. Tests: new `tests/test_decision_refound.py`,
`tests/test_decide.py`; existing suites updated where they assert decision records from
hold-class parks.

## Tests (the REQ's acceptance block)

- AC2 `tests/test_decision_refound.py::test_validate_holds_park_no_decision`,
  `::test_rework_and_revalidate_work_without_decision_record`
- AC3 `::test_attended_park_is_a_hold_not_a_decision`
- AC4 `::test_skill_fork_parks_with_brief_and_list_renders_it`
- AC5 `tests/test_decide.py::test_decide_refuses_claude_and_unattended`,
  `::test_decide_records_choice_and_unblocks`
- AC6 `tests/test_decide.py::test_answered_fork_is_delivered_into_resumed_command`
- AC7 manual (validate phase, plain session).
