---
name: intake
description: Interview a raw idea into a schema-valid draft REQ. Use when the user has a new feature/change idea ("I want to add…", "we should support…", "intake this") that is not yet a requirement. Interrogates risks, scope, dependencies, and the English-code/localized-UI split, then writes a draft REQ + its index row.
---

# /intake — interview an idea into a draft REQ

You turn a raw idea into a **schema-valid draft requirement**. The interrogation is the
point: a sharp `/intake` is worth more than fast output. Institutionalize the questions.

## 1. Orient

- Read `CLAUDE.md`, `docs/requirements/REQ-001.md` (the north star), and
  `docs/requirements/REQUIREMENTS_INDEX.md`. The new REQ must advance REQ-001 or be
  explicitly scoped against it.
- Find the next free id: highest `REQ-NNN` in the index + 1, zero-padded.

## 2. Interrogate (the sacred part)

Ask, in `AskUserQuestion` form when interactive, until you genuinely understand:

- **Problem:** who hits it, how often, what's the cost of the status quo?
- **Scope boundaries:** what is explicitly *not* in this REQ?
- **Alternatives:** what simpler thing did we reject, and why?
- **Risks / weaknesses:** what could make this the wrong call?
- **Dependencies:** which existing REQs must be done first? (→ `depends_on`)
- **Acceptance:** what observable behaviour proves it works? Each criterion must map to a
  **runnable test** in this project's test command.
- **Localization split:** any user-facing strings? They stay isolated/translatable; all
  code and technical text is English.

**Park-and-surface:** if `DEVSTEWARD_UNATTENDED=1` is set, do **not** block on questions.
Instead write a decision request to the ledger and stop (see §4).

## 3. Emit

- Write `docs/requirements/REQ-NNN.md` from `_templates/req.md` with `status: draft`,
  filled frontmatter, a real Context/Decisions/Requirement, and a `yaml acceptance`
  block where **every** criterion has an `id` and a `test:`.
- Add its row to `REQUIREMENTS_INDEX.md` (status `DRAFT`).
- Add it under **Next** in `ROADMAP.md` and to the dependency graph.
- If scenarios help, add `SCN-NNN` files and reference them in `scenario_refs`.
- Run `steward lint` and fix anything it reports. Leave it green.

Do all of this in the **same commit** (frontmatter + index + roadmap together), branch
first, co-author trailer.

## 4. Unattended fork handling

When `DEVSTEWARD_UNATTENDED=1` and you hit a question you cannot answer from REQ-001 +
the repo, append to `.devsteward/state.yaml` under `decisions:` a record
`{id, step, question, status: open}` and stop without writing a half-baked REQ. The
engine surfaces it; resume when answered.
