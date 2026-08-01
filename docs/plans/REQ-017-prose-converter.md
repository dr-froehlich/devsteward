# REQ-017 — Legacy prose REQ converter (`scripts/convert_reqs_prose.py`)

Implementation plan for [REQ-017](../requirements/REQ-017.md). The REQ fixes the *what* and
the nine decisions; this plan fixes the *how* — the grammar, the module surface, the file
list and the test-to-AC mapping.

## Input grammar (verified against THermo's 12 REQs)

```
### REQ-NNN: <title>            ← level-3 header, supplies id + title

- **Status:** DONE              ← the eight field bullets, column 0
- **Added:** 2026-04-07
- **Completed:** 2026-04-07     ← or `–` (U+2013 EN DASH)
- **Verified by:** idf.py build clean 2026-04-07
- **Depends on:** REQ-001, REQ-002        ← or `–`
- **Description:**

<prose at column 0 *or* indented 2 — both shapes occur; #### sub-headings,
tables, fenced blocks and its own bold bullets live here>

- **Acceptance criteria:**
  - [x] …
  - [ ] …
- **Notes:**
  <prose>
```

**The discriminator is the known field name, never bullet shape.** The Description body
contains bullets that look identical to a naive matcher — `- **MAC address**: Replace …`,
`` - **`FactoryReset()`** — delete … `` — at column 0. Two facts separate them, and we rely
on the first:

1. **Primary:** the bold text, colon-stripped and normalized, is one of the eight known
   field names. `MAC address` is not.
2. *Incidental (not relied on):* fields put the colon **inside** the bold (`**Status:**`),
   look-alikes put it outside (`**MAC address**:`). True across all 12 files, but too
   fragile to be the rule.

Field-name normalization: strip a trailing `:`, lowercase, spaces → underscores.
`Verified by` → `verified_by`, `Acceptance criteria` → `acceptance_criteria`.

## Module surface — `scripts/convert_reqs_prose.py`

Imports the core from `convert_reqs.py`; **duplicates nothing** (REQ Decision 3).
Reused as-is: `normalize_frontmatter`, `infer_kind`, `dump_frontmatter`,
`parse_acceptance_checkboxes`, `transcode_acceptance_block`, `_convert_acceptance`,
`splice_index`, `build_index`.

| Function | Responsibility |
|----------|----------------|
| `ProseParseError` | Exception carrying the file name + the reason. Raised, never swallowed |
| `split_fields(text)` | Header → `(id, title)`; body → an ordered `{field: segment}` map, splitting only at known field bullets at column 0 |
| `coerce_status(token, *, where)` | The fixed table; unknown → `ProseParseError` |
| `coerce_date` / `coerce_text` / `coerce_deps` | `–`/`-`/empty → `None` / `[]`; a malformed date → `ProseParseError` |
| `build_body(rid, title, segments)` | The restructured markdown, pre-transcode |
| `demote_unrunnable_active(status, seg)` | Decision 10 — an active status with no runnable criterion becomes `draft` |
| `convert_prose_text(text)` | One file: parse → frontmatter + body → hand to the core. Already-frontmattered input returns **unchanged** (idempotence) |
| `convert_corpus_prose(src, dst)` | Parse **all** files first, write **only** if every one parsed. Returns a `ConversionReport` |
| `ConversionReport` | `reqs`, `title_conflicts`, `demotions` — everything the operator must be told |
| `main(argv)` | `src dst` CLI, mirrors `convert_reqs.py`; prints conflicts and demotions |

### Decision 10 — the active-import demotion (added during build)

The trial conversion turned `steward lint` red with **66 problems**, all from THermo's two
*active* REQs (011 in-progress / 012 open, 33 criteria between them, no test ids). `lint.py`
rule 5 fires on active REQs only, by REQ-010 Decision 4's design. The converter may not
invent a test id nor re-adjudicate a status, so the only honest landing spot is `draft`:
exempt from rule 5, produces no engine steps, and true. Verdicts are untouched; the operator
runs `steward activate` once real criteria exist. Terminal statuses are never demoted.

### Restructured output (Decision 4)

```
---
<canonical frontmatter, dump_frontmatter's field order>
---

### REQ-NNN: <title>            ← preserved, deliberately (REQ Notes: the cosmetic wart)

## Requirement

<Description segment, dedented, verbatim otherwise>

## Acceptance criteria

```yaml acceptance
…
```

## Notes

<Notes segment, dedented>
```

The acceptance block is produced by emitting the raw checkbox list under a literal
`## Acceptance criteria` heading and then running the core's `_convert_acceptance` over the
assembled body — its anchor is `^## Acceptance criteria`, so the core transcodes rather than
being special-cased. No `## Context` / `## Decisions` is emitted: the dialect has no source
field for either, and the converter does not invent sections (REQ Notes).

### Transactionality (Decision 6)

`convert_corpus_prose` runs in two passes: **parse every file into memory**, collecting
`ProseParseError`s; if any, raise with all of them and write **nothing** — no REQ file, no
index. Only a fully-parsed corpus reaches the write pass. `REQ-xxx.md` is skipped by stem
before parsing (the `reqfile.load_reqs` rule), so a template stub is never an error.

### Dedent

`textwrap.dedent` over the Description/Notes segments — both the column-0 (REQ-004) and
indented-2 (REQ-012) shapes occur. The acceptance segment is dedented too; continuation
lines keep their *relative* indent, so `parse_acceptance_checkboxes`'s continuation rule
still fires.

### Idempotence (AC7)

A file already starting with `---` is returned byte-unchanged. That makes a second run over
converted output a true no-op, and keeps the prose converter from fighting the frontmatter
one over a mixed corpus.

## Files

| File | Change |
|------|--------|
| `scripts/convert_reqs_prose.py` | **new** — the whole front-end |
| `tests/test_convert_reqs_prose.py` | **new** — 8 tests, one per AC |
| `tests/fixtures/thermo_reqs/` | **new** — all 12 THermo REQs + `REQUIREMENTS_INDEX.md` + the `REQ-xxx.md` stub, captured verbatim |
| `tests/fixtures/thermo_reqs_golden/` | **new** — the reviewed converted output (12 files + index) |
| `scripts/convert_reqs.py` | **untouched** (Decision 3) |

## AC → test mapping

| AC | Test |
|----|------|
| AC1 | `test_parses_headers_and_ignores_body_bullets` |
| AC2 | `test_status_vocabulary_and_unknown_token_aborts` |
| AC3 | `test_acceptance_transcodes_via_shared_core` |
| AC4 | `test_body_sections_map_and_prose_rides_verbatim` |
| AC5 | `test_header_title_wins_and_conflict_is_reported` |
| AC6 | `test_unparseable_aborts_atomically_and_stub_is_skipped` |
| AC7 | `test_thermo_corpus_matches_goldens_and_is_idempotent` |
| AC8 | `test_thermo_corpus_lints_clean_and_index_prose_survives` |

AC8's lint runs against a `Config(root=tmp, requirements_dir=".", index_file="…")` — the
same hermetic shape `test_memzy_fixture_corpus_lints_clean` already uses. The goldens are
generated once and **read** before committing; a generated-and-trusted golden proves nothing.
