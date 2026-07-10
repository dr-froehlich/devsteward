# Plan — REQ-078: `/advance` targets the in-context REQ; validations are out of scope

**Status:** develop (batch). Method-only fix — two hardlinked SKILL.md files, no engine/lint/schema.

## Problem (recap)

Interactive `/advance` with no explicit target self-orients off `steward status` and can
adopt a pending `REQ-NNN:validate` step — which it cannot actually close in a live session
(the guided validate path refuses inside Claude/CLAUDECODE). The session degrades into
validation-prep, burning a paid-for session. Two root causes: (a) intake's bare "run
advance" close never names the REQ; (b) `/advance` has no rule that a validate step is out
of scope.

## Approach

All ACs are `check: manual` (human oracle over prose changes), so REQ-078 carries a
System-Test phase: this develop checkpoint **commits the work on `dev`** and the land
defers to `steward validate REQ-078` in a plain session.

### Files touched (each edit is one inode — hardlinked twin updates automatically)

1. **`.claude/skills/advance/SKILL.md`** (twin: `devsteward/templates/.claude/skills/advance/SKILL.md`)
   - **§1 Orient — target selection (Decisions 1–3).** After the existing explicit-target
     line, add an interactive target-selection rule:
     - *Decision 1:* interactive, no explicit `REQ-NNN develop` target → if a REQ is fresh
       in the session context, **ask** (`AskUserQuestion`) whether to advance that REQ's
       develop step; on decline or empty context, auto-select the next eligible step. Batch
       always carries an explicit target — unchanged.
     - *Decision 2:* auto-selection **skips** any eligible `validate`/System-Test step and
       advances the next **develop**-eligible step. Validations are `/system-test`'s job.
     - *Decision 3:* if **no** develop step is eligible (only validations pending),
       **surface** the pending validation(s) with the exact `steward validate REQ-NNN`
       shell command and **stop** — never run a validation in-session.
   - Satisfies AC1 (in-context targeting, mode-scoped) and AC2 (skip-validate +
     surface-and-stop).

2. **`.claude/skills/intake/SKILL.md`** (twin: `devsteward/templates/.claude/skills/intake/SKILL.md`)
   - **§3 Emit — closing suggestion (Decision 4).** Add a close line: the suggested next
     command is `/advance REQ-NNN develop` naming the just-intook REQ — never a bare "run
     advance". Satisfies AC3. (Intake currently has no closing suggestion at all, so there
     is no bare form to remove — we add the precise form.)

### Non-goals

- No engine/CLI/lint/schema change: `steward advance` from a shell already routes validate
  steps to `/system-test`; the defect is skill-instruction only.
- Handbook/`STEWARD.md`: only touch if they restate step-selection in a way that now
  contradicts Decisions 1–3 (checked below).

## Verification

- `steward lint` stays green.
- AC1/AC2/AC3 are `manual` — read-and-confirm, closed via `steward validate REQ-078` in a
  plain session (this develop checkpoint defers the land).
