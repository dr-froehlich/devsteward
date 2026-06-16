# FINDING — the guided session did NOT guide the human through the manual AC (AC6)

This is the central observation of the REQ-034 live e2e (AC6), surfaced by Peter:
the FlowSteward `steward validate REQ-024` session drove AC4/AC5 (artifact), captured
evidence, and **ended without ever guiding the human through AC6** (the manual homelab
sign-off) — no surfaces prepared for it, no walkthrough, no questions taken. The exact
REQ-030-D4 "present + record" asymmetry REQ-034 set out to amend, reproduced live.

Contrast: THIS session (REQ-034's own guided validator) gave Peter a full stepwise
tutorial — because it runs devsteward's repo skill on the req-034 branch.

## Attribution (facts)

| Artifact | State |
|---|---|
| devsteward engine (editable pipx -> req-034 branch) | guard + editor-pattern bring-up present (confirmed, files 10/40) |
| devsteward repo skill `.claude/skills/system-test/SKILL.md` | 5123 B, Jun 14 03:20, inode 358283, REQ-034 guided section present |
| devsteward template `devsteward/templates/.claude/skills/system-test/SKILL.md` | 5123 B, Jun 14 03:20, inode 358283 (HARDLINKED to repo skill), IDENTICAL |
| FlowSteward stamped `.claude/skills/system-test/SKILL.md` | 3387 B, **Jun 11 16:32**, inode 209448, **pre-REQ-034, NO guided section** |

REQ-034's "kept identical (repo + template)" deliverable holds (hardlinked, identical).
The failure is that the **consumer's stamped copy is stale** — it predates REQ-034 and
was never refreshed, so `--guided` silently no-ops in the consumer.

## Why this is more than "just re-stamp FlowSteward"

- Consumers run their OWN stamped `.claude/skills/`, frozen at `steward new` time. The
  engine is editable/always-current; the skill is frozen. The two can drift.
- There is **no first-class consumer skill-refresh command** in the CLI surface captured
  (`activate advance checkpoint decision init lint new recover rework run status validate`
  — no "update"/"sync-skills"). The only refresh paths are manual copy or re-`steward new`.
- When they drift, `steward validate --guided` produces the OLD bare behavior **silently** —
  no signal that the guided half was absent. That is the "green-but-hollow" shape: engine
  mechanics pass (guard, bring-up, gate, verdict-record) while the human still gets no
  guidance — the very outcome REQ-034 exists to prevent.
- Note the parallel: devsteward already hardlinks repo-skill <-> template so they cannot
  drift INTERNALLY. There is no equivalent guarantee between the template and a CONSUMER's
  stamped copy.

## Two readings (Peter's to adjudicate for the AC6 verdict)

- A) REQ-034 is correct; FlowSteward merely needs its skill refreshed. Refresh the stamped
  skill from the template, re-run, and the guided AC6 walkthrough should appear.
- B) REQ-034 is half-delivered in practice: it ships the engine half but leaves the
  human-guidance half in a stamped artifact consumers must manually keep current, with no
  refresh command and no drift signal — so a real consumer just got zero AC6 guidance.

## Suggested disambiguation (Peter's choice; tester does not repair)

Refresh FlowSteward's stamped skill from the current template, e.g.:
    cp /home/peter/projects/devsteward/devsteward/templates/.claude/skills/system-test/SKILL.md \
       /home/peter/projects/flowsteward/.claude/skills/system-test/SKILL.md
then re-run `steward validate REQ-024` from a plain shell and observe whether the manual
AC6 now gets a prepared-surfaces + walkthrough + questions session. Result distinguishes A
from B.

## Verdict authorship

None asserted. AC6 of REQ-034 is Peter's manual decision against Decisions 1-7; the engine
records his verdict. This file is reviewable evidence only.
