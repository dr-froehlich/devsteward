# Plan 0036 — REQ-039: the concept phase, the *lightweight* way (a develop land-gate)

## Why this plan re-scopes REQ-039

REQ-039 was intaken 2026-06-14 as a full **symmetric phase**: a leading `REQ-NNN:concept`
step, a `steward concept` CLI verb, a `/concept` skill, a `concept.py` routine mirroring the
33 KB `validate.py`, an engine-recorded sign-off, and defer/decline routing — plus a
Decision 7 / AC6 built entirely on the **feature-branch** model ("the implementation feature
branch is created only when develop begins").

Two things make that spec wrong now:

1. **It is stale.** REQ-047/048 (landed) made the engine trunk-based — there are *no* feature
   branches (`executor.py`: *"REQ-048: trunk-based — no branch prepare, no merge"*). Decision
   7 / AC6 test behaviour that no longer exists.
2. **It is over-built for the need.** Validate carries its heavy machinery because of
   **decoupling** — the System Tester must be brought up in a fresh session that never sees
   the diff. REQ-039 itself states concept carries *none* of that decoupling. A coupled
   concept session is just the human + Claude thinking together — which is exactly what an
   interactive `/advance` session already is. So a `steward concept` verb + `/concept` skill +
   `concept.py` routine would add a parallel bring-up path for no isolation gain, against
   CLAUDE.md's "minimal topology / prefer subtraction / surface unnecessary complexity."

**Owner decision (interactive, 2026-06-21):** take the **lightweight doc-gate** path.

## The mechanism

`process.concept: true` keeps its existing semantics — it makes the single `develop` step
**attended** (`source.py`), so a batch run finds it ineligible and parks naming the attended
need. No new step, CLI verb, skill, or routine. The concept session *is* the attended develop
session: the human and Claude do the architecture/spike work, capture the conclusion in a
**concept document** at `docs/concepts/REQ-NNN.md`, then write the implementation plan against
it and build.

The engine's firewall is a **develop land-gate**, exactly mirroring the existing
`PlanArtifactGate` (the `docs/plans/` rule, REQ-029 D6): when — and only when — a REQ declared
`process.concept: true`, the mechanical land refuses unless

- `docs/concepts/REQ-NNN.md` exists, **and**
- the REQ's `concept_refs:` frontmatter references it (`…REQ-NNN.md`).

A refusal flows through the established REQ-056 land-refusal path: a `land_refused` event, the
develop step set FAILED (not BLOCKED, no parked decision), a clean committed ledger close, and
`steward repeat REQ-039` to recover once the human adds the doc/link. A REQ without the flag is
untouched.

Spikes/prototypes remain throwaway (never committed) — only the architectural conclusion
survives, in the concept doc. This is the same artifact-discipline as `docs/plans/`, one
altitude up.

## Files

- `devsteward/profiles/req/reqfile.py` — add a `concept_refs` accessor on `ReqFile` (mirrors
  `depends_on`).
- `devsteward/config.py` — add a `concepts_dir` property (`docs/concepts/`), mirroring
  `plans_dir`.
- `devsteward/profiles/req/checkpoint.py` — add `ConceptArtifactGate` (flag-conditioned doc +
  `concept_refs` existence check) and a small `CompositeLandGate` (first refusal wins).
- `devsteward/build.py` — `build_land_gate` composes `PlanArtifactGate` + `ConceptArtifactGate`.
- `tests/conftest.py` — let `write_req` set `concept_refs`.
- `tests/test_concept_phase.py` — the four regression ACs below.
- Docs (consistency, untested): `/advance` skill (concept-doc-first when `process.concept`),
  `/intake` skill + handbook `_01-format`/`_02-engine`/`_03-workflow`, `STEWARD.md` — describe
  the concept gate alongside the plan gate, and that concept is a *doc-gated attended develop
  session*, not a separate phase. (`/advance` & `/intake` skills are hardlinked to their
  templates — one edit updates both.)

## Acceptance (all `regression` — a pure engine gate, fully unit-testable; no new runtime
phase to observe, so no `manual`/validate phase, keeping the REQ light and self-consistent)

- **AC1** — `process.concept: true` makes the single develop step **attended** (batch parks it,
  naming the attended need) and emits **no separate `:concept` step**; a REQ without the flag
  has a non-attended develop step.
- **AC2** — when a REQ declared `process.concept: true`, the develop land **refuses** unless
  `docs/concepts/REQ-NNN.md` exists; with the doc present (and linked) it admits.
- **AC3** — the land **also** refuses when the doc exists but the REQ's `concept_refs:` does
  not reference it; once linked, it admits.
- **AC4** — a REQ **without** `process.concept` is never subject to the concept-doc gate (no
  `docs/concepts/` file required to land).

## Out of scope (unchanged from the original)

The first *real* consumer — FlowSteward's concept re-drive — stays its own follow-on. No
release-gate handling of concept docs, no staleness detection. `develop: split` is orthogonal
and untouched.
