# Plan 0032 — REQ-057: post-REQ-047 documentation refresh + a Claude-targeted `steward` manual

Covers **REQ-057**.

## Goal

Bring all DevSteward documentation current with the post-REQ-047 trunk-based engine, give an
agent a black-box `steward` manual so it never reads the package source, align the bundled
skills' verbs, and close state F's circular-answer trap in code.

## Surfaces and changes

### 1. AC1 — close state F's circular-answer trap (`devsteward/cli.py`)

`steward decision answer` is for **genuine forks** (parked from a `develop` step). A
validation-phase hold — a `manual`-AC await (state F) or a red validation — is parked on a
`REQ-NNN:validate` step and has dedicated verbs (`steward validate` for the pending sign-off;
`steward rework` / `steward revalidate` for a red). Answering it via `decision answer` flips
the validate step `BLOCKED → PENDING`; unattended it re-runs, still can't reach the human, and
**re-parks** — the circular trap REQ-056 removed for D/H.

Fix: in `decision_answer`, fetch the decision first; if its `step` is a `:validate` step,
**refuse** with a `ClickException` that redirects to `steward validate {req}` (and names
`rework`/`revalidate` for the red case), **before** any mutation — so the validate step stays
`BLOCKED` and the decision stays `OPEN` (no re-park). A develop-phase fork is unaffected.

### 2. AC2 — the Claude-targeted manual (`devsteward/templates/STEWARD.md` + `CLAUDE.md.tmpl`)

- New `devsteward/templates/STEWARD.md`: a terse, agent-facing operating manual for the
  `steward` command surface — the public interface, treating the engine as a black box. Covers
  the develop→validate→land workflow and the recovery path out of **every** red/parked state
  without any reference to DevSteward internals.
- It rides the existing `templates/**/*` package-data glob and `_stamp` copy (no new
  machinery): `steward new` writes it to the consumer root as `STEWARD.md` (no placeholders, so
  the plain `.md` is copied verbatim through substitution).
- `CLAUDE.md.tmpl` gains a reference naming `STEWARD.md` as the authoritative `steward` usage
  doc and stating the black-box rule (use the CLI + `STEWARD.md`, never read the engine source).

### 3. AC3 — current verbs/topology across handbook + skills

- Completely revise `devsteward/handbook/_00-method.qmd`, `_02-engine.qmd`, `_03-workflow.qmd`
  to post-REQ-047 reality: remove all feature-branch / worktree / engine-switching / `--no-ff`
  merge-topology language; describe the trunk-based dev-only model; document the recovery model
  as one coherent section — `repeat` (re-run a FAILED step), the `rework`-vs-`revalidate`
  root-cause choice on a red validation, D/H → `repeat` (not a decision, REQ-056), and the
  async-QA / state-F path (`steward validate`, not `decision answer`).
- Update `advance/SKILL.md` prose `recover` → `repeat` (edited once via the
  `[[skills-hardlinked-to-templates]]` inode; repo and template are one file).
- No occurrence of `steward recover` as a live command in handbook, manual, or skills.

## Tests

- `tests/test_system_test_phase.py::test_pending_validation_decision_answer_redirects` — AC1.
  Park a validation hold on `REQ-001:validate`, run `steward decision answer` via `CliRunner`
  on a real git+config scaffold (`_scaffold`/`_init_git`): assert non-zero exit, message names
  `steward validate REQ-001`, step stays `BLOCKED`, decision stays `OPEN`. A develop-phase fork
  is answered normally (exit 0, step → `PENDING`).
- `tests/test_steward_manual.py::test_claude_manual_ships_stamped_and_referenced` — AC2.
  Manual present in `devsteward/templates/`; `steward new` stamps `STEWARD.md` to the consumer
  root; stamped `CLAUDE.md` references it.
- `tests/test_steward_manual.py::test_docs_and_skills_use_current_verbs` — AC3. Handbook + the
  manual name `repeat` and `revalidate`; bundled skills name `repeat`; none of the three
  presents `steward recover` as a live command.
- AC4 is `manual` — a human signs off completeness + black-box sufficiency at the validate
  phase. The develop gate therefore commits the work (`develop_committed`); the land defers to
  `REQ-057:validate`.

## Notes

- English-only throughout; no localized UI strings.
- A repo-root live copy of `STEWARD.md` for dogfounding is optional (not required by
  acceptance); skipped to keep the change minimal — when developing DevSteward itself, reading
  the engine source is legitimate, so the manual is primarily a consumer-facing template.
