# Plan — REQ-069: build delivers the validation fixtures it owes

**REQ:** [REQ-069](../requirements/REQ-069.md) · one fused develop checkpoint, no concept
phase, no lab. Both ACs are `artifact`, so the REQ has a **System-Test phase**: the green
develop gate only commits the work (`develop_committed`), and the land fires after
`steward validate REQ-069`.

## Approach

A method correction on two prose surfaces, no engine change (REQ-069 Decision 2). REQ-051
built the validator's prohibition (*the System Tester never improvises a fixture*); this adds
the builder's matching duty on the two surfaces a builder and a reader of the method meet.

## 1. The `/advance` skill — §2, next to the REQ-089 bullet

`.claude/skills/advance/SKILL.md` is **one inode** with
`devsteward/templates/.claude/skills/advance/SKILL.md` (REQ-096), so one edit ships the duty
to every consumer through `steward sync`.

A new §2 bullet, **directly after** *"A proof that needs a deploy belongs in this session
(REQ-089)"* (Decision 2). Both bullets rest on one reason: the System Tester runs in a fresh
session and cannot repair anything, so the builder does now what validation cannot do later.
The bullet states:

- when the REQ carries `artifact` or `manual` ACs, this session builds **and commits on
  `dev`** every fixture, seeded sample project and lab starting-state their validation rests
  on;
- the System Tester may **not** create them (REQ-051): a missing fixture is a hard red it is
  forbidden to fill in;
- so an undelivered fixture deadlocks the validation, and only the Build phase can prevent it.

## 2. The handbook — `_03-workflow.qmd`, next to the REQ-051 bullet

`devsteward/handbook/_03-workflow.qmd`, section *Labs — owned fixtures with reality-derived
provenance*. A new bullet **directly after** *"Fixtures are committed upstream; the System
Tester never improvises (REQ-051)"*, so the prohibition and the duty read as the two halves of
one rule. Same content as the skill bullet, in the handbook's descriptive voice.

## 3. Grading tests — `tests/test_req069_fixture_duty.py`

Both read **only** the evidence dir the engine hands an `artifact` grading command
(`DEVSTEWARD_EVIDENCE_DIR`, REQ-075). The develop gate deselects them project-wide (REQ-068).
Under a bare `python -m pytest` the variable is unset and they **skip**: there is no evidence
outside a validation, the same skip-if-absent shape FlowSteward's grading tests use. A
captured file that is missing **fails**, never skips.

| Test | Evidence file | Asserts |
|---|---|---|
| `test_evidence_stamped_advance_skill` (AC1) | `advance-SKILL.md`, captured from a fresh `steward new` | §2 (between `## 2.` and `## 3.`) has a top-level bullet naming REQ-069 that states the duty: `artifact`/`manual`, fixture, seeded sample project, lab starting-state, commit on `dev`, the System Tester, REQ-051. That bullet is **adjacent** to the REQ-089 *"A proof that needs a deploy belongs in"* bullet. |
| `test_evidence_handbook_workflow` (AC2) | `_03-workflow.qmd`, captured from `dev` | In one `##` section, the REQ-051 *"Fixtures are committed upstream; the System Tester never improvises"* bullet and a bullet naming REQ-069 that states the build-side duty are **adjacent**. |

Bullets are split on top-level `- ` lines, so adjacency is structural, not a line distance.

## 4. Proof in this session

The grading tests are run here against evidence captured by hand (a `steward new` into a temp
dir + a copy of the handbook), green, and once against a deliberately broken copy, red, so the
validation has been seen to discriminate before the System Tester runs it.

## Not touched

- **`STEWARD.md`** (REQ-094): no verb, flag, engine behaviour or frontmatter field changes, and
  the manual does not mention fixtures today. The duty ships in the skill itself.
- **No engine code.** The left-shift tooth stays out of scope (Decision 3).
- **No backlog item** exists for this REQ (it predates REQ-093); none is created.
