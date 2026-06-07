# 04 · The skills

Three skills carry the cognitive work the engine orchestrates. They ship in
`templates/.claude/skills/` and are stamped into every consumer. The engine invokes them
headless; a human can also invoke them directly in an interactive session.

## `/intake` — interview an idea into a draft REQ

The interrogation skill, and the one to protect. Takes a raw idea and interrogates it —
problem, scope boundaries, alternatives, risks, dependencies, the acceptance tests, the
English-code/localized-UI split — then emits a **schema-valid draft REQ** (`status:
draft`), its index row, its roadmap entry, and any `SCN` scenarios. Leaves `steward lint`
green. A sharp `/intake` is the highest-leverage moment in the method; never rush it.

## `/advance` — one checkpoint

The generalized `/scaleup`. Orients from the ledger, does **exactly one** checkpoint
(Design, Build, or Land), stops at forks, runs the acceptance tests at Land, and ends
with the fixed report. It runs two ways with different contracts — headless under `steward
advance` / `steward run` (the engine verifies and commits; forks park) or directly in a
live session (the human verifies and the skill commits; forks ask). See the two-mode
contract in `03-workflow.md`.

## `/bootstrap` — bring a new project to life

Run once, right after `steward new`, while the scaffolding still has `{{placeholders}}`.
Interviews for stack + build/test commands, co-authors the frozen **REQ-001** north star,
fills the placeholders, writes `.devsteward/config.yaml`, makes the first commit, and
initializes the ledger.

## The park-and-surface contract

All three skills obey the same rule when `DEVSTEWARD_UNATTENDED=1` is set (batch mode): do
**not** block on `AskUserQuestion`. Instead append a decision request to
`.devsteward/state.yaml` under `decisions:` (`{id, step, question, status: open}`) and stop.
The engine surfaces it and advances to the next independent step. Without the env var
(interactive mode) the skills *do* ask via `AskUserQuestion` and continue — but that run
carries no engine guarantee; the human in the loop is the guarantee. Either way **the
interview stays sacred** — a fork is recorded or asked, never guessed.

## Renaming

Skill names (`/intake`, `/advance`, `/bootstrap`) are conventions, not hard-coded. The
REQ profile invokes `/advance`; if you rename it, update the profile's command string.
