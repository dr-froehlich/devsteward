# REQ-089 AC2 — System Tester walkthrough

Observation surface (as named by AC2): the four doctrine surfaces, read cold, no builder
diff or session reasoning consulted.

- `devsteward/templates/.claude/skills/advance/SKILL.md` (§2, §4)
- `devsteward/templates/.claude/skills/intake/SKILL.md` (§2b)
- `devsteward/templates/STEWARD.md`
- `devsteward/handbook/_00-method.qmd`

## Pass condition (verbatim from AC2)

> a session reading ONLY /advance during an attended develop step, on a REQ whose proof
> requires pushing so CI can build and deploy, would conclude it MAY commit and push and
> that the proof belongs in this session; the batch prohibition still reads as absolute;
> `steward checkpoint` still reads as the terminal act; nothing states or implies that
> only a `concept: true` phase may reach the live system. Fail if any surface still
> fences the grant to `concept: true`, if the batch rule was loosened, or if /advance
> and /intake disagree.

## What each surface says

**advance/SKILL.md §2 "Iterate when the work needs the real world (REQ-089)"** (lines
92–103): states the round-trip-through-external-infrastructure trigger, says the grant
"is a property of the work, not of a flag: an empirical `concept: true` phase is one
instance, deploy-shaped develop work is another, and the next one will not be on any
list," and keys it "on **attended**." Names `steward checkpoint` as "the terminal act."

**advance/SKILL.md §2, "A proof that needs a deploy belongs in *this* session
(REQ-089)"** (lines 104–110): states the deploy proof must happen in the develop
session, attended, fixed in place — explicitly rejects deferring to System-Test ("the
System Tester runs in a fresh session that never sees the diff and cannot fix anything
… no repair loop").

**advance/SKILL.md §4 "Mid-phase commits — the attended grant (REQ-089)"** (lines
172–183): "*(interactive only)* … you **may commit and push mid-phase**, as often as the
iteration needs. The mechanism is **plain `git` commits by the session**; `steward
checkpoint` is *never* a mid-phase verb and stays the terminal act." Explicitly: "This is
a **grant keyed on attended**, not an exception on a list."

**advance/SKILL.md §4 batch clause** (lines 184–186): "*(batch)* do **not** commit (and
never create a branch). Leave the working tree dirty … Committing here would
*double-commit*." Unqualified, absolute, unchanged in strength.

Grep confirms **no occurrence** of "one sanctioned exception" anywhere in
`advance/SKILL.md`; the only `concept: true` mentions are (a) the unrelated
concept-phase-first bullet (§2 opening) and (b) the explicit "not a flag" clause that
generalizes the grant *off* `concept: true`. Neither fences the grant to it.

**intake/SKILL.md, "The deploy-shaped case, explicitly (REQ-089)"** (lines 175–182) and
the preceding live-proof-in-develop screen (lines 152–174): names the deploy-shaped case
as a develop-session obligation, and retains — verbatim — "the mid-phase deploy
permission is a grant, not a restriction that **only** concept phases may reach the live
system." Agrees with `/advance`.

**STEWARD.md** (lines 47–54): "**The one grant is attended (REQ-089):** an interactive
session whose work needs a round-trip through external infrastructure … may make plain
`git` commits and push mid-phase … A **batch** … session never commits … `steward
checkpoint` is never a mid-phase verb." Grep confirms **zero** occurrences of "One
exception" (the old empirical-`concept: true` parenthetical is gone).

**handbook/_00-method.qmd rule 4** ("Work that needs the real world iterates — attended
(REQ-089)", lines 46–58): "The grant is keyed on **attended** … not on a flag: an
*empirical* concept phase … is one instance, deploy-shaped develop work is another."
Restates checkpoint-as-terminal-act and the no-repair-loop reason deploy proofs stay out
of System-Test.

## Cross-surface consistency

`/advance` and `/intake` state the same rule (attended axis, grant not restriction,
deploy-shaped case named explicitly in both) — no disagreement found. The batch
prohibition is unqualified and unchanged in every surface it appears. No surface fences
the grant to `concept: true`; `STEWARD.md`'s old parenthetical exception is confirmed
removed by direct grep, not just by absence in a read-through.

## System Tester's observation

Every element of the AC2 pass condition is met on a plain textual read of the four named
surfaces, cold (no builder diff/session/plan consulted). No disqualifying condition
(concept-fenced grant, loosened batch rule, /advance–/intake disagreement) found.

**This is a report, not a verdict** — the manual sign-off itself belongs to the human
reviewer via the engine's own prompt, per the System-Test skill's division of labor.
