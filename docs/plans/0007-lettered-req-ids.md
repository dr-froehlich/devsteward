# 0007 — Lettered REQ ids (REQ-021)

**Date:** 2026-06-09
**Status:** **DESIGN.** Build-ready implementation design for REQ-021. Confirms the code
audit in REQ-021 holds against the live tree and pins the exact edit sites + the six
acceptance-test stubs. No production code yet.
**Author:** Peter Fröhlich + Claude (REQ-021 design checkpoint)
**Scope:** Implements [0005 — Onboard memzy](0005-memzy-onboarding.md) **Piece 1**. Purely
lexical; family/umbrella semantics are explicitly out of scope (REQ-021 Decision 1).

## The change in one line

Relax `^REQ-[0-9]{3}$` → `^REQ-[0-9]{3}[a-z]?$` in the three places the REQ-id format is
enforced, leave `SCN-` and `source.py` untouched, and pin with tests that the opaque
id-handling paths already tolerate the suffix.

## Audit confirmed against the live tree

The REQ-021 claim — "the only id-number regex in the engine is `lint._INDEX_ROW_RE`; ids
otherwise flow as strings" — checks out:

- `devsteward/profiles/req/source.py:62` builds steps as `f"{r.id}:{phase}"` and reads
  `r.id` verbatim; nothing parses the digits. **No change.**
- `devsteward/profiles/req/reqfile.py` reads `id` from frontmatter as a string; validation
  is delegated to the schema. **No change.**
- `glob("REQ-*.md")` already matches lettered files. **No change.**
- The two schema copies and `lint._INDEX_ROW_RE` are the only `REQ-NNN`-shaped patterns.

## Exact edit sites (Build)

### Format relaxation — `^REQ-[0-9]{3}$` → `^REQ-[0-9]{3}[a-z]?$`

Both schema copies, identical edits (they must stay in sync — REQ-021 Decision 3):

| File | Line | Field | Change |
|------|------|-------|--------|
| `devsteward/schema/req.schema.json` | 12 | `id` | add `[a-z]?` |
| `devsteward/schema/req.schema.json` | 42 | `depends_on` items | add `[a-z]?` |
| `devsteward/schema/req.schema.json` | 57 | `supersedes` | add `[a-z]?` |
| `devsteward/templates/docs/requirements/schema/req.schema.json` | 12 | `id` | add `[a-z]?` |
| `devsteward/templates/docs/requirements/schema/req.schema.json` | 42 | `depends_on` items | add `[a-z]?` |
| `devsteward/templates/docs/requirements/schema/req.schema.json` | 57 | `supersedes` | add `[a-z]?` |

`SCN-` (line 52 in both) is **left unchanged** — out of scope.

### Index-row matcher — `devsteward/lint.py:29`

`r"^\|\s*(REQ-\d{3})\s*\|..."` → `r"^\|\s*(REQ-\d{3}[a-z]?)\s*\|..."`. Clears the
"missing a row" false positive for a lettered id and lets its status be sync-checked.

### Next-id allocation — intake skill prose (REQ-021 Decision 5)

Both copies, the bullet at `SKILL.md:16` ("Find the next free id: highest `REQ-NNN` in
the index + 1, zero-padded."):

- `.claude/skills/intake/SKILL.md`
- `devsteward/templates/.claude/skills/intake/SKILL.md`

Add an instruction to **strip any trailing lowercase letter before taking the max**, so a
lettered id (`028p`) is read as `028`, never `0281`-like, and never skews the next number.
This is a markdown instruction the model executes, not Python — so AC5 asserts on the
skill text, not behavior.

## Acceptance-test stubs (Build)

| AC | Test | What it pins |
|----|------|--------------|
| AC1 | `tests/test_lint.py::test_lettered_id_schema_accepts_and_rejects` | schema validates `REQ-099z` for id/`depends_on`/`supersedes`; rejects `REQ-099ab`, `REQ-0991` |
| AC2 | `tests/test_lint.py::test_lettered_id_index_row_synced` | a lettered REQ with its index row present lints clean (no "missing a row"), status synced |
| AC3 | `tests/test_lint.py::test_lettered_id_depends_on_resolves` | `REQ-027 → REQ-028p` passes schema + cross-ref resolution |
| AC4 | `tests/test_req_profile.py::test_lettered_id_step_derivation` | a reopened/active lettered REQ yields `REQ-NNNx:design/build/land`; a dependent's edge resolves to `REQ-NNNx:land` (guards `source.py`, expected no code change) |
| AC5 | `tests/test_skills.py::test_intake_next_id_strips_letter_suffix` | **both** intake `SKILL.md` copies instruct stripping the trailing letter |
| AC6 | `tests/test_dogfood_lint.py` + `tests/test_convert_reqs.py::test_memzy_fixture_corpus_lints_clean` | own corpus still green; memzy fixture corpus extended with a lettered-id fixture converts + lints clean |

### Notes for the test author

- **AC4** exercises the otherwise-dark path: memzy's lettered REQs land as `done` (no
  steps), so step derivation for a lettered id is never hit in normal flow. The test
  constructs an *active* lettered REQ (e.g. via the `ReqFile`/profile fixtures already used
  in `test_req_profile.py`) and asserts the three phase steps + a dependent edge to
  `:land`. If this test needs a `source.py` change, the audit was wrong — but it should not.
- **AC5** extends the existing `tests/test_skills.py`, which today only reads the template
  copy via `SKILLS_DIR`. The new test must read **both** the repo-root
  `.claude/skills/intake/SKILL.md` and the template copy and assert the strip instruction
  in each.
- **AC6** adds a lettered-id fixture to `tests/fixtures/memzy_reqs/` authored in memzy's
  **source dialect** (so the REQ-010 converter normalizes it) — e.g. a `REQ-028p` file plus
  its index row and a `depends_on` reference from a sibling — and the existing
  `test_memzy_fixture_corpus_lints_clean` then covers it. Keep the fixture minimal.

## Why this can't regress a native repo

Widening a regex only *adds* matches; every existing 3-digit id validates and behaves
identically. AC6 makes that explicit by keeping DevSteward's own dogfood lint and the
memzy fixture corpus green. The relaxation is strictly additive.

## Out of scope (restated from REQ-021)

- Family/umbrella semantics — no parent rollup, no grouped ordering, no lint for a
  `REQ-NNN` umbrella file. Purely lexical.
- Multi-letter / numeric suffixes (`028ab`, `028-2`) — single `[a-z]` only.
- The `SCN-` id format and converting memzy's scenarios.
- Running the converter on memzy / seeding its ledger — plan 0005 Pieces 2–5, separate acts.
