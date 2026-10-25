# 0037 — Converter index splice (REQ-023)

**Date:** 2026-06-21
**REQ:** [REQ-023](../requirements/REQ-023.md) — *Converter index splice — replace only the
REQ table, preserve a project's surrounding index prose.*
**Builds on:** [0004 — memzy converter (REQ-010)](0004-memzy-converter.md),
[0005 — memzy onboarding](0005-memzy-onboarding.md) Piece 2.

## Problem

`scripts/convert_reqs.py`'s `convert_corpus` writes `build_index(...)` over the **entire**
`REQUIREMENTS_INDEX.md`. memzy's index is more than a REQ table — it also carries a
**Planned** table (`| Proposed | Title |` rows) and a **Scenarios** section (`SCN-*` rows).
Running the converter in place (plan 0005 Piece 2) would silently discard those sections,
breaking REQ-010 Decision 7's "idempotent and non-destructive" contract for any index richer
than the REQ-010 fixtures.

## Decision (REQ-023)

**Splice**: replace only the machine-generated REQ table inside an existing index; preserve
every other section byte-for-byte. With no pre-existing index (or one with no REQ table),
emit a whole file as today (back-compat). The operation stays idempotent/byte-stable.

## Locating the table to replace (REQ-023 Decision 2)

The REQ table is identified by its **data rows**, not by heading text. A REQ data row is a
`| REQ-NNN | … | STATUS | … |` row — exactly what `devsteward.profiles.req.index.INDEX_ROW_RE`
already matches (the same contract lint reads statuses through). Key property that makes this
safe against the surrounding prose:

- memzy's **Planned** rows are `| REQ-010 | title |` — only **three** pipes (two cells).
  `INDEX_ROW_RE` requires the four-pipe `| id | title | STATUS |` shape, so Planned rows do
  **not** match. Scenarios rows start with `SCN-`, also no match. Only the main REQ table's
  rows match → the anchor lands in the right table.

Algorithm (`splice_index`):

1. Find the first line matching `INDEX_ROW_RE` (the anchor). None → no REQ table → fall back
   to `build_index` (whole file), per Decision 3.
2. Expand the region up and down over the contiguous block of `|`-leading lines around the
   anchor. This captures the column header, the separator, and **all** data rows — including
   rows whose status cell is not a bare word (e.g. memzy's historic
   `superseded *(by REQ-020)*`, which `INDEX_ROW_RE` itself would skip). Contiguity stops at
   the blank line before `## Planned`, so the Planned/Scenarios blocks are never absorbed.
3. Replace that line span with a freshly rendered table; splice the unchanged prefix/suffix
   back verbatim; preserve the original trailing newline.

## Code shape

- Extract `_render_table(reqs)` — the header + separator + one row per REQ (the bytes
  `build_index` already emits; unchanged formatting, lowercase status as before).
- `build_index(reqs)` = `"# Requirements Index\n\n" + _render_table(reqs) + "\n"` (whole-file
  path, unchanged output).
- New `splice_index(existing, reqs)` — the algorithm above; falls back to `build_index` when
  `existing` has no REQ table.
- `convert_corpus`: if `REQUIREMENTS_INDEX.md` already exists in the destination, splice into
  it; otherwise write a whole file. (In-place onboarding has `src == dst`, so the index
  exists → splice.)

## Files touched

| File | Change |
|------|--------|
| `scripts/convert_reqs.py` | add `_render_table` + `splice_index`; `build_index` delegates; `convert_corpus` splices into an existing index |
| `tests/test_convert_reqs.py` | the four REQ-023 acceptance tests (AC1–AC4) |

## Acceptance (REQ-023)

- **AC1** `test_index_splice_preserves_surrounding_prose` — splice into an index with a
  Planned table + Scenarios section; those sections survive byte-for-byte; the REQ table is
  replaced (a stale row with no backing file is gone).
- **AC2** `test_spliced_index_rows_parseable_and_synced` — after splice, `read_statuses` over
  the index returns exactly the corpus ids with status synced to frontmatter (Planned ids are
  not picked up; the stale id is gone).
- **AC3** `test_index_whole_file_when_absent` — no pre-existing index → output equals
  `build_index`, starts with `# Requirements Index`, and the corpus lints clean.
- **AC4** `test_index_splice_idempotent` — converting the same corpus in place twice is
  byte-stable, preserved prose included.

## Out of scope

Converting the *content* of the Planned table or Scenarios (they stay living docs — plan 0005
scope); the seeder ([[REQ-022]]) and the `onboard` orchestration ([[REQ-024]]).
