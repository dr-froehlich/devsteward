# REQ-071 AC2 — guided coherence walkthrough

Observation surfaces read in full (plain reading session, no lab/account needed):

- `STEWARD.md` (214 lines)
- `.claude/skills/intake/SKILL.md` (200 lines)
- `.claude/skills/advance/SKILL.md` (146 lines)
- `devsteward/handbook/_00-method.qmd` (92 lines)

## Decision-rule anchor ("cannot be honestly written at intake")

| Surface | Present? | Location |
|---|---|---|
| STEWARD.md | yes | L61 "set `process.concept: true` when the acceptance criteria **cannot be honestly written at intake**" |
| intake SKILL.md | yes | L154-155, decision rule stated verbatim |
| advance SKILL.md | not required by AC1 (advance owns rule 4 only) | — |
| handbook _00-method.qmd | yes | L35-36, under "Earning the acceptance criteria" |

## The five rules, per surface

1. **Concept-phase-as-functional-spec** — STEWARD.md L60-71; intake L143-159 (`concept:` declaration); handbook L34-40 (rule 1).
2. **Wire-through-the-live-entrypoint** — STEWARD.md L159-162 ("Authoring doctrine" section); intake L60-65 (§2a); handbook L41-44 (rule 2).
3. **Don't-scope-a-known-defect-out** — STEWARD.md L163-165; intake L67-71 (§2a); handbook L45-47 (rule 3).
4. **Concept-phase-iterates-until-frozen** — STEWARD.md L63-67; advance L63-78 (§2, concept-first paragraph) — contains the "terminal act" anchor and no longer carries "never commit prototype code"; handbook L48-52 (rule 4).
5. **Phase-model-placement** — STEWARD.md L67-71; intake L160-169 (contains "never carry the downstream REQ's acceptance bar" anchor); handbook L53-59 (rule 5).

## Cross-doctrine coherence checks

- Rule 4 terminal-checkpoint semantics (STEWARD.md, advance) read consistent with the
  checkpoint contract: "one authoritative commit," "sanctioned over an already-clean tree,"
  matches REQ-018's checkpoint-as-bookkeeper framing; references REQ-067's bundle-directory
  committed-prototype form in both STEWARD.md and intake.
- Rule 5's split-or-downstream fork (intake §2c) sits directly beside the `develop: split`
  declaration and the `check:` lane taxonomy (§2b) without contradicting it; the
  "never carry the downstream REQ's acceptance bar" clause names the FlowSteward REQ-081 AC6
  trap explicitly in both STEWARD.md and intake.
- advance/SKILL.md confirmed to NOT contain the string "never commit prototype code" (the
  stale REQ-067-contradicting line) anywhere in its 146 lines.
- No contradictions found against the existing REQ-027/064/068 `check:`-lane doctrine or the
  REQ-039/067 concept-gate text; the four surfaces state the same five rules in consistent,
  non-conflicting language (expected parallel restatement, not the kind of duplication the
  Requirement text warns against — that clause targets duplicating the *existing* taxonomy,
  not the deliberate four-surface restatement this REQ requires as its wiring proof).

## Anomalies observed

None. All four surfaces edited; all five rules + the decision-rule anchor recognizable;
advance/SKILL.md's stale line confirmed absent.
