---
name: bootstrap
description: Bring a freshly-stamped DevSteward project to life. Use once, right after `steward new`, when CLAUDE.md / REQ-001 still contain {{placeholders}}. Interviews for stack and build/test commands, co-authors REQ-001 (the north star), fills placeholders, writes config, and initializes the ledger.
---

# /bootstrap — bring a new project to life

Run once, at creation. The repo has been stamped from DevSteward's templates and still
has `{{PLACEHOLDER}}` tokens. You make it a living project.

## 1. Interview

Use `AskUserQuestion`. Establish:

- **Project name** and one-paragraph **purpose** (this becomes REQ-001).
- **Who it serves** and the single **north-star outcome**.
- **Stack** (language, framework, key libraries).
- **Build command** and **test command** (exact shell invocations).
- Any **localization** needs (which languages; remember: code English, UI isolated).

Interrogate like `/intake` does — a vague north star poisons everything downstream.

**Mid-turn explanations are swallowed — put context inside the question (2026-07-17
marker test).** Text emitted *after a tool result and followed by another tool call* is
never rendered — exactly where an interview's between-question explanations land. Anything
the operator must read to answer goes **inside the `question` field / option descriptions /
previews**; when the context is longer than a question can carry, **end the turn** with the
explanation as final text and ask in plain prose, waiting for the reply.

## 2. Fill the scaffolding

- Replace every `{{…}}` placeholder in `CLAUDE.md` and `REQ-001.md` (in the requirements
  dir — `requirements_dir` in `.devsteward/config.yaml`, default `docs/requirements/`)
  (set `{{TODAY}}` to today's date; `{{TEST_COMMAND}}` must be the real test command, so
  REQ-001's acceptance test actually runs).
- Confirm `.devsteward/config.yaml` matches the chosen layout and account provider — in
  particular the four doc-path keys (`requirements_dir`, `index_file`, `plans_dir`,
  `concepts_dir`). If this project's `docs/` belongs to a docs generator, point them
  somewhere else **now** and move the stamped scaffolding to match.
- Co-author **REQ-001** properly: a tight, frozen north star — a compass, not a spec.
- Update `REQUIREMENTS_INDEX.md` to match.

## 3. Bring it to life

- `git init` if needed. `main` is production and `dev` is the integration branch (the
  default working branch) — create `dev` and make the **first commit** there (not on `main`,
  which the engine refuses to autocommit onto), co-author trailer. All work — declaration
  and implementation alike — lands on `dev`; the engine never branches.
- Ensure the ledger exists (`steward init` if `.devsteward/state.yaml` is absent).
- Run `steward lint` — leave it green.
- Tell the user the next move: `/intake "<first real idea>"`, then `steward run`.

This skill should not be needed again; day-to-day work is `/intake` + `/advance`.

## Park-and-surface

`/bootstrap` is normally run interactively. If it is ever invoked headless with
`DEVSTEWARD_UNATTENDED=1` set, obey the same contract as the other skills: do **not**
guess at the north star or the build/test commands — append a decision request to
`.devsteward/state.yaml` under `decisions:` (`{id, step, question, status: open}`) and
stop. A wrong north star poisons everything downstream, so a fork here is always parked,
never guessed.
